$(OUT_PATH):
	mkdir -p $@

BR2_PACKAGE_DTC 			?= y
BR2_PACKAGE_DTC_PROGRAMS	?= y

PYTHON3 := python3

LINUX_PATH                  ?= $(ROOT)/linux
AARCH64_CROSS_COMPILE	?= aarch64-linux-gnu-

################################################################################
# Buildroot
################################################################################

buildroot-sub:
	@mkdir -p ../out-br
	(cd .. && $(PYTHON3) build/br-ext/scripts/make_def_config.py \
		--br buildroot --out out-br \
		--top-dir "$(ROOT)" \
		--br-defconfig build/br-ext/configs/generic \
		$(DEFCONFIG_GDBSERVER) \
		$(DEFCONFIG_DOCKER) \
		--make-cmd $(MAKE))

	$(MAKE) $(br-make-flags) -C ../out-br all

.PHONY: buildroot-clean
buildroot-clean:
	@test ! -d $(ROOT)/out-br || $(MAKE) -C $(ROOT)/out-br clean

.PHONY: buildroot-cleaner
buildroot-cleaner:
	@rm -rf $(ROOT)/out-br

################################################################################
# Linux Kernel
################################################################################

LINUX_DEFCONFIG_COMMON_ARCH := arm64

# a config patch that disables a lot more than `fastlinux.conf`
# 
# there may still be options that could be disabled (e.g.: printk system for a
# ~0.5MB reduction in the kernel image). imx8m-related stuff were left in for
# now (still needs proper testing on PHYTEC Polis).
#
# NOTE: using CONFIG_CC_OPTIMIZE_FOR_SIZE is a _bad_ idea. yes, the resulting
#       kernel image will be loaded & verified faster, but the performance
#       downgrade from not using -O2 will cause the overall boot process to
#       end up being even slower.
ifeq ($(FASTER_BOOT), 1)
KCONF_FASTPATCH = $(CURDIR)/kconfigs/fastpatch.conf
endif

LINUX_COMMON_FLAGS ?= LOCALVERSION= CROSS_COMPILE=$(AARCH64_CROSS_COMPILE)

.PHONY: linux-common
linux-common: linux-defconfig
	echo '-ssp' > $(LINUX_PATH)/.scmversion
	$(MAKE) -C $(LINUX_PATH) $(LINUX_COMMON_FLAGS)

$(LINUX_PATH)/.config: $(LINUX_DEFCONFIG_COMMON_FILES)
	cd $(LINUX_PATH) && \
		ARCH=$(LINUX_DEFCONFIG_COMMON_ARCH) \
		scripts/kconfig/merge_config.sh $(LINUX_DEFCONFIG_COMMON_FILES) \
			$(LINUX_DEFCONFIG_BENCH)

.PHONY: linux-defconfig-clean-common
linux-defconfig-clean-common:
	rm -f $(LINUX_PATH)/.config

# LINUX_CLEAN_COMMON_FLAGS should be defined in specific makefiles
.PHONY: linux-clean-common
linux-clean-common: linux-defconfig-clean
	$(MAKE) -C $(LINUX_PATH) $(LINUX_CLEAN_COMMON_FLAGS) clean

# LINUX_CLEANER_COMMON_FLAGS should be defined in specific makefiles
.PHONY: linux-cleaner-common
linux-cleaner-common: linux-defconfig-clean
	$(MAKE) -C $(LINUX_PATH) $(LINUX_CLEANER_COMMON_FLAGS) distclean

LINUX_DEFCONFIG_COMMON_FILES := \
		$(LINUX_PATH)/arch/arm64/configs/defconfig \
		$(KCONF_FASTPATCH) \
		$(CURDIR)/kconfigs/fastlinux.conf \
		$(CURDIR)/kconfigs/devicemapper.conf \
		$(CURDIR)/kconfigs/fvp.conf

ifeq ($(DEBUG_KERNEL),y)
	LINUX_DEFCONFIG_COMMON_FILES := \
		$(LINUX_DEFCONFIG_COMMON_FILES) \
		$(CURDIR)/kconfigs/debug.conf
endif

ifeq ($(DOCKER_SUPPORT),y)
	LINUX_DEFCONFIG_COMMON_FILES := \
		$(LINUX_DEFCONFIG_COMMON_FILES) \
		$(CURDIR)/kconfigs/docker.conf
endif

linux-defconfig: $(LINUX_PATH)/.config

LINUX_COMMON_FLAGS += ARCH=arm64

linux: linux_pre linux-common 

linux_pre: 
	cp $(TARGET_DIR)/vm-dts/fvp-base-revc.dts $(LINUX_PATH)/arch/arm64/boot/dts/arm/fvp-base-revc.dts

linux-defconfig-clean: linux-defconfig-clean-common

LINUX_CLEAN_COMMON_FLAGS += ARCH=arm64

linux-clean: linux-clean-common

LINUX_CLEANER_COMMON_FLAGS += ARCH=arm64

linux-cleaner: linux-cleaner-common

linux-vm: linux buildroot-sub

vms-rebuild: 
	$(BUILD_SCRIPTS)/build_peregrine.py --rebuild --vms-only -configfile $(PLATFORM_CONFIG_FILE)
	$(BUILD_SCRIPTS)/build_peregrine.py -wrap arm-tf --vms-only -configfile $(PLATFORM_CONFIG_FILE)

vms: 
	# Android
	# cp $(ANDROID_PATH)/kernel $(ROOT)/out/cpio/
	# cp $(ANDROID_PATH)/combined-ramdisk.img $(ROOT)/out/cpio/
	# cp $(ANDROID_PATH)/devtree.dtb $(ROOT)/out/cpio/
	$(BUILD_SCRIPTS)/build_peregrine.py --vms-only -configfile $(PLATFORM_CONFIG_FILE)
	
