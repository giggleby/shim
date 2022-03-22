# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from cros.factory.probe.lib import cached_probe_function
from cros.factory.test.utils import hps_utils
from cros.factory.utils import sys_interface


class HPSFunction(cached_probe_function.CachedProbeFunction):
  """Probe the HPS (human presence sensor) information."""

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    if not os.path.exists('/dev/i2c-hps-controller'):
      return None
    hps_device = hps_utils.HPSDevice(sys_interface.SystemInterface())
    hps_device.PowerCycle()
    mcu_id, camera_id, spi_flash_id = hps_device.GetHPSInfo()
    results = [{
        'mcu_id': mcu_id,
        'camera_id': camera_id,
        'spi_flash_id': spi_flash_id,
    }]
    return results
