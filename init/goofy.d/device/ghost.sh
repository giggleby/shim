#!/bin/sh
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

FACTORY_BASE="/usr/local/factory"

export PATH=${FACTORY_BASE}/bin:${FACTORY_BASE}/bin/overlord:$PATH

TEST_LIST="$(factory test-list | tail -n1)"
MAC="$(iw dev | grep addr | cut -d' ' -f2)"

PROPERTIES_FILE="${FACTORY_BASE}/board/${TEST_LIST}-properties.json"
if ! [ -e "${PROPERTIES_FILE}" ]; then
  PROPERTIES_FILE="${FACTORY_BASE}/board/default-properties.json"
fi

${FACTORY_BASE}/bin/ghost \
    --fork 172.23.104.2 \
    --mid "${TEST_LIST}-${MAC}" \
    --prop-file "${PROPERTIES_FILE}" > /dev/null 2>&1
