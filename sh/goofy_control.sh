#!/bin/sh
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e
FACTORY="$(dirname "$(dirname "$(readlink -f "$0")")")"
FACTORY_LOG_FILE=/var/factory/log/factory.log

BOARD_SETUP="$FACTORY/custom/board_setup_factory.sh"

# Default args for Goofy.
GOOFY_ARGS=""

# Use wrappers for tools that use the EC.
export PATH="/usr/local/factory/bin/ec_lock:$PATH"

# Default implementation for factory_setup (no-op).  May be overriden
# by board_setup_factory.sh.
factory_setup() {
    true
}

load_setup() {
  # Load board-specific parameters, if any.
  if [ -s $BOARD_SETUP ]; then
    echo "Loading board-specific parameters..." 1>&2
    . $BOARD_SETUP
  fi

  factory_setup
}

start_factory() {
  # HACK: get /var/factory off of the stateful partition
  if [ ! -e /var/factory/.remounted ]; then
    mkdir -p /mnt/stateful_partition/var_overlay/factory /var/factory
    if [ ! -e /mnt/stateful_partition/var_overlay/factory/.remounted ]; then
      rsync -a /var/factory/ /mnt/stateful_partition/var_overlay/factory/
      touch /mnt/stateful_partition/var_overlay/factory/.remounted
      # Delete old /var/factory/tests to make more room.
      rm -rf /var/factory/tests
    fi
    mount --bind /mnt/stateful_partition/var_overlay/factory /var/factory
    mkdir -p /var/factory/log /var/factory/state /var/factory/tests
    ln -sf /var/factory/log/factory.log /var/log
  fi

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
      $FACTORY/bin/restart -a
  "

  # Preload modules here
  modprobe i2c-dev 2>/dev/null || true

  cd "$FACTORY"/../autotest
  eval "$("$FACTORY/sh/startx.sh" 2>/var/log/startx.err)"
  "$FACTORY/bin/goofy" $GOOFY_ARGS >>"$FACTORY_LOG_FILE" 2>&1
}

stop_factory() {
  load_setup
  # Try to kill X, and any other Python scripts, five times.
  echo -n "Stopping factory."
  for i in $(seq 5); do
    pkill 'X|python' || break
    sleep 1
    echo -n "."
  done

  echo "

    Factory tests terminated. To check error messages, try
      tail $FACTORY_LOG_FILE

    To restart, press Ctrl-Alt-F2, log in, and type:
      $FACTORY/bin/restart

    If restarting does not work, try to reset by:
      $FACTORY/bin/restart -a
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
