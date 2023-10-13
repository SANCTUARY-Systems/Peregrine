# Build Project for the Peregrine Real-Time Hypervisor

Peregrine is a real-time hypervisor with a strong security focus, initially supporting aarch64 (64-bit Armv8 CPUs).

# Building
Install dependencies (tested for Ubuntu 20.04 LTS)

`sudo apt-get install android-tools-adb android-tools-fastboot autoconf automake bc bison build-essential ccache cscope curl device-tree-compiler expect flex ftp-upload gdisk iasl jq libattr1-dev libcap-dev libfdt-dev libftdi-dev libglib2.0-dev libgmp-dev libhidapi-dev libmpc-dev libncurses5-dev libpixman-1-dev libssl-dev libtool lxterminal make mtools netcat ninja-build python-crypto python3-crypto python-pyelftools python3-pycryptodome python3-pyelftools python3-serial lxterminal rsync unzip uuid-dev xdg-utils xterm xz-utils zlib1g-dev coreutils cryptsetup-bin swig git python3-pip wget cpio`



Preparations

`git clone https://github.com/SANCTUARY-Systems/Peregrine.git`

`git submodule update --init --recursive`

`python3 -m pip install build/scripts/requirements.txt`

Building

`cd build/`

`make peregrine`

`make vms-rebuild` -> building Linux, this takes some time

Running

`make run-only`

# Licensing
This is a GPLv2 open-source release for evaluation and research purposes. If you need a commercial license and support, please contact [info@sanctuary.dev](mailto:info@sanctuary.dev).

# A detailled README will follow.

