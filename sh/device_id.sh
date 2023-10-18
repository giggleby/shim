#!/bin/sh
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# A script to generate a "trusted" device identifier.

# Finds root device.
get_rootdev() {
  if type rootdev >/dev/null 2>&1; then
    rootdev -s -d
    return
  fi

  local device_number="$(stat -c '%d' /)"
  local major="$(( device_number / 256 ))"
  local minor="$(( device_number % 256 ))"
  local dev_path="/sys/dev/block/${major}:${minor}"

  if [ -d "${dev_path}" ]; then
    # dev_path may be /dev/dm-0, and we want to find first "real" device.
    while true; do
      local slaves=$(ls "${dev_path}/slaves" 2>/dev/null || true)
      if [ -z "${slaves}" ] || ! [ -d "${dev_path}/slaves/${slaves}" ]; then
        break
      fi
      dev_path="${dev_path}/slaves/${slaves}"
    done
    echo /dev/"$(basename "$(readlink -f "${dev_path}")")"
    return
  fi

  return 1
}

# Get md5sum of given input.
get_md5sum() {
  local input="$1"
  echo "${input}" | md5sum | cut -d ' ' -f 1
}

# Use disk storage name and serial number to build device id.
id_storage() {
  local device="$1"

  if [ -z "${device}" ]; then
    device="$(get_rootdev)"
  fi

  # Normally this is done by /etc/init/udev-trigger.conf.
  # Since the script would be run at system startup, before the udev-trigger is
  # run, we need to do this by ourselves.
  udevadm trigger --subsystem-match block
  udevadm settle

  # Leverage ID_SERIAL and ID_NAME as input context
  # to generate md5sum as device id.
  get_md5sum "$(udevadm info --query=property "${device}" \
                  | grep 'ID_\(SERIAL\|NAME\)=' \
                  | sort)"
}

# Collect all ethernet type network interfaces and compute a hash.
id_ethernet() {
  get_md5sum "$(ip addr | grep link/ether | sort)"
}

# Use GSC device id (available for cr50 or ti50 devices) to build device id.
id_gsc_device() {
  # Leverage GSC device id as input context
  # to generate md5sum as device id.
  get_md5sum "$(gsctool -a -K dev_ids)"
}

main() {
  set -e
  if command -v gsctool >/dev/null 2>&1; then
    id_gsc_device
  else
    id_storage "$@"
  fi
}
main "$@"
