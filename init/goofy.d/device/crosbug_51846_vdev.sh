#!/bin/sh
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# http://crosbug.com/p/51846: Virtual dev mode can't persist.

check_virtual_dev_mode() {
  local FIRMWARE_NV_INDEX="0x1007"
  local FLAG_VIRTUAL_DEV_MODE_ON="0x02"

  echo "Checking if virtual dev is enabled..."
  local nvflag="$(tpm_nvread -i ${FIRMWARE_NV_INDEX} | tail -c +14 | head -c 2)"
  # Example output of nvread:
  # 00000000  02 03 01 00 01 00 00 00 00 7a
  # And we want the 3th number.

  [ "$((nvflag & FLAG_VIRTUAL_DEV_MODE_ON))" != 0 ]
}

is_write_protected() {
  echo "Checking write-protection status..."
  if crossystem 'wpsw_boot?1' &&
     flashrom --wp-status | grep -q 'write protect is enabled'; then
    return 0
  fi
  return 1
}

main() {
  check_virtual_dev_mode || return 0
  is_write_protected && return 0

  # Try to turn on write GBB flags and disable write protection.
  local tmp_file="/tmp/_cr51846.bin"
  flashrom -r "${tmp_file}" -i GBB
  local flags_output="$(gbb_utility --flags ${tmp_file})"
  local GBB_FLAG_FORCE_DEV_SWITCH_ON="0x08"
  local flags="${flags_output#* }"
  local new_flags="$(
          printf "%#010x" "$((flags | GBB_FLAG_FORCE_DEV_SWITCH_ON))")"
  if [ "${flags}" != "${new_flags}" ]; then
    echo "Setting GBB flags from ${flags} to ${new_flags}."
    /usr/share/vboot/bin/set_gbb_flags.sh "${new_flags}"
  fi
  crossystem disable_dev_request=1
}

set -e
main "$@"
