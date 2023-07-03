#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh
# shellcheck disable=SC2154
REQUIREMENTS="${EDITOR_DIR}/requirements.dev"

setup_by_piptool() {
  pip install pip-tools
  pip-sync requirements.txt requirements-dev.txt
}

# shellcheck disable=SC2154
if in_chroot && [ ! -d "${CHROOT_VENV_DIR}" ]; then
  # Chroot Case
  echo "Setup env inside chroot."
  virtualenv -p python3.8 "${CHROOT_VENV_DIR}"
  source "${CHROOT_VENV_DIR}"/bin/activate
  setup_by_piptool
  exit
elif (! in_chroot) && [ ! -d "${VENV_DIR}" ]; then
  # Outside Case
  echo "Setup env outside chroot."
  virtualenv -p python3.10 "${VENV_DIR}"
  source "${VENV_DIR}"/bin/activate
  setup_by_piptool
  exit
fi
echo "Venv folder exists, sync dependencies"

if in_chroot; then
  # Chroot Case
  source "${CHROOT_VENV_DIR}"/bin/activate
  pip-sync requirements.txt requirements-dev.txt
else
  # outside
  source "${VENV_DIR}"/bin/activate
  pip-sync requirements.txt requirements-dev.txt
fi
