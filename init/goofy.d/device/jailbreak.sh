#!/bin/sh
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# minijail0 would lock mount points like /var and cause our wipe-in-place to
# fail. jailbreak tries to stub minijail0 so all processes will be executed in
# same name space (which is fine for factory tests).

SCRIPT_PATH="$(readlink -f "$0")"
TARGETS_DIR="${SCRIPT_PATH%.sh}"

main() {
  local target_src target_dest target_name
  for target_src in "${TARGETS_DIR}"/*; do
    target_name="${target_src##*/}"
    target_dest=/sbin/"${target_name}"
    if [ -x "${target_dest}" ]; then
      mount --bind "${target_src}" "${target_dest}"
    fi
  done
}

main "$@"
