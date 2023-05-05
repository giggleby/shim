#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh

# Setup env if not present by "setup-env.sh"
"${SCRIPT_DIR}"/setup-env.sh
source "$(get_venv_dir)"/bin/activate

cd "${CROS_DIR}" || exit
python3 -m coverage run -m \
  unittest discover \
    -s cros/factory/test_list_editor/backend \
    -p "*_unittest.py" -v && \
python3 -m coverage report \
  --include="${EDITOR_DIR}/*" \
  --omit="*_unittest.py" && \
touch "${EDITOR_DIR}"/.tests-passed

rm -f .coverage
