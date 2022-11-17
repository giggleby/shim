#!/bin/bash
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# shellcheck disable=SC2269
DATASTORE_HOST="${DATASTORE_HOST}"

# Retry on error to wait datastore start
status=$(curl "${DATASTORE_HOST}" --retry-all-errors --retry 5)
if [ "${status}" != "Ok" ]; then
  echo "Cannot reach datastore server." >&2
  exit 1
fi
