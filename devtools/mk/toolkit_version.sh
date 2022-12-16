#!/bin/bash
# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Usage: toolkit_version.sh

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "${SCRIPT_DIR}/common.sh" || exit 1

: ${CHROOT_SOURCE_DIR:=/mnt/host/source}
: ${CHROMIUMOS_OVERLAY:=${CHROOT_SOURCE_DIR}/src/third_party/chromiumos-overlay}
CROS_VERSION_SCRIPT=${CHROMIUMOS_OVERLAY}/chromeos/config/chromeos_version.sh

main() {
  local version=""
  local version_postfix=" $(whoami)@$(hostname)"

  if [ -x "${CROS_VERSION_SCRIPT}" ]; then
    version="$("${CROS_VERSION_SCRIPT}" | \
               sed -n 's/ *CHROMEOS_VERSION_STRING=//p')"
    if [ "${CHROMEOS_OFFICIAL:-0}" -ne 1 ]; then
      timestamp="$(date +%Y_%m_%d_%H%M%S)"
      version="$(echo "${version}" | cut -f 1,2 -d '.').${timestamp}"
    else
      version_postfix=""
    fi
  fi
  if [ -z "${version}" ]; then
    version="$(date '+%Y-%m-%dT%H:%M:%S')"
  fi
  echo "${version}${version_postfix}"
  mk_success
}
main "$@"
