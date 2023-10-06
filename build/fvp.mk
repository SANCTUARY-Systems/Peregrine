ROOT ?= $(shell pwd)/..

MAKEFLAGS 				+= -j12
BUILD_SCRIPTS 			?= $(ROOT)/build/scripts
TF_A_PATH				?= $(ROOT)/trusted-firmware-a
TOOLCHAIN_PATH  		?= $(ROOT)/toolchains
CLANG_PATH				?= $(ROOT)/peregrine/prebuilts/linux-x64/clang/bin/clang

AARCH64_CROSS_COMPILE	?= aarch64-linux-gnu-

################################################################################
# Compile Flags
################################################################################

MEM_LAYOUT_PRINT		?= n
PEREGRINE_PROJECT 		= fvp

### FVP flags to speed up simulation
FVP_FAST_NO_CACHE_MODELLING	?=y
FVP_FAST_NO_RATE_LIMIT	?=y

### Feature flags
USE_BOOTLOADER_AS_BL33 	?= y
USE_UBOOT_AS_BL33 		?= y

ifeq ($(TFA_DEBUG),y)
	TF_A_DBG_SYMBOLS 	?= 1
	TF_A_BUILD 			?= debug
else
	TF_A_DBG_SYMBOLS 	?= 0
	TF_A_BUILD 			?= release
endif

CCACHE ?= $(shell which ccache) # Don't remove this comment (space is needed)

################################################################################
# Paths to Folders and Binaries
################################################################################

### Folders
TARGET_DIR		= $(ROOT)/build/targets/fvp

### Binaries
PEREGRINE_BIN     ?= $(ROOT)/peregrine/out/$(PEREGRINE_PROJECT)/aem_v8a_fvp_clang/peregrine.bin
UBOOT_BIN       ?= $(ROOT)/u-boot/u-boot.bin
UBOOT_CMD		?= $(TARGET_DIR)/uboot-configs/boot_cmds.img
PLATFORM_CONFIG_FILE = $(TARGET_DIR)/fvp.json

### Misc
PLATFORM_SUB_FLAVOR = v8a

ifeq ($(PLATFORM_SUB_FLAVOR),v8a)
	FVP_PATH	?= $(TOOLCHAIN_PATH)/Base_RevC_AEMv8A_pkg
	FVP_NAME    ?= FVP_Base_RevC-2xAEMv8A
else
	FVP_NAME    ?= FVP_Base_RevC-2xAEMvA
	FVP_PATH	?= $(TOOLCHAIN_PATH)/Base_RevC_AEMvA_pkg
endif

ifeq ($(PLATFORM_SUB_FLAVOR),fvp)
	FVP_FLAGS 	+= --block-device=$(BOOT_IMG)
else
ifeq ($(USE_BOOTLOADER_AS_BL33),y)
	BL33_IMAGE			?= $(UBOOT_BIN)
	BL33_EXTRA1_IMAGE 	?= $(UBOOT_CMD)
endif
endif
ifeq ($(FVP_FAST_NO_CACHE_MODELLING),y)
	FVP_FLAGS 	+= -C cache_state_modelled=0
endif
ifeq ($(FVP_FAST_NO_RATE_LIMIT),y)
	FVP_FLAGS 	+= -C bp.vis.rate_limit-enable=0
endif

################################################################################
# Build & Clean Targets
################################################################################

vms:
	$(MAKE) -f vm_wo_optee.mk vms BUILD_SCRIPTS=$(BUILD_SCRIPTS) PLATFORM_CONFIG_FILE=$(PLATFORM_CONFIG_FILE)

vms-rebuild:
	$(MAKE) -f vm_wo_optee.mk vms-rebuild BUILD_SCRIPTS=$(BUILD_SCRIPTS) PLATFORM_CONFIG_FILE=$(PLATFORM_CONFIG_FILE)

peregrine:
	$(BUILD_SCRIPTS)/build_peregrine.py --hypervisor-only -configfile $(PLATFORM_CONFIG_FILE)

	
linux-clean:
	$(MAKE) -f vm_wo_optee.mk linux-clean

clean: 
	$(BUILD_SCRIPTS)/build_peregrine.py -wrap clean-internal -configfile $(PLATFORM_CONFIG_FILE)

clean-internal: arm-tf-clean buildroot-clean \
	hypervisor-clean uboot-clean ftpm-clean linux-clean out-clean

clean-partial: 
	$(BUILD_SCRIPTS)/build_peregrine.py -wrap clean-partial-internal -configfile $(PLATFORM_CONFIG_FILE)

clean-partial-internal: arm-tf-clean boot-img-clean  \
	hypervisor-clean uboot-clean out-clean

include toolchain.mk


################################################################################
# ARM Trusted Firmware
################################################################################

TF_A_FLAGS_ADD += BL33_START_ADDR=$(UBOOT_KERNEL_START_ADDR) BL33_EXTRA1_START_ADDR=$(UBOOT_CMD_START_ADDR)

ifeq ($(USE_BOOTLOADER_AS_BL33),y)
TF_A_FLAGS_VM ?= \
	BL33=$(BL33_IMAGE) \
	BL33_EXTRA1=$(BL33_EXTRA1_IMAGE) \
	FVP_HW_CONFIG_DTS=fdts/fvp-base-gicv3-psci-1t.dts \
	ARM_PRELOADED_DTB_BASE=$(PEREGRINE_FDT_START_ADDR) \
	ARM_TSP_RAM_LOCATION=tdram \
	FVP_USE_GIC_DRIVER=FVP_GICV3 \
	PLAT=fvp
endif

TF_A_FLAGS_ADD += DEBUG=$(TF_A_DBG_SYMBOLS) \
			MBEDTLS_DIR=$(ROOT)/mbedtls  \
			ARM_ROTPK_LOCATION=devel_rsa \
			ROT_KEY=plat/arm/board/common/rotpk/arm_rotprivk_rsa.pem \
			GENERATE_COT=1 \
			MEASURED_BOOT=1 \
			TRUSTED_BOARD_BOOT=1 \
			EVENT_LOG_LEVEL=40

ifeq ($(MEM_LAYOUT_PRINT),y)
	TF_A_FLAGS_ADD += MEM_LAYOUT_PRINT=1
else
	TF_A_FLAGS_ADD += MEM_LAYOUT_PRINT=0	
endif

arm-tf: arm-tf-clean
	$(TF_A_EXPORTS) $(MAKE) -C $(TF_A_PATH) CC=$(CLANG_PATH) CFLAGS="-Wno-gnu-variable-sized-type-not-at-end" $(TF_A_FLAGS_VM) $(TF_A_FLAGS_ADD) DBG_SYMBOLS=$(TF_A_DBG_SYMBOLS) all fip

arm-tf-clean:
	$(TF_A_EXPORTS) $(MAKE) -C $(TF_A_PATH) clean

################################################################################
# Peregrine
################################################################################

hypervisor:
ifeq ($(),y)
	$(info ### Peregrine DEBUG BUILD ###)
	cd $(ROOT)/peregrine && TARGET_CONFIG=DEBUG $(MAKE) LOG_LEVEL=$(PEREGRINE_LOG_LEVEL) PROJECT=$(PEREGRINE_PROJECT) MEASURED_BOOT=$(MEASURED_BOOT)
else
	$(info ### Peregrine RELEASE BUILD ###)
	cd $(ROOT)/peregrine && TARGET_CONFIG=RELEASE $(MAKE) LOG_LEVEL=$(PEREGRINE_LOG_LEVEL) PROJECT=$(PEREGRINE_PROJECT) MEASURED_BOOT=$(MEASURED_BOOT)
endif
	if [ ! -d "$(OUT_PATH)" ]; then \
		mkdir -p "$(OUT_PATH)"; \
    fi
	cp $(PEREGRINE_BIN) "$(OUT_PATH)"/

hypervisor-clean:
	cd $(ROOT)/peregrine && $(MAKE) clean  PROJECT=$(PEREGRINE_PROJECT)

hypervisor-clobber:
	cd $(ROOT)/peregrine && $(MAKE) clobber

################################################################################
# U-Boot
################################################################################

uboot:
	ARCH=arm64 CROSS_COMPILE="$(CCACHE)$(AARCH64_CROSS_COMPILE)" $(MAKE) -C $(ROOT)/u-boot DEVICE_TREE=$(UBOOT_DTS)

	# Create cmds to boot Peregrine from u-boot
	# echo -e 'smhload ../../u-boot/cot_peregrine/peregrine.fit $(UBOOT_FIT_START_ADDR)\nsmhload ../../$(BOOT_IMG_VM_REL) $(VMS_START_ADDR)\nbootm $(UBOOT_FIT_START_ADDR)' > $(TARGET_DIR)/uboot-configs/boot_cmds
	echo -e 'load hostfs - $(UBOOT_FIT_START_ADDR) ../../u-boot/cot_peregrine/peregrine.fit\nload hostfs - $(VMS_START_ADDR) ../../$(BOOT_IMG_VM_REL)\nbootm $(UBOOT_FIT_START_ADDR)' > $(TARGET_DIR)/uboot-configs/boot_cmds
	$(ROOT)/u-boot/tools/mkimage -T script -C none -n 'Boot Commands' -d $(TARGET_DIR)/uboot-configs/boot_cmds $(TARGET_DIR)/uboot-configs/boot_cmds.img
	
uboot-clean:
	rm -f $(TARGET_DIR)/uboot-configs/boot_cmds
	rm -f $(TARGET_DIR)/uboot-configs/boot_cmds.img
	$(MAKE) -C $(ROOT)/u-boot clean
	rm -rf $(ROOT)/u-boot/cot_peregrine

################################################################################
# Target Specific targets
################################################################################

fvp-download:
	@echo 'INFO: Downloading FVP.'
	wget -O $(TOOLCHAIN_PATH)/fvp.tgz https://developer.arm.com/-/media/Files/downloads/ecosystem-models/FVP_Base_RevC-2xAEMvA_11.23_9_Linux64.tgz?rev=9de951d16ad74096ad78e4be80df5114&hash=93BEA9D29D5360330D13FFF574CD6804
	@cd $(TOOLCHAIN_PATH); \
	tar -xf fvp.tgz Base_RevC_AEMvA_pkg
	rm $(TOOLCHAIN_PATH)/fvp.tgz

target:
	@echo 'INFO: target specific make target not used.'

################################################################################
# Run Targets
################################################################################

FVP_TERMINAL_COMMAND := /usr/bin/lxterminal -t "%title" -e telnet localhost %port
FVP_TERMINAL_COMMAND_0 := /usr/bin/lxterminal -t "%title (Hypervisor)" -e telnet localhost %port
FVP_TERMINAL_COMMAND_1 := /usr/bin/lxterminal -t "%title (Secure World)" -e telnet localhost %port
FVP_TERMINAL_COMMAND_2 := /usr/bin/lxterminal -t "%title (VM 1)" -e telnet localhost %port
FVP_TERMINAL_COMMAND_3 := /usr/bin/lxterminal -t "%title (VM 2)" -e telnet localhost %port

run-only:			
	$(info ************  $(PLATFORM_SUB_FLAVOR) with Hypervisor  ************)
	@cd $(FVP_PATH); \
	$(FVP_PATH)/models/Linux64_GCC-6.4/$(FVP_NAME) \
	--log "$(ROOT)/build/fvp.log" \
	--disable-analytics \
	$(FVP_FLAGS) \
	-C bp.terminal_0.terminal_command='$(FVP_TERMINAL_COMMAND_0)' \
	-C bp.terminal_1.terminal_command='$(FVP_TERMINAL_COMMAND_1)' \
	-C bp.terminal_2.terminal_command='$(FVP_TERMINAL_COMMAND_2)' \
	-C bp.terminal_3.terminal_command='$(FVP_TERMINAL_COMMAND_3)' \
	-C bp.pl011_uart0.unbuffered_output=1 \
    -C bp.pl011_uart0.out_file="$(ROOT)/build/uart0.log" \
    -C bp.pl011_uart1.out_file="$(ROOT)/build/uart1.log" \
    -C bp.pl011_uart2.out_file="$(ROOT)/build/uart2.log" \
    -C bp.pl011_uart3.out_file="$(ROOT)/build/uart3.log" \
	-C pctl.startup=0.0.0.0			\
	-C bp.secure_memory=1			\
	-C bp.secureflashloader.fname="$(TF_A_PATH)/build/fvp/$(TF_A_BUILD)/bl1.bin"  \
	-C bp.flashloader0.fname="$(TF_A_PATH)/build/fvp/$(TF_A_BUILD)/fip.bin" \
	-C bp.smsc_91c111.enabled=1 \
	-C bp.hostbridge.interfaceName="tap0" \
	-C cluster0.NUM_CORES=4 				\
	-C cluster0.cpu0.clock_multiplier=20 \
	-C cluster0.cpu0.enable_crc32=1 		\
	-C cluster0.cpu1.clock_multiplier=20 \
	-C cluster0.cpu1.enable_crc32=1 		\
	-C cluster0.cpu2.clock_multiplier=20 \
	-C cluster0.cpu2.enable_crc32=1 		\
	-C cluster0.cpu3.clock_multiplier=20 \
	-C cluster0.cpu3.enable_crc32=1 		\
	-C cluster1.NUM_CORES=4 				\
	-C cluster1.cpu0.clock_multiplier=20 \
	-C cluster1.cpu0.enable_crc32=1 		\
	-C bp.vis.rate_limit-enable=0 \
	-C cache_state_modelled=0 \
	-C cluster1.cpu1.clock_multiplier=20 \
	-C cluster1.cpu1.enable_crc32=1 		\
	-C cluster1.cpu2.clock_multiplier=20 \
	-C cluster1.cpu2.enable_crc32=1 		\
	-C cluster1.cpu3.clock_multiplier=20 \
	-C cluster1.cpu3.enable_crc32=1 		\
	-C pci.pci_smmuv3.mmu.SMMU_AIDR=2 \
	-C pci.pci_smmuv3.mmu.SMMU_IDR0=0x0046123B \
	-C pci.pci_smmuv3.mmu.SMMU_IDR1=0x00600002 \
	-C pci.pci_smmuv3.mmu.SMMU_IDR3=0x1714 \
	-C pci.pci_smmuv3.mmu.SMMU_IDR5=0xFFFF0472 \
	-C pci.pci_smmuv3.mmu.SMMU_S_IDR1=0xA0000002 \
	-C pci.pci_smmuv3.mmu.SMMU_S_IDR2=0 \
	-C pci.pci_smmuv3.mmu.SMMU_S_IDR3=0	\
	-C bp.virtio_net.hostbridge.userNetworking=1 \
	-C bp.virtio_net.hostbridge.userNetPorts=5555=5555 \
	-C bp.virtio_net.enabled=1 \
	-C bp.ve_sysregs.mmbSiteDefault=0 \
	-C bp.ve_sysregs.exit_on_shutdown=1	\
