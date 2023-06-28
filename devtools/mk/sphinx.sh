#!/bin/bash
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "${SCRIPT_DIR}/common.sh" || exit 1
. "${SCRIPT_DIR}/venv_common.sh" || exit 1

: "${SPHINX_VENV:="${SCRIPT_DIR}/sphinx.venv"}"
: "${SPHINX_REQUIREMENTS:="${SCRIPT_DIR}/sphinx.requirements.txt"}"

main(){
  local make="$1"
  local doc_tmp_dir="$2"

  load_venv "${SPHINX_VENV}" "${SPHINX_REQUIREMENTS}" || exit 1

  "${make}" -C "${doc_tmp_dir}" html

  mk_success
}

main "$@"
