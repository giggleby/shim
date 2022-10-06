# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe.lib import cached_probe_function
from cros.factory.test.utils import hps_utils
from cros.factory.utils import sys_interface


class HPSFunction(cached_probe_function.CachedProbeFunction):
  """Probe the HPS (human presence sensor) information."""

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    if not hps_utils.HasHPS():
      return None
    hps_device = hps_utils.HPSDevice(sys_interface.SystemInterface())
    mcu_id, camera_id, spi_flash_id = hps_device.GetHPSInfo()
    results = [{
        'mcu_id': mcu_id,
        'camera_id': camera_id,
        'spi_flash_id': spi_flash_id,
    }]
    return results
