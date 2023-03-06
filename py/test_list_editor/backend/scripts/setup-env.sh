#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh

if in_chroot && [ ! -d "${CHROOT_VENV_DIR}" ]; then
  # Chroot Case
  echo "Setup env inside chroot."
  virtualenv -p python3.8 "${CHROOT_VENV_DIR}"
  source "${CHROOT_VENV_DIR}"/bin/activate
elif (! in_chroot) && [ ! -d "${VENV_DIR}" ]; then
  # Outside Case
  echo "Setup env outside chroot."
  virtualenv -p python3.10 "${VENV_DIR}"
  source "${VENV_DIR}"/bin/activate
else
  echo "Venv folder exists, Exiting..."
  exit
fi

pip install -r "${EDITOR_DIR}"/requirements.dev
