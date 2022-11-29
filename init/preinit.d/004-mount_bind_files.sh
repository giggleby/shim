#!/bin/bash
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

main() {
  local FAKE_ROOT_DIR="${SCRIPT_DIR}/mount_bind_files"

  while IFS= read -r -d '' file; do
    local overridden_file="${file#"${FAKE_ROOT_DIR}"}"
    if [ -e "${overridden_file}" ]; then
      mount --bind "${file}" "${overridden_file}"
    fi
  done < <( find "${FAKE_ROOT_DIR}" -type f -print0 )
}

main