#!/bin/bash
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e

. /usr/local/factory/sh/common.sh

FACTORY="$(dirname "$(dirname "$(readlink -f "$0")")")"
FACTORY_LOG_FILE=/var/factory/log/factory.log

BOARD_SETUP=("$FACTORY/board/board_setup_factory.sh"
             "$FACTORY/custom/board_setup_factory.sh")

# Default args for Goofy.
GOOFY_ARGS=""
PRESENTER_ARGS=""

# Ports used by goofy
GOOFY_UI_PORT="4012"
GOOFY_LINK_PORTS="4020 4021"

# Default implementation for factory_setup (no-op).  May be overriden
# by board_setup_factory.sh.
factory_setup() {
    true
}

load_setup() {
  # Load board-specific parameters, if any.
  for f in "${BOARD_SETUP[@]}"; do
    if [ -s $f ]; then
      echo "Loading board-specific parameters $f..." 1>&2
      . $f
      break
    fi
  done

  if [[ -f ${AUTOMATION_MODE_TAG_FILE} ]]; then
    local mode="$(cat ${AUTOMATION_MODE_TAG_FILE})"
    if [[ -n "${mode}" ]]; then
      echo "Enable factory test automation with mode: ${mode}" 1>&2
      GOOFY_ARGS="${GOOFY_ARGS} --automation-mode=${mode}"
    fi
    if [[ -f ${STOP_AUTO_RUN_ON_START_TAG_FILE} ]]; then
      echo "Suppress test list auto-run on start" 1>&2
      GOOFY_ARGS="${GOOFY_ARGS} --no-auto-run-on-start"
    fi
  fi

  factory_setup
}

check_disk_usage() {
  # Show error in red
  echo -e "\033[1;31m"
  "$FACTORY/bin/disk_space" 2>&1 1>/dev/null || exit 1
  echo -e "\033[0m"
}

clear_tpm_owner() {
  # Alert user and try to clear TPM.
  local tty=/dev/tty5
  echo "
        Sorry, you must clear TPM owner before running factory UI.
        We are going to do that for you (and then reboot) in 10 seconds.

        If you want to abort, do Ctrl-Alt-F2, login, and run

          stop factory

       " >"$tty"
  chvt 5
  for i in $(seq 10 -1 0); do
    echo " > Clear & reboot in ${i} seconds..." >"$tty"
    sleep 1
  done
  crossystem clear_tpm_owner_request=1
  echo "Restarting system..." >"$tty"
  reboot
  # Wait forever.
  sleep 1d
}

start_factory() {
  # This should already exist, but just in case...
  mkdir -p "$(dirname "$FACTORY_LOG_FILE")"
  ln -sf "$FACTORY_LOG_FILE" /var/log

  load_setup
  echo "
    Starting factory program...

    If you don't see factory window after more than one minute,
    try to switch to VT2 (Ctrl-Alt-F2), log in, and check the messages by:
      tail $FACTORY_LOG_FILE

    If it keeps failing, try to reset by:
      factory_restart -a
  "

  # We disable powerd in factory image, but this folder is needed for some
  # commands like power_supply_info to work.
  mkdir -p /var/lib/power_manager

  # Preload modules here
  modprobe i2c-dev 2>/dev/null || true
  check_disk_usage

  # If TPM is owned, we have to reboot otherwise UI may get freak.
  if (cryptohome --action=tpm_status 2>&1 | grep -q 'TPM Owned: true'); then
    clear_tpm_owner
  fi

  # Open ports in the firewall so that the presenter can reach us
  # Note we want these ports to be expanded as a list, and so are unquoted
  local port=
  for port in $GOOFY_LINK_PORTS $GOOFY_UI_PORT; do
    /sbin/iptables -A INPUT -p tcp --dport ${port} -j ACCEPT
  done

  if [ -z "$(status ui | grep start)" ]; then
    start -n ui &
  fi

  if [ -f "${RUN_GOOFY_PRESENTER_TAG_FILE}" ] && \
     [ -f "${RUN_GOOFY_DEVICE_TAG_FILE}" ]; then
    GOOFY_ARGS="${GOOFY_ARGS} --standalone"
    PRESENTER_ARGS="${PRESENTER_ARGS} --standalone"
  fi

  # Run goofy_presenter if goofy_presenter tag file is present
  if [ -f "${RUN_GOOFY_PRESENTER_TAG_FILE}" ]; then
    "$FACTORY/bin/goofy_presenter" $PRESENTER_ARGS >>"$FACTORY_LOG_FILE" 2>&1 &
  fi

  # Run goofy(device) if the goofy_device tag file is present,
  # or goofy_presenter tag file is missing
  if [ -f "${RUN_GOOFY_DEVICE_TAG_FILE}" \
       -o ! -f "${RUN_GOOFY_PRESENTER_TAG_FILE}" ]; then
       "$FACTORY/bin/goofy" $GOOFY_ARGS >>"$FACTORY_LOG_FILE" 2>&1 &
  fi

  wait
}

stop_factory() {
  load_setup
  # Try to kill X, and any other Python scripts, five times.
  echo -n "Stopping factory."
  for i in $(seq 5); do
    pkill 'python' || break
    sleep 1
    echo -n "."
  done

  echo "

    Factory tests terminated. To check error messages, try
      tail $FACTORY_LOG_FILE

    To restart, press Ctrl-Alt-F2, log in, and type:
      factory_restart

    If restarting does not work, try to reset by:
      factory_restart -a
    "
}

case "$1" in
  "start" )
    start_factory "$@"
    ;;

  "stop" )
    stop_factory "$@"
    ;;

  * )
    echo "Usage: $0 [start|stop]"
    exit 1
    ;;
esac
