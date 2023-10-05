#!/usr/bin/env bash

set -uex
cd "$(dirname "$0")"

DISK_IMAGE_FILE="$1"
DISK_IMAGE_MAPPER_NAME="$2"
DISK_IMAGE_SIZE_MEGS="$3"

dd if=/dev/zero of=${DISK_IMAGE_FILE} bs=1M count=$(( $DISK_IMAGE_SIZE_MEGS + 2 ))
echo "1M,${DISK_IMAGE_SIZE_MEGS}M,L,-;" | sfdisk -X gpt ${DISK_IMAGE_FILE}

# for plaintext ext4:
# mke2fs -t ext4 -I 256 -E offset=1048576 ${DISK_IMAGE_FILE} -F ${DISK_IMAGE_SIZE_MEGS}M

sudo -v

loopd=$(sudo losetup --partscan --find --show --nooverlap "$DISK_IMAGE_FILE")

echo -n "Bruce-Schneier" | sudo cryptsetup luksFormat ${loopd}p1 --pbkdf-force-iterations 1000 -

sudo cryptsetup luksDump ${loopd}p1

echo -n "Bruce-Schneier" | sudo cryptsetup open ${loopd}p1 $DISK_IMAGE_MAPPER_NAME

sudo mke2fs -t ext4 -I 256 /dev/mapper/$DISK_IMAGE_MAPPER_NAME

sudo cryptsetup close $DISK_IMAGE_MAPPER_NAME

sudo losetup -d "$loopd"
