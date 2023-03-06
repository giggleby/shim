#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_FOLDER="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"
EDITOR_FOLDER="$(realpath "${SCRIPT_FOLDER}"/../)"
VENV_FOLDER="$(realpath "${EDITOR_FOLDER}"/editor.venv)"
CHROOT_VENV_FOLDER="$(realpath "${EDITOR_FOLDER}"/editor.chroot.venv)"

in_chroot() {
  [ -n "${CROS_WORKON_SRCROOT}" ]
}

if in_chroot && [ ! -d "${CHROOT_VENV_FOLDER}" ]; then
  # Chroot Case
  echo "Setup env inside chroot."
  virtualenv -p python3.8 "${CHROOT_VENV_FOLDER}"
  source "${CHROOT_VENV_FOLDER}"/bin/activate
elif (! in_chroot) && [ ! -d "${VENV_FOLDER}" ]; then
  # Outside Case
  echo "Setup env outside chroot."
  virtualenv -p python3.10 "${VENV_FOLDER}"
  source "${VENV_FOLDER}"/bin/activate
else
  echo "Venv folder exists, Exiting..."
  exit
fi

pip install -r "${EDITOR_FOLDER}"/requirements.dev
