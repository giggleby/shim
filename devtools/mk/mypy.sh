#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "${SCRIPT_DIR}/common.sh" || exit 1
. "${SCRIPT_DIR}/venv_common.sh" || exit 1

: "${MYPY_VENV:="${SCRIPT_DIR}/mypy.venv"}"
: "${MYPY_REQUIREMENTS:="${SCRIPT_DIR}/mypy.requirements.txt"}"

main(){
  load_venv "${MYPY_VENV}" "${MYPY_REQUIREMENTS}" || exit 1

  "$@"

  mk_success
}

main "$@"
