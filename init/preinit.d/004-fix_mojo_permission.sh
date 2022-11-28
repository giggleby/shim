#!/bin/sh
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

MOJO_EXTRA_POLICY_DIR="/usr/local/etc/mojo/service_manager/policy"

main() {
  # Goofy is running as the `cros_init_scripts`, add this identity for accessing
  # the IIOService for accelerometer tests.
  cat > "${MOJO_EXTRA_POLICY_DIR}/iioservice_factory.jsonc" <<EOL
[
  {
    // Allow factory Goofy UI to run accelerometer tests.
    "identity": "u:r:cros_init_scripts:s0",
    "request": [
      "IioSensor"
    ]
  }
]
EOL
}

main
