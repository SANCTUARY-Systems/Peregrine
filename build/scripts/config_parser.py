#!/usr/bin/env python3
from typing import Dict, List
from dataclasses import dataclass, field
import json
import os
from distutils import util
import sys
import re
import fdt
from fdt_hotfix import FDT_HOTFIX

BUILD_ROOT = None
vm_count = 0
found_primary = False

regex_json_remove_comment = re.compile(r"#.*\n")

MANIFEST_SIG_ALGO_ID    = 0x70414930
MANIFEST_SIG_SIZE       = 0x100
MANIFEST_HASH_ALGO_ID   = 0x50000004
MANIFEST_HASH_SIZE      = 0x20

def parse_hex(value):
    """ Parse a hex value from a string

    Args:
        value (str): Input string

    Returns:
        any: int if input was as valid hex string, else str
    """
    if isinstance(value, str):
        if value.startswith("0x"):
            try:
                return int(value, 16)
            except:
                pass
    return value

def apply_values_from_json(target, source, keys=None):
    """ Copies key, value pairs from source to target (deep copy)

    Args:
        target (dict): Target dict
        source (dict): Source dict
        keys (list(str), optional): Keys to copy. Defaults to None.
    """

    if not keys:
        keys = source.keys()

    for key in keys:
        if key in source.keys():
            if isinstance(source[key], Dict):
                target[key] = dict()
                for subkey in source[key].keys():
                    target[key][subkey] = parse_hex(source[key][subkey])
            else:
                target[key] = parse_hex(source[key])


def set_root(root):
    """ Sets the root directory

    Args:
        root (str): Path of root directory
    """

    global BUILD_ROOT
    BUILD_ROOT = root

class Device:
    """ Represents a device in the manifest """

    def __init__(self, dev_id, base_addr, pages_count, attributes, interrupts=None, name=None):
        """ Initializer for Device

        Args:
            dev_id (_type_): Device ID
            base_addr (_type_): Base address of device
            pages_count (_type_): Number of pages belonging to the device
            attributes (_type_): Attributes
            interrupts (_type_, optional): List of interrupts. Defaults to None.
            name (_type_, optional): Human-readable name of the device. Defaults to None.
        """

        self.id = dev_id
        self.description = name if name is not None else dev_id
        self.base_addr = base_addr
        self.pages_count = pages_count
        self.attributes = attributes
        self.interrupts = interrupts

    def to_fdt_node(self):
        """ Generate FDT node from Device

        Returns:
            FdtNode: FdtNode
        """

        dev_node = fdt.Node(self.id)
        dev_node.append(fdt.PropStrings("description", self.description))
        dev_node.append(fdt.PropWords("base-address", *self.base_addr))
        dev_node.append(fdt.PropWords("pages-count", self.pages_count))
        dev_node.append(fdt.PropWords("attributes", self.attributes))
        if self.interrupts is not None:
            dev_node.append(fdt.PropWords("interrupts", *self.interrupts))
        return dev_node

    def from_dict(dev_id, dev_dict):
        """ Create new Device from dict

        Args:
            dev_id (str): Device ID
            dev_dict (dict): Dict to create Device from

        Returns:
            Device: Device object
        """

        base_addr = dev_dict.get('base-address')
        if base_addr is not None:
            base_addr = base_addr.split(' ')
            base_addr = list(map(lambda x: int(parse_hex(x)), base_addr))
        pages_count = dev_dict.get('pages-count', 1)
        attributes = int(parse_hex((dev_dict.get('attributes', 3)))) # fallback is read-write
        interrupts = dev_dict.get('interrupts')
        if interrupts is not None:
            interrupts = interrupts.split(' ')
            interrupts = list(map(lambda x: int(parse_hex(x)), interrupts))
        name = dev_dict.get('description')
        return Device(dev_id=dev_id, base_addr=base_addr, pages_count=pages_count, attributes=attributes, interrupts=interrupts, name=name)

@dataclass
class VM:
    """ VM class to represent a single virtual machine """

    class DeviceRegions:
        """ Device regions holding all devices """

        def __init__(self, regions):
            """ Initializer for DeviceRegions

            Args:
                regions (list(Device)): List of devices
            """

            self.regions = regions

        def to_fdt_node(self):
            """ Generate FdtNode containing all devices

            Returns:
                FdtNode: FdtNode
            """

            dev_reg = fdt.Node('device-regions')
            dev_reg.append(fdt.PropStrings("compatible", "arm,ffa-manifest-device-regions"))
            for dev in self.regions:
                if isinstance(dev, Device):
                    dev_reg.append(dev.to_fdt_node())
            return dev_reg

        def from_dict(devices_dict):
            """ Generate DeviceRegions from dictionary

            Args:
                devices_dict (dict): Input dict

            Returns:
                DeviceRegions: DeviceRegions
            """

            regions = []
            for dev_id, dev_dict in devices_dict.items():
                regions.append(Device.from_dict(dev_id=dev_id, dev_dict=dev_dict))
            return VM.DeviceRegions(regions)

    vm_id: int = None
    uuid: str = None
    name: str = None
    build_command: str = ""
    build_env: Dict[str, str] = field(default=None)
    always_rebuild: bool = False
    kernel_path: str = None
    kernel_version: int = 1
    kernel_boot_params: str = ""
    ramdisk_path: str = None
    ramdisk_version: int = 1
    fdt_path: str = None
    fdt_version: int = 1
    is_enabled: bool = True
    is_primary: bool = False
    vcpu_count: int = 1
    cpus: List[str] = field(default=None)
    memory_size: int = None
    boot_address: int = None
    smc_whitelist: List[str] = field(default=None)
    smc_whitelist_permissive: bool = False
    requires_identity_mapping: bool = False
    ipa_memory_layout: Dict[str, int] = field(default=None)
    device_whitelist: List[str] = field(default=None)
    device_regions: List[DeviceRegions] =  field(default=None)

    hash_algo_id: int = MANIFEST_HASH_ALGO_ID
    hash_size: int = MANIFEST_HASH_SIZE

    def populate_fields(self):
        """ Populate additional fields of the VM object """
        self.device_regions = VM.DeviceRegions.from_dict(self.device_regions) if self.device_regions else None

        # due to JSON limitations, hex numbers must be expressed
        # as strings; convert the "cpus" list members to integers
        #
        # TODO: consider looking into JSON5 parsers in the future
        #       should have support for hex numbers
        if self.cpus:
            self.cpus = [ int(it, 0) for it in self.cpus ]

    @classmethod
    def from_json(cls, json_string):
        """ Create a new VM object based on a JSON file

        Args:
            json_string (str): Path to JSON file

        Returns:
            VM: VM
        """

        global vm_count
        global found_primary

        vm = cls()

        json_parsed = json.loads(json_string.replace("$(ROOT)", BUILD_ROOT))
        vm_id =  list(json_parsed.keys())[0]
        vm_dict = json_parsed[vm_id]

        vm_dict["vm_id"] = -1

        if "build_env" in vm_dict.keys() and len(vm_dict["build_env"]) > 0:
            parameter_list = vm_dict["build_env"].split(" ")
            vm_dict["build_env"] = {}
            for env_elem in parameter_list:
                vm_dict["build_env"].update(dict([env_elem.split("=")]))
        else:
            vm_dict["build_env"] = dict()

        apply_values_from_json(vm.__dict__, vm_dict, vm.__dataclass_fields__.keys())

        if vm.is_enabled:
            if vm.is_primary:
                vm.vm_id = "vm1"
                vm_count += 1
                found_primary = True
            else:
                if vm.requires_identity_mapping:
                    print("ERROR: Only the primary VM can have identity mapping.")
                    sys.exit(1)
                vm_count += 1
                vm.vm_id = "vm" + str(vm_count if found_primary else vm_count + 1)

            vm.populate_fields()

            return vm
        else:
            return None

    def unroll_dt(self):
        """ Generate an FdTNode based on the VM.
        Disabled VMs will not be included.

        Returns:
            FdtNode: FdtNode
        """

        if not self.is_enabled:
            return None

        vm_node = fdt.Node(self.vm_id)
        vm_node.append(fdt.PropStrings("uuid", self.uuid))
        vm_node.append(fdt.PropStrings("debug_name", self.name))
        vm_node.append(fdt.PropStrings("kernel_filename", f"{self.vm_id}_{os.path.basename(self.kernel_path)}"))
        vm_node.append(fdt.PropWords("kernel_version", self.kernel_version))

        if self.kernel_boot_params:
            vm_node.append(fdt.PropStrings("kernel_boot_params", self.kernel_boot_params))

        if self.fdt_path:
            patched_fdt_name = os.path.basename(self.fdt_path)
            patched_fdt_name = f"{self.vm_id}_{patched_fdt_name[:-1]}b"
            vm_node.append(fdt.PropStrings("fdt_filename", patched_fdt_name))
            vm_node.append(fdt.PropWords("fdt_version", self.fdt_version))

        if self.ramdisk_path:
            vm_node.append(fdt.PropStrings("ramdisk_filename", f"{self.vm_id}_{os.path.basename(self.ramdisk_path)}"))
            vm_node.append(fdt.PropWords("ramdisk_version", self.ramdisk_version))

        if self.is_primary:
            vm_node.append(fdt.Property("is_primary"))

        vm_node.append(fdt.PropWords("vcpu_count", self.vcpu_count))
        vm_node.append(fdt.PropWords("cpus", *self.cpus))

        if self.memory_size:
            vm_node.append(fdt.PropWords("memory_size", self.memory_size))

        if self.boot_address:
            vm_node.append(fdt.PropWords("boot_address", self.boot_address))

        if self.smc_whitelist_permissive:
            vm_node.append(fdt.Property("smc_whitelist_permissive"))

        if self.requires_identity_mapping:
            vm_node.append(fdt.Property("requires_identity_mapping"))

        if self.ipa_memory_layout is not None:
            mem_node = fdt.Node('ipa-memory-layout')
            for key in self.ipa_memory_layout:
                mem_node.append(fdt.PropWords(key, self.ipa_memory_layout[key]))
            vm_node.append(mem_node)

        if self.device_regions:
            vm_node.append(self.device_regions.to_fdt_node())

        return vm_node

@dataclass
class PlatformConfig:
    """ Platform configuration """
    name: str = None
    uuid: str = None
    version: int = 1
    crypto: Dict[str, int] = field(default_factory=lambda: {"sig_algo_id": MANIFEST_SIG_ALGO_ID, "sig_size": MANIFEST_SIG_SIZE, "hash_algo_id": MANIFEST_HASH_ALGO_ID, "hash_size": MANIFEST_HASH_SIZE, "manifest_sign_key": None})
    build_options: Dict[str, any] = field(default_factory=lambda: {"debug_hypervisor": False, "hypervisor_log_level": "LOG_LEVEL_INFO", "debug_tfa": False, "debug_kernel": False, "docker_support": False, "out_dir": None, "target_dir": None, "u_boot_device_tree_file": None, "use_optee_mediator": False})
    memory_layout: Dict[str,str] = None
    max_cpus: int = 1
    max_vms: int = None

    max_affinity0: int = 0
    max_affinity1: int = 0
    max_affinity2: int = 0
    

    def get_platform_config():
        return PlatformConfig.config

    def print(self):
        """ Print the Platform Configuration """

        for key,val in self.__dict__.items():
            print(f"{key}: {val}")

    def get_memory_layout_as_str(self):
        """ Return the hex-string-formatted memory layout

        Returns:
            dict: memory layout in hex strings
        """
        return {k: hex(v) for k, v in self.memory_layout.items()}
    
    def extract_platform_details(self):
        """ Derive additional platform details from flattened device tree """

        if (self.target_dts_file) and os.path.exists(self.target_dts_file):
            with open(self.target_dts_file, "r") as f:
                dts_text = f.read()

            if dts_text:
                dts_parsed = FDT_HOTFIX.parse_dts(dts_text)
                
                cpu_list = list(filter(lambda x: x.name.startswith("cpu@"), dts_parsed.get_node("cpus").nodes))
                for core in cpu_list:
                    affinity =  core.get_property("reg")[-1]

                    affinity0 = affinity % 256 #calculate affinity level 0
                    affinity1 = (affinity//256) % 256 #calculate affinity level 1
                    affinity2 = (affinity//(256*256)) % 256 #calculate affinity level 2

                    if affinity0 > self.max_affinity0: self.max_affinity0 = affinity0
                    if affinity1 > self.max_affinity1: self.max_affinity1 = affinity1
                    if affinity2 > self.max_affinity2: self.max_affinity2 = affinity2

                # Offset all affinity levels by one as expected by the hypervisor
                self.max_affinity0 += 1
                self.max_affinity1 += 1
                self.max_affinity2 += 1

                max_cpus = len(cpu_list)

                if max_cpus > 0:
                    self.max_cpus = max_cpus

                if not self.max_vms or self.max_cpus < self.max_vms:
                    self.max_vms = self.max_cpus

    @classmethod
    def from_json(cls, json_string):
        """ Derive new PlatformConfig from JSON

        Args:
            json_string (str): JSON string

        Returns:
            PlatformConfiguration: PlatformConfiguration
        """

        PlatformConfig.config = cls()

        json_string = regex_json_remove_comment.sub("\n", json_string) # Remove single-line commments
        json_string = json_string.replace("$(ROOT)", BUILD_ROOT)   # Replace $(ROOT) with concrete root
        json_parsed = json.loads(json_string)
        main_id = list(json_parsed.keys())[0]


        if main_id != "platform":
            print("ERROR WRONG MAIN ID.\n")
            return

        main_node_json = json_parsed["platform"]

        key_diff = set(main_node_json.keys()) - set(cls.__dataclass_fields__.keys())

        if len(key_diff) > 0:
           print(f"WARNING: Unknown entries in manifest: {list(key_diff)}")

        apply_values_from_json(PlatformConfig.config.__dict__, main_node_json,  PlatformConfig.config.__dataclass_fields__.keys())

        # set target dts file
        PlatformConfig.config.target_dts_file = os.path.join(PlatformConfig.config.build_options["target_dir"], "platform_fdt.dts")

        PlatformConfig.config.extract_platform_details()

        return PlatformConfig.config
