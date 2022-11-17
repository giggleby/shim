# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe.lib import runtime_probe_function


class GenericBatteryFunction(runtime_probe_function.RuntimeProbeFunction):
  """Probe the battery information."""
  CATEGORY_NAME = 'battery'
  FUNCTION_NAME = 'generic_battery'
