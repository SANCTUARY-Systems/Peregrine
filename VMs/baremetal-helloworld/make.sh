#!/usr/bin/env bash

set -uex
cd "$(dirname "$0")"

ROOT=$(readlink -e ..)

aarch64-linux-gnu-gcc -g -Wl,-T,test.ld startup.S test.c -o test.elf -nostartfiles

aarch64-linux-gnu-objcopy -O binary test.elf test.bin

