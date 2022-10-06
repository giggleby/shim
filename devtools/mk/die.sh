#!/bin/bash
# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Provides an easy way for Makefile rule to do "echo 'msg' >&2; exit 1".
# Usage: die.sh MESSAGE

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "${SCRIPT_DIR}/common.sh" || exit 1

die "$*"
