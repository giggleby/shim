#!/bin/sh
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# We need to unload driver to prevent the toolkit screen from flashing black
# when pressing the recovery button.

echo GOOG0007:00 > /sys/bus/platform/drivers/cros-ec-keyb/unbind || true
