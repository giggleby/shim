#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "${SCRIPT_DIR}/common.sh" || exit 1
. "${SCRIPT_DIR}/venv_common.sh" || exit 1

: "${COVERAGE_VENV:="${SCRIPT_DIR}/coverage.venv"}"
: "${COVERAGE_REQUIREMENTS:="${SCRIPT_DIR}/coverage.requirements.txt"}"

main(){
  load_venv "${COVERAGE_VENV}" "${COVERAGE_REQUIREMENTS}" || exit 1

  test_files="$1"
  includes="$2"
  excludes="$3"
  html="$4"

  mkdir -p .coverage_data
  bin/run_unittests ${test_files} --coverage
  coverage combine >/dev/null

  coverage report --include "${includes}" --omit "${excludes}"
  if [ -n "${html}" ]; then
    coverage html --include "${includes}" --omit "${excludes}"
  fi

  mk_success
}

main "$@"