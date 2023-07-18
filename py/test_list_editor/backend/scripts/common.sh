# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Common directory used by the test list editor backend
SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"
EDITOR_DIR="$(realpath "${SCRIPT_DIR}"/../)"
CROS_DIR="$(realpath "${SCRIPT_DIR}"/../../../../py_pkg/)"
VENV_DIR="$(realpath "${EDITOR_DIR}"/editor.venv)"
CHROOT_VENV_DIR="$(realpath "${EDITOR_DIR}"/editor.chroot.venv)"

DEV_IMAGE_NAME=""

export SCRIPT_DIR
export EDITOR_DIR
export CROS_DIR
export VENV_DIR
export CHROOT_VENV_DIR
export DEV_IMAGE_NAME

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

gcloud_exists() {
  command -v gcloud >/dev/null 2>&1
}

kubectl_exists() {
  command -v kubectl >/dev/null 2>&1
}

verify_gcloud_project_set() {
  echo "Checking gcloud project is set to \"chromeos-factory\"."
  local gcloud_output
  gcloud_output=$(gcloud config get-value project 2>/dev/null)
  if [[ "${gcloud_output}" != "chromeos-factory" ]]; then
    echo "The output of 'gcloud config get project' is not set to\
    'chromeos-factory'. Please double check before execution."
    exit;
  fi
  echo "Verified gcloud project set to \"chromeos-factory\"."
}



export -f in_chroot
export -f get_venv_dir
export -f gcloud_exists
export -f verify_gcloud_project_set
export -f kubectl_exists
