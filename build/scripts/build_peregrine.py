#!/usr/bin/env python3
import os
import sys
import config_parser
import subprocess
import shutil
import glob
from pathlib import Path
import argparse
import shlex
import json
import jsonpickle
from build_utils import *
import tempfile
import fdt_patcher

import fdt

class Builder:
    BUILD_ROOT = f"{os.getcwd()}/../"
    config: config_parser.PlatformConfig = None
    env_exports = {}

    ##### Start of hooks

    @classmethod
    def setup(cls):
        """ Hook for setup function """
        if cls.config.name == "fvp":
            cls.make_platform_tools()

        cls.make_uboot_tools()

    @classmethod
    def after_vm_built(cls, vm):
        """ Hook called for each VM that has been built

        Args:
            vm (VM): VM that has been built
        """

        pass

    @classmethod
    def before_vm_pack(cls, vms, manifest_path, cpio_dir):
        """ Hook called after all VMs have been built

        Args:
            vms (vm[]): array of VMs
            manifest_path (str): Path to manifest
            cpio_dir (str): Path to cpio dir
        """

        pass

    @classmethod
    def insert_additional_manifest_entries(cls, node):
        """ Hook to insert additional entries into the manifest

        Args:
            node (FdtNode): Node where content can be appended
        """
        pass

    ##### End of hooks

    @classmethod
    def init_config(cls, config_path):
        """Parse the platform configuration

        Args:
            config_path (str): Path to platform configuration file
        """

        # extract platform name
        platform_name = os.path.basename(os.path.dirname(config_path))

        # parse platform configuration file
        with open(config_path, "r") as f:
            cls.config = config_parser.PlatformConfig.from_json(f.read())
            if not cls.config:
                print("Could not parse platform configuration file, aborting.")
                sys.exit(1)

            cls.config.name = platform_name

    @classmethod
    def update_exports(cls):
        """ Update global dict with predefined keys & user options """

        cls.env_exports.update({
            "UUID": cls.config.uuid,
            "ROOT": cls.BUILD_ROOT,
            "OUT_PATH": cls.config.build_options["out_dir"],
            "PEREGRINE_DEBUG": "y" if cls.config.build_options["debug_hypervisor"] else "n",
            "PEREGRINE_LOG_LEVEL": cls.config.build_options["hypervisor_log_level"],
            "TFA_DEBUG": "y" if cls.config.build_options["debug_tfa"] else "n",
            "DEBUG_KERNEL": "y" if cls.config.build_options["debug_kernel"] else "n",
            "DOCKER_SUPPORT": "y" if cls.config.build_options["docker_support"] else "n",
            "UBOOT_DTS": cls.config.build_options["u_boot_device_tree_file"][:-4],
            "TARGET_DIR": cls.config.build_options["target_dir"],
            "MAX_CPUS": str(cls.config.max_cpus),
            "MAX_VMS": str(cls.config.max_vms),
            "MAX_AFF0": str(cls.config.max_affinity0), 
            "MAX_AFF1": str(cls.config.max_affinity1), 
            "MAX_AFF2": str(cls.config.max_affinity2),
            **cls.config.get_memory_layout_as_str()
        })
        print(cls.env_exports)

    @classmethod
    def make(cls, target, makefile=None):
        """ Invokes `make [-f FILE] <target>`.
        This function updates the environment of the `make` process see update_exports()

        Args:
            target (str): Makefile target to be invoked
            makefile (_type_, optional): Use specific makefile. Defaults to None.
        """

        dir = os.path.join(cls.BUILD_ROOT, "build")
        file_args = ["-f", makefile] if makefile else []

        print("Running:", ["make", *file_args, target],
            dict(cwd=dir, env={**cls.env_exports}, check=True))

        subprocess.run(["make", *file_args, target],
                    cwd=dir,
                    env={**os.environ, **cls.env_exports, **os.environ},
                    check=True)

    @classmethod
    def create_platform_fit_image(cls):
        """ Generates a Flattened uImage Tree """
        fit_target_file = os.path.join(
            cls.BUILD_ROOT, "u-boot/cot_peregrine/peregrine.fit")

        remaining_parameters = [fit_target_file]

        subprocess.run([os.path.join(cls.BUILD_ROOT, "u-boot/tools/mkimage"), "-f",
                        os.path.join(cls.BUILD_ROOT, "u-boot/cot_peregrine/peregrine.its"), *remaining_parameters], check=True)

    @classmethod
    def build_vm(cls, vm, force_rebuild=False):
        """ Regenerates VM manifest and potentially rebuilds VM.

        Args:
            vm (VM): The VM
            force_rebuild (bool, optional): Rebuilds the VM on true. Defaults to False.

        Returns:
            bool: True on success, else False
        """

        if vm.is_enabled:
            # if a build command is provided (can be script path, make cmdline, etc.)
            if vm.build_command and (force_rebuild or vm.always_rebuild):
                # create argv based on whether the build command is a cmdline or just the path to a script
                build_command = vm.build_command
                if os.path.exists(vm.build_command):
                    script_dir = os.path.dirname(vm.build_command)
                    build_command = [build_command]
                else:
                    build_command = shlex.split(build_command)
                    script_dir = os.path.join(cls.BUILD_ROOT, "build")
                custom_env = {**os.environ, **vm.build_env, **cls.env_exports}

                # execute build command in a subprocess
                subprocess.run([*build_command], cwd=script_dir, env=custom_env, check=True)
            if not vm.kernel_path:
                print(
                    f'No kernel image provided for VM with UUID "{vm.uuid}", aborting.\n')
                return False

            cpio_out_dir = os.path.join(cls.config.build_options["out_dir"], "cpio")
            kernel_filename = os.path.basename(vm.kernel_path)

            if os.path.exists(vm.kernel_path): # no kernel no party

                kernel_out_file = os.path.join(cpio_out_dir, f"{vm.vm_id}_{kernel_filename}")

                shutil.copy(vm.kernel_path, kernel_out_file)

                # if it exists, copy the VM's initrd image as well
                if vm.ramdisk_path:
                    ramdisk_filename = os.path.basename(vm.ramdisk_path)
                    ramdisk_out_file = os.path.join(cpio_out_dir, f"{vm.vm_id}_{ramdisk_filename}")
                    shutil.copyfile(vm.ramdisk_path, ramdisk_out_file)

                # if it exists, copy the Device Tree and make the needed alterations
                # depending on the format (DTS or DTB) compiling it may be required
                if vm.fdt_path:
                    # determine DT type by extension
                    if vm.fdt_path.endswith(".dtb"):
                        filetype = "dtb"
                    elif vm.fdt_path.endswith(".dts"):
                        filetype = "dts"
                    else:
                        print("Unable to infer DT type from file name: \"%s\"" \
                              % vm.fdt_path)
                        return False

                    # make a working copy of the DT
                    fdt_copy = os.path.join(cls.config.build_options["out_dir"],
                                            f"{vm.vm_id}_{os.path.basename(vm.fdt_path)}")
                    shutil.copyfile(vm.fdt_path, fdt_copy)

                    # determine path & name of modified DT
                    patched_fdt_name = os.path.basename(vm.fdt_path)
                    patched_fdt_name = f"{vm.vm_id}_{patched_fdt_name[:-1]}b"
                    outpath = os.path.join(cpio_out_dir, patched_fdt_name)

                    # patch ramdisk size in "/chosen" node (if ramdisk present)
                    if vm.ramdisk_path:
                        ramdisk_start = vm.ipa_memory_layout["ramdisk"]
                        ramdisk_end   = ramdisk_start + os.path.getsize(vm.ramdisk_path)

                        # DTS patch
                        if filetype == "dts":
                            with open(fdt_copy, "rt") as f_in:
                                fdt_content = f_in.read()

                            fdt_content = fdt_content.replace(
                                            "linux,initrd-start = <initrd-start>;",
                                            "linux,initrd-start = <%#x>;" % ramdisk_start)
                            fdt_content = fdt_content.replace(
                                            "linux,initrd-end = <initrd-end>;",
                                            "linux,initrd-end = <%#x>;" % ramdisk_end)

                            with open(fdt_copy, "wt") as f_out:
                                f_out.write(fdt_content)
                        # DTB patch
                        else:
                            fdt_data = fdt_patcher.parse_fdt(fdt_copy)
                            if fdt_data is None:
                                print("Unable to parse DTB file: \"%s\"" % fdt_copy)
                                return False

                            # this will reuse existing "bootargs" and
                            # "stdout-path" properties
                            fdt_patcher.set_chosen(fdt_data,
                                                   rd_start=ramdisk_start,
                                                   rd_end=ramdisk_end)

                            ans = fdt_patcher.store_fdt(fdt_copy, fdt_data)
                            if ans is False:
                                print("Unable to store chosen node changes: \"%s\""
                                      % fdt_copy)

                    # patch "/memory@..." node based on main components IPA layout
                    if vm.ipa_memory_layout and vm.memory_size:
                        fdt_data = fdt_patcher.parse_fdt(fdt_copy)

                        # prepare arguments for invocation
                        kernel_addr  = vm.ipa_memory_layout['kernel']
                        fdt_addr     = vm.ipa_memory_layout['fdt']      \
                                       if 'fdt' in vm.ipa_memory_layout \
                                       else 2**64 - 1
                        ramdisk_addr = vm.ipa_memory_layout['ramdisk']      \
                                       if 'ramdisk' in vm.ipa_memory_layout \
                                       else 2**64 - 1

                        # perform the patch
                        fdt_patcher.set_memory(fdt_data, vm.memory_size,
                                            kernel_addr, fdt_addr, ramdisk_addr)

                        ans = fdt_patcher.store_fdt(fdt_copy, fdt_data)
                        if ans is False:
                            print("Unable to store memory node changes: \"%s\""
                                  % fdt_copy)

                    # patch "/cpus" node based on VM's physical CPU assignation
                    if vm.cpus:
                        fdt_data = fdt_patcher.parse_fdt(fdt_copy)

                        # perform the patch
                        fdt_patcher.trim_excess_cpus(fdt_data, vm.vcpu_count)

                        ans = fdt_patcher.store_fdt(fdt_copy, fdt_data)
                        if ans is False:
                            print("Unable to store cpus node changes: \"%s\""
                                  % fdt_copy)
                    else:
                        print("No physical CPU assignation detected")
                        return False

                    # delete nodes based on whitelist (if specified by user)
                    if vm.device_whitelist:
                        fdt_data = fdt_patcher.parse_fdt(fdt_copy)
                        if fdt_data is None:
                            print("Unable to parse FDT file: \"%s\"" % fdt_copy)
                            return False

                        fdt_patcher.apply_whitelist(fdt_data, vm.device_whitelist)

                        ans = fdt_patcher.store_fdt(fdt_copy, fdt_data)
                        if ans is False:
                            print("Unable to store whitelist changes: \"%s\""
                                  % fdt_copy)

                    # compile if FDT is in DTS format
                    if vm.fdt_path.endswith(".dts"):
                        compile_dts(fdt_copy, outpath)
                    # or copy it as-is in case it's DTB
                    elif vm.fdt_path.endswith(".dtb"):
                        shutil.copyfile(fdt_copy, outpath)
                    else:
                        print("Unknown FDT format: \"%s\"" % fdt_copy)
                        return False

                cls.after_vm_built(vm)

        return True

    @classmethod
    def generate_vm_dt(cls, vm):
        """ Generates the device tree corresponding to the VM's manifest

        Args:
            vm (VM): The VM

        Returns:
            FDT: FDT contents
        """

        return vm.unroll_dt()

    @classmethod
    def create_merged_manifest(cls, manifest_path, VMs=[],):
        """ Generates a VM manifest in FTD format for the hypervisor

        Args:
            manifest_path (str): Output path of the manifest (search for "manifest.dtb")
            VMs (list, optional): List of VM objects to include in the manifest. Defaults to [].
        """

        hypervisor = fdt.Node("hypervisor")

        hypervisor.append(fdt.PropStrings("compatible", "peregrine,peregrine"))
        hypervisor.append(fdt.PropStrings("manifest_uuid", cls.config.uuid))
        hypervisor.append(fdt.PropWords("manifest_version", cls.config.version))

        cls.insert_additional_manifest_entries(hypervisor)

        found_primary = 0
        vms_available = 0

        # for each VM in the received list
        for vm in VMs:
            cpio_out_dir    = os.path.join(cls.config.build_options["out_dir"], "cpio")
            kernel_filename = os.path.basename(vm.kernel_path)

            # skip VM if not built
            if not os.path.exists(os.path.join(cpio_out_dir, f"{vm.vm_id}_{kernel_filename}")):
                continue

            # check if image can be dom0 and add add it to the device tree regardless
            found_primary += 1 if vm.is_primary else 0
            if found_primary > 1:
                print("ERROR: More than one primary VM specified (is_primary).")
                sys.exit(1)

            vm_node = cls.generate_vm_dt(vm)
            if vm_node:
                hypervisor.append(vm_node)

            vms_available += 1

        # check that there is exactly one primary VM in the list
        if vms_available > 0:
            if found_primary == 0:
                print("ERROR: No primary VM specified (is_primary).")
                sys.exit(1)
        else:
            print("Warning: Building without any VMs!\n")

        fdt_out = fdt.FDT()
        fdt_out.add_item(hypervisor)

        # generate .dts from the constructed FDT object
        dts_path = os.path.join(cls.BUILD_ROOT, "build", "platform_manifest.dts")
        with open(dts_path, "w+") as f:
            f.write(fdt_out.to_dts())

        # compile .dts into a .dtb
        compile_dts(dts_path, manifest_path)

    @classmethod
    def parse_vm_from_file(cls, file_obj):
        """ Prase VM configuration from file

        Args:
            file_obj (file obj): JSON file object to read from

        Returns:
            VM: VM
        """

        return config_parser.VM.from_json(file_obj.read())


    @classmethod
    def get_vms(cls, build=False, force_rebuild=False):
        """ Ggenerates a list of VM configuration objects from .json config files.

        NOTE: the src directory is hardcoded to ${ROOT}/build/VMs
        NOTE: VMs that are disabled from the config files are not added to the list

        Args:
            build (bool, optional): Of true, manifests will be updated, else just a list of VMs is retrieved. Defaults to False.
            force_rebuild (bool, optional): Force the rebuild process for existing images. Defaults to False.

        Returns:
            list(VM):  The list of VM objects
        """

        VMs = []
        vm_uuids = []
        vm_cpus = set()
        config_parser.vm_count = 0
        vm_dir = os.path.join(cls.config.build_options["target_dir"], "VMs")

        for vm_json in sorted(os.listdir(vm_dir)):
            with open(os.path.join(vm_dir, vm_json), "r") as f:
                # parse the config file
                new_vm = cls.parse_vm_from_file(f)

                if new_vm is not None and new_vm.is_enabled:
                    # check for UUID duplicates
                    if  new_vm.uuid in vm_uuids:
                        print("ERROR: UUID duplicate found.")
                        sys.exit(1)
                    else:
                        vm_uuids.append(new_vm.uuid)

                    # check for void CPU allocation set
                    if len(new_vm.cpus) == 0:
                        print("ERROR: no CPUs allocated to VM")
                        sys.exit(1)

                    # check for physical CPU assignation overlap
                    cpu_overlap = vm_cpus & set(new_vm.cpus)
                    if len(cpu_overlap) != 0:
                        print("ERROR: physical CPU assignation overlap: %s" % \
                              [ hex(it) for it in cpu_overlap ])
                        sys.exit(1)
                    else:
                        vm_cpus |= set(new_vm.cpus)

                    # ensure CPU0 is assigned to primary VM
                    if new_vm.is_primary and 0x0 not in new_vm.cpus:
                        print("ERROR: CPU0 was not assigned to primary VM")
                        sys.exit(1)

                    # build new vm
                    ans = cls.build_vm(new_vm, force_rebuild) if build else True
                    if not ans:
                        print("ERROR: Could not build VM.")
                        sys.exit(1)

                    if new_vm.vm_id == "vm1" and len(VMs):
                        VMs.insert(0, new_vm)
                    else:
                        VMs.append(new_vm)

        if len(vm_uuids) > cls.config.max_vms:
            print("Built more VMs than maximum VMs allowed for this target.")
            sys.exit(1)
        elif len(vm_uuids) == 0:
            print("No VMs are enabled. Please enable at least one VM.")
            sys.exit(1)

        return VMs

    @classmethod
    def create_json(cls):
        """ Creates a json file comprising the data of all enabled VMS in the management VM folder. """

        # fetch the virtual machines which are enabled
        vms = cls.get_vms()
        vm_strings = []
        # convert the virtual machines to json strings
        for vm in vms:
            vm_strings.append(jsonpickle.encode(vm))
        # generate the output data
        output_data = {"vms": [json.loads(vm_s) for vm_s in vm_strings]}
        # specify the target directory for the json file
        target_rel_path = "br-ext/ssp-fvp-overlay/root"
        target_directory = os.path.join(os.getcwd(), target_rel_path)
        if not os.path.exists(target_directory):
            os.makedirs(target_directory)
        # write the data into the json file
        with open(os.path.join(target_directory, "aggregated_data.json"), "w") as file:
            # convert the output data to a string with relative paths
            output_data_str = json.dumps(output_data, indent=4)
            output_data_str = output_data_str.replace(os.getcwd() + "/", "")
            # write the data into the json file
            file.write(output_data_str)

    @classmethod
    def pack_platform_image(cls, platform_image_file, cpio_dir):
        """ Ggenerates cpio archive.

        NOTE: this is basically
                   $ find ${cpio_dir} | cpio -o > ${platform_image_file}
        NOTE: the staging directory must contain a number of things:
                   - platform manifest & its signature
                   - VM images, device trees, rootfs archives

        Args:
            platform_image_file (str): Iutput archive name
            cpio_dir (str): Staging directory for the cpio archive
        """
        with open(platform_image_file, "wb") as f:
            ps = subprocess.Popen(["find", ".", "-type", "f", "-not", "-name", "manifest.dtb"], cwd=cpio_dir, stdout=subprocess.PIPE)

            files_read = b"./manifest.dtb\n" + ps.stdout.read()

            print(files_read.decode())

            cpio_proc = subprocess.Popen(["cpio", "--create"],
                            cwd=cpio_dir,
                            stdin=subprocess.PIPE,
                            stdout=f)

            cpio_proc_out = cpio_proc.communicate(input=files_read)[0]


    @classmethod
    def create_platform_fdt(cls, platform_image_file):
        """ Creates & compiles a device tree file based on a template.

        NOTE: currently, the fdts/ hardcoded path is for the Fixed Virtual Platform

        Args:
            platform_image_file (str): Platform initrd file
        """
        memory_layout = cls.config.get_memory_layout_as_str()
        dts_content = ""

        # calculate the end address of the full platform initrd image
        end_addr = "0x%0.2X" % (cls.config.memory_layout["VMS_START_ADDR"] + os.path.getsize(platform_image_file))

        # replace a specific line in the FVP device tree with build-specific info:
        # i.e.: boot arguments (empty), default stdout (serial0), initrd boundary addresses
        #
        # NOTE: this is done in-memory; the original template is not modified
        with open(cls.config.target_dts_file, "r") as f:
            dts_content = f.read().replace('chosen {};', "chosen {{\n\tbootargs = \"\";\n\tstdout-path = \"serial0:115200n8\";\n\tlinux,initrd-start = <{VMS_START_ADDR}>;\n\tlinux,initrd-end = <{VMS_END_ADDR}>;\n }};\n".format(
                VMS_START_ADDR=memory_layout["VMS_START_ADDR"], VMS_END_ADDR=end_addr))

        out_dts_file = os.path.join(cls.config.build_options["out_dir"], "platform_fdt.dts")

        with open(out_dts_file, "w+") as f:
            f.seek(0)
            f.write(dts_content)
            f.truncate()

        compile_dts(out_dts_file, os.path.join(
            cls.config.build_options["out_dir"], "peregrine_fdt.dtb"))


    @classmethod
    def prepare_cpio_dir(cls):
        """ Creates the `cpio/` dir and deletes any content inside

        Returns:
            str: path to the (newly created) staging directory
        """
        cpio_dir = os.path.join(cls.config.build_options["out_dir"], "cpio/")

        # create directory or empty its contents if already there
        if not os.path.exists(cpio_dir):
            os.makedirs(cpio_dir)
        else:
            for f in glob.glob(f"{cpio_dir}/*"):
                os.remove(f)

        return cpio_dir

    @classmethod
    def build_vms(cls, platform_image_file, cpio_dir, manifest_path, rebuild=False):
        """ Implementation of `make vms`

        Args:
            platform_image_file (str): Platform ramdisk image to be generated
            cpio_dir (str): Staging dir for cpio
            manifest_path (str): Path for merged VM manifest
            rebuild (bool, optional): Force VM rebuild. Defaults to False.

        Returns:
            _type_: _description_
        """

        # remove any previously existing platform image
        if os.path.exists(platform_image_file):
            os.remove(platform_image_file)

        vms = cls.get_vms(build=True, force_rebuild=rebuild)

        # generate VM manifest based on previously obtained VM list
        cls.create_merged_manifest(manifest_path, vms)

        return vms

    @classmethod
    def pack_vms(cls, platform_image_file, cpio_dir):
        """ Pack platform image containing VMs and hypervisor binary.

        Args:
            platform_image_file (str): Platform ramdisk image to be generated
            cpio_dir (str): Staging dir for cpio
        """

        # pack everything from the cpio staging area into an initrd image
        cls.pack_platform_image(platform_image_file, cpio_dir)

        # generate hardware (FVP) device tree from template
        cls.create_platform_fdt(platform_image_file)

    @classmethod
    def make_tfa(cls):
        """ Builds Arm Trusted-Firmware """
        cls.make("arm-tf")


    @classmethod
    def prepare_hypervisor_uboot_files(cls):
        build_configs_uboot_dir = os.path.join(
            cls.config.build_options["target_dir"], "uboot-configs"
        )

        uboot_cot_hypervisor_dir = os.path.join(
            cls.BUILD_ROOT, "u-boot/cot_peregrine/"
        )

        if not os.path.exists(uboot_cot_hypervisor_dir):
            os.makedirs(uboot_cot_hypervisor_dir)
        compile_dts(
            os.path.join(build_configs_uboot_dir, "image_keys.dts"),
            os.path.join(uboot_cot_hypervisor_dir, "image_keys.dtb"),
            "-p 0x1000"
        )


    @classmethod
    def create_platform_certs(cls):
        """ create_platform_certs - generate RSA private key & x509 certificate

            NOTE: both files are used by `create_platform_fit_image()` during the FIT
                image generation phase. u-boot's `mkimage` will use the .pem file
                to sign the image and the .crt file to verify the signature at at
                boot
        """

        home = str(Path.home())
        rnd_file = os.path.join(home, ".rnd")
        platform_key = os.path.join(
            cls.BUILD_ROOT, "u-boot/cot_peregrine/peregrine.key")

        with tempfile.NamedTemporaryFile() as tmp:
            # generate a 1KB file of random data
            subprocess.run(["openssl", "rand", "-out",
                        tmp.name, "-writerand", tmp.name], check=True)

        # generate a 2048b RSA private key
        try:
            subprocess.run(["openssl", "genpkey",
                            "-algorithm", "RSA",
                            "-out", platform_key,
                            "-pkeyopt", "rsa_keygen_bits:2048",
                            "-pkeyopt", "rsa_keygen_pubexp:65537"],
                        check=True)
        except subprocess.CalledProcessError as e:
            print(e.output)

        # generate a x509 certificate
        subprocess.run(["openssl", "req",
                        "-batch", "-new", "-x509",
                        "-key", platform_key,
                        "-out", os.path.join(cls.BUILD_ROOT,
                                            "u-boot/cot_peregrine/peregrine.crt")],
                    check=True)

    @classmethod
    def make_platform_tools(cls):
        """Builds tools needed for the specific in case they have not been built"""

        # test if FVP executable is present
        tools_path = os.path.join(cls.BUILD_ROOT, "toolchains")

        fvp_path = os.path.join(tools_path, "Base_RevC_AEMv8A_pkg")

        if not os.path.exists(fvp_path):
            # let's downlad and unpack the gzipped tarball
            cls.make("fvp-download")

    @classmethod
    def make_uboot_tools(cls):
        """Builds the u-boot tools in case they have not been built"""
        
        uboot_path = os.path.join(
            cls.BUILD_ROOT, "u-boot"
        )

        # Only do this once to prevent overwriting the config
        # The check is based on mkimage which is always built if the
        # tools are built

        if not os.path.exists(os.path.join(uboot_path, "tools/mkimage")):
            subprocess.run(["make", "-C",uboot_path, "tools-only_defconfig"],
                        cwd=uboot_path,
                        env=os.environ,
                        check=True)
            
            subprocess.run(["make", "-C",uboot_path, "tools-only"],
                        cwd=uboot_path,
                        env=os.environ,
                        check=True)
                    
    @classmethod
    def make_uboot(cls):
        """ Builds U-Boot """

        build_configs_uboot_dir = os.path.join(
            cls.config.build_options["target_dir"], "uboot-configs"
        )

        uboot_cot_hypervisor_dir = os.path.join(
            cls.BUILD_ROOT, "u-boot/cot_peregrine/"
        )

        memory_layout = cls.config.get_memory_layout_as_str()

        # replace device tree with the modified one (if any specified)
        if len(cls.config.build_options["u_boot_device_tree_file"]) != 0:
            shutil.copy(
                os.path.join(build_configs_uboot_dir, cls.config.build_options["u_boot_device_tree_file"]),
                os.path.join(cls.BUILD_ROOT, f"u-boot/arch/arm/dts/{cls.config.build_options['u_boot_device_tree_file']}")
            )

        # copy the prepared .config file
        uboot_config_file = os.path.join(cls.BUILD_ROOT, "u-boot/.config")
        shutil.copy(
            os.path.join(build_configs_uboot_dir, ".config"),
            uboot_config_file
        )

        # Set adddress of u-boot kernel in config file
        # NOTE: "CONFIG_SYS_TEXT_BASE" changed to "CONFIG_TEXT_BASE" in v2022.10
        #       keep both version for now
        replace_file_line(
            uboot_config_file,
            "CONFIG_SYS_TEXT_BASE=XXX\n",
            f"CONFIG_SYS_TEXT_BASE={memory_layout['UBOOT_KERNEL_START_ADDR']}\n"
        )

        replace_file_line(
            uboot_config_file,
            "CONFIG_TEXT_BASE=XXX\n",
            f"CONFIG_TEXT_BASE={memory_layout['UBOOT_KERNEL_START_ADDR']}\n"
        )

        # Set address of cmd script in config file
        replace_file_line(
            uboot_config_file,
            "CONFIG_BOOTCOMMAND=\"source XXX\"\n",
            f"CONFIG_BOOTCOMMAND=\"source {memory_layout['UBOOT_CMD_START_ADDR']}\"\n"
        )

        # Set addresses of hypervisor binary and FDT
        uboot_hypervisor_its_file = os.path.join(uboot_cot_hypervisor_dir, "peregrine.its")
        shutil.copy(
            os.path.join(build_configs_uboot_dir, "peregrine.its"),
            uboot_hypervisor_its_file
        )
        with open(uboot_hypervisor_its_file,"r") as f:
            data = f.read()
            data = data.replace("<peregrine>",f'<{memory_layout["PEREGRINE_KERNEL_START_ADDR"]}>')
            data = data.replace("<fdt>",f'<{memory_layout["PEREGRINE_FDT_START_ADDR"]}>')

        with open(uboot_hypervisor_its_file, "w") as f_new:
            f_new.write(data)

        cls.make("uboot")

    @classmethod
    def make_hypervisor(cls):
        """ Builds the hypervisor """

        cls.make("hypervisor")

    @classmethod
    def make_platform(cls):
        """ Builds the whole platform """

        cls.prepare_hypervisor_uboot_files()

        # create platform certificate
        cls.create_platform_certs()

        cls.make_hypervisor()
        cls.make_uboot()
        cls.make_tfa()

    @classmethod
    def build(cls):
        """ Script entry point """

        global config

        # define command line arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--rebuild', action='store_true',
                            help="Rebuild all VMs.")
        parser.add_argument('--hypervisor-only', action='store_true',
                            help="Only build the hypervisor.")
        parser.add_argument('--vms-only', action='store_true',
                            help="Only build VMs.")
        parser.add_argument('-wrap', action='store', type=str,
                            help='The makefile target.')
        parser.add_argument('-makefile', action='store', type=str,
                            help='The makefile.')

        # parse command line arguments
        parser.add_argument('-configfile', action='store', type=str, required=True,
                            help="Config File for the build process.")

        args = parser.parse_args()

        config_parser.set_root(cls.BUILD_ROOT)
        build_dir = os.path.join(cls.BUILD_ROOT, "build")

        cls.init_config(config_path=os.path.join(build_dir, args.configfile))

        # update global environment dict with specific paths
        platform_image_file = os.path.join(cls.config.build_options["out_dir"], "vms.img")
        platform_image_file_rel = os.path.relpath(platform_image_file, cls.BUILD_ROOT)
        boot_image_file = os.path.join(cls.config.build_options["out_dir"], "boot-fat.uefi.img")
        cls.env_exports.update({"BOOT_IMG": boot_image_file,
                            "BOOT_IMG_VM": platform_image_file,
                            "BOOT_IMG_VM_REL": platform_image_file_rel})

        # call setup hook
        cls.setup()

        # prepare staging area for the cpio archive
        cpio_dir = cls.prepare_cpio_dir()
        manifest_path = os.path.join(cpio_dir, "manifest.dtb")

        # continue updating the global environment dict with user's options
        cls.update_exports()
        cls.config.print()

        # (maybe) this script's invocation wrapped a one-shot `make <target>`
        if args.wrap:
            cls.make(target=args.wrap, makefile=args.makefile)
            return

        # (maybe) compile hypervisor in addition to VMs
        if not args.vms_only:
            # let's check if any of the VMs actually needs the TPM TA or others
            cls.get_vms()
            cls.make_platform()

        # generate VMs
        cls.create_json()
        rebuild = args.rebuild if not args.hypervisor_only else False


        vms = cls.build_vms(platform_image_file=platform_image_file,
                cpio_dir=cpio_dir,
                manifest_path=manifest_path,
                rebuild=rebuild)

        cls.before_vm_pack(vms, manifest_path, cpio_dir)

        cls.pack_vms(platform_image_file=platform_image_file, cpio_dir=cpio_dir)

        # integrate everything into a single FIT image
        cls.create_platform_fit_image()

        cls.make("target") # target specific make target


if __name__ == "__main__":
    Builder.build()
