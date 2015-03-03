#!/bin/sh
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# http://crbug.com/410233: If TPM is owned, UI may get freak.
check_tpm() {
  echo "Checking if TPM is owned..."
  if [ "$(crossystem mainfw_type 2>/dev/null)" = "nonchrome" ] ||
     [ "$(cat /sys/class/misc/tpm0/device/owned 2>/dev/null)" != "1" ]; then
    echo "TPM is not owned or not ChromeOS. Safe."
    return
  fi

  local ttys="/dev/tty1 /dev/tty2 /dev/kmsg /dev/console"

  # If TPM is owned, we have to reboot otherwise UI may get freak.
  # Alert user and try to clear TPM.
  stop -n ui >/dev/null 2>&1 &
  echo "
        Sorry, you must clear TPM owner before running factory UI.
        We are going to do that for you (and then reboot) in 10 seconds.

        If you want to abort, do Ctrl-Alt-F2, login, and run

          stop factory
       " | tee -a $ttys
  for i in $(seq 10 -1 0); do
    echo " > Clear & reboot in ${i} seconds..." | tee -a $ttys
    sleep 1
  done

  crossystem clear_tpm_owner_request=1
  echo "Restarting system..." | tee -a $ttys
  reboot

  # Wait forever.
  sleep 1d
}

main() {
  check_tpm
}

main "$@"
