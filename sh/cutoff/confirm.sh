#!/bin/sh

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
DISPLAY_MESSAGE="${SCRIPT_DIR}/display_wipe_message.sh"

: "${TTY:=/run/frecon/vt0}"

main() {
  "${DISPLAY_MESSAGE}" "press_enter_to_continue"
  stty -F "${TTY}" sane

  if ! type evtest >/dev/null 2>&1; then
    echo "Cannot find command evtest" >"${TTY}"
    sleep 1d
  fi

  # TODO(stimim); find correct event id
  while evtest --query /dev/input/event2 EV_KEY KEY_ENTER; do
    sleep 0.01
  done
  echo "Received ENTER"
}

main "$@"
