#!/usr/bin/env bash
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Usage: ./setup.sh [workspace_folder]
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
FACTORY_DIR="$(readlink -f "${SCRIPT_DIR}/../..")"
set -e
. "${SCRIPT_DIR}/../mk/common.sh"

main(){
  local workspace_folder="$1"
  if [ -z "${workspace_folder}" ]; then
    workspace_folder="${FACTORY_DIR}"
  fi
  local settings_dir="${workspace_folder}/.vscode"
  local settings_path="${settings_dir}/settings.json"

  if which "code"; then
    echo "Verified that the vscode is installed."
  else
    die "No vscode is installed as code. Run this script outside chroot if" \
        "you install vscode outside chroot."
  fi

  isort "${SCRIPT_DIR}/.isort.cfg"

  mkdir -p "${settings_dir}"
  cp -f "${SCRIPT_DIR}/factory_settings.json" "${settings_path}"
  sed -i "s#\${factoryFolder}#${FACTORY_DIR}#g" "${settings_path}"

  local jsconfig_path="${workspace_folder}/jsconfig.json"
  cp -f "${SCRIPT_DIR}/example_jsconfig.json" "${jsconfig_path}"
  sed -i "s#\${factoryFolder}#${FACTORY_DIR}#g" "${jsconfig_path}"

  echo "Add .vscode to your global .gitignore."
  echo "See https://gist.github.com/subfuzion/db7f57fff2fb6998a16c for more" \
    "information."
  mk_success
}

main "$@"
