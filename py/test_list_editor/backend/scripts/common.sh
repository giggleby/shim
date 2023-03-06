# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Common directory used by the test list editor backend
SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"
EDITOR_DIR="$(realpath "${SCRIPT_DIR}"/../)"
CROS_DIR="$(realpath "${SCRIPT_DIR}"/../../../../py_pkg/)"
VENV_DIR="$(realpath "${EDITOR_DIR}"/editor.venv)"
CHROOT_VENV_DIR="$(realpath "${EDITOR_DIR}"/editor.chroot.venv)"

export SCRIPT_DIR
export EDITOR_DIR
export CROS_DIR
export VENV_DIR
export CHROOT_VENV_DIR

in_chroot() {
  [ -n "${CROS_WORKON_SRCROOT}" ]
}

get_venv_dir() {
  if in_chroot; then
    echo "${CHROOT_VENV_DIR}"
  else
    echo "${VENV_DIR}"
  fi
}

export -f in_chroot
export -f get_venv_dir