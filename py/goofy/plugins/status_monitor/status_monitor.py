# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.device import device_utils
from cros.factory.goofy.plugins import plugin
from cros.factory.utils import type_utils


# Since plugin runs in another thread, user needs to be careful not to
# collect the FW info while updating the FW.
_INFO_TO_MONITOR = (
    'mlb_serial_number',
    'serial_number',
    'stage',
    'test_image_version',
    'release_image_version',
    'firmware_version',
    'kernel_version',
    'architecture',
    'ec_version',
    'root_device',
    'device_id',
    'toolkit_version',
    'hwid_database_version',
)

class StatusMonitor(plugin.Plugin):

  def __init__(self, goofy, used_resources=None):
    super().__init__(goofy, used_resources)
    self._device = device_utils.CreateStationInterface()

  @type_utils.Overrides
  def GetUILocation(self):
    return 'status-monitor'

  @plugin.RPCFunction
  def UpdateDeviceInfo(self):
    """The device info is changed, update them on UI."""
    self._device.info.Invalidate()

  @plugin.RPCFunction
  def GetSystemInfo(self):
    """Returns system status information.

    This may include system load, battery status, etc. See
    cros.factory.device.status.SystemStatus. Return None
    if DUT is not local (station-based).
    """

    data = {ele: getattr(self._device.info, ele)
            for ele in _INFO_TO_MONITOR}

    if self._device.link.IsLocal():
      data.update(self._device.status.Snapshot().__dict__)

    return data
