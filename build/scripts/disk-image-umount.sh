#!/usr/bin/env bash

set -uex
cd "$(dirname "$0")"

DISK_IMAGE_MAPPER_NAME="$1"

sudo umount /mnt

sudo cryptsetup close $DISK_IMAGE_MAPPER_NAME

sudo losetup -d $(cat disk-image-loopd)
rm disk-image-loopd

