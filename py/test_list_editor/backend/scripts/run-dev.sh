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

# Use gunicorn to serve the backend program.

# The program uses "gthread" worker class to look for a balance between
# IO-bound task and CPU-bound task. This would help alleviate the stress when
# React hooks are firing multiple requests to the service.
#
# The arguments would perform the following things:
#
# "-w 2": Sets process worker to 2. This is an arbitrary number.
#         According to the gunicorn document, this should be fairly small
#         number (< 12).
# "-b 0.0.0.0:"${PORT_NUMBER}"": Binds the service to listen to the specified
#                                url and port.
# "--enable-stdio-inheritance": Allow python print output to stdout.
# "--access-logfile -": Print the access log to stdout.
# "--threads 2": Set the thread count in each worker to 2. This is an
#                arbitrary number.
# "--reload": Reload when there is change to the backend program. Useful
#             functionality for debugging the service.
#
# For more detailed settings on how to tune the workers, please refer to
# the gunicorn document.
# https://docs.gunicorn.org/en/stable/settings.html#worker-processes

python3 -m gunicorn \
    -w 2 \
    -b 0.0.0.0:"${PORT_NUMBER}" \
    --worker-class gthread \
    --enable-stdio-inheritance \
    --access-logfile - \
    --threads 2 \
    --reload \
    cros.factory.test_list_editor.backend.main:app
