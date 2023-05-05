#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh
# shellcheck disable=SC2154
REQUIREMENTS="${EDITOR_DIR}/requirements.dev"

check_venv() {
  # TODO(louischiu): We should use poetry or some package management tool
  # to make this more robust.
  if ! diff <(pip freeze --local -r "${REQUIREMENTS}" | \
      sed -n '/^##/,$ !p') "${REQUIREMENTS}" ; then
    pip install --force-reinstall -r "${REQUIREMENTS}"
  fi
}
# shellcheck disable=SC2154
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
  check_venv
  exit
fi

pip install -r "${EDITOR_DIR}"/requirements.dev
