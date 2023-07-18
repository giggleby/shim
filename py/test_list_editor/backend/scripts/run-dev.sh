#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh

PORT_NUMBER="${1:-5000}"

# Setup env if not present by "setup-env.sh"
"${SCRIPT_DIR}"/setup-env.sh
source "$(get_venv_dir)"/bin/activate

echo "Starting Flask Server";
cd "${CROS_DIR}" || exit
python3 -m flask --app cros.factory.test_list_editor.backend.main \
  --debug run -p "${PORT_NUMBER}" --host 0.0.0.0
