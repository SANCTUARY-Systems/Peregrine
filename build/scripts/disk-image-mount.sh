#!/usr/bin/env bash

set -uex
cd "$(dirname "$0")"

DISK_IMAGE_FILE="$1"
DISK_IMAGE_MAPPER_NAME="$2"
OPT="$3"

loopd=$(sudo losetup --partscan --find --show --nooverlap "$DISK_IMAGE_FILE")
echo "$loopd" > disk-image-loopd

echo -n "Bruce-Schneier" | sudo cryptsetup open /dev/loop2p1 $DISK_IMAGE_MAPPER_NAME

sudo mount -o loop,$OPT /dev/mapper/$DISK_IMAGE_MAPPER_NAME /mnt
