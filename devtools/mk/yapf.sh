#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "${SCRIPT_DIR}/common.sh" || exit 1
. "${SCRIPT_DIR}/venv_common.sh" || exit 1

: "${YAPF_VENV:="${SCRIPT_DIR}/yapf.venv"}"
: "${YAPF_REQUIREMENTS:="${SCRIPT_DIR}/yapf.requirements.txt"}"

main(){
  load_venv "${YAPF_VENV}" "${YAPF_REQUIREMENTS}" || exit 1

  "$@"

  mk_success
}

main "$@"
