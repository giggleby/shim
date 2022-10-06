# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Test eDP panel is supported with proper timing.

Description
-----------
The eDP panel driver 'panel-simple-dp-aux' is a driver on ARM for ePD
panel, it can drive unknown panels as well with generic but conservative
timings. This test is to verify the eDP panel is not driven by generic but
conservative timing. It is only working with device with exactly 1
dp-aux device, and will perform check only if the used driver is
'panel-simple-dp-aux', and will check the debugfs content of
/sys/kernel/debug/dri/*/eDP*/panel/detected_panel and fail if the content is
'UNKNOWN'.
If the test failed due to not driving the panel with dedicated power sequence,
a message 'Unknown panel {panel_name} {panel_id}, using conservative timings'
is logged into dmesg. Please contact panel driver developers to ask them to add
support for the panel in the 'drivers/gpu/drm/panel/panel-edp.c', upstream the
change to Linux kernel, then land it in both main and relevant Chrome OS kernel
branches.

Test Procedure
--------------
This is an automated test without user interaction.

Dependency
----------
- cros.factory.device.device_utils
  - cros.factory.utils.sys_interface.Glob
  - cros.factory.utils.sys_interface.ReadFile

Examples
--------
To test the eDP::

  {
    "pytest_name": "edp_panel_timing"
  }
"""

import os

from cros.factory.device import device_utils
from cros.factory.test import test_case


class EDPPanelTimingTest(test_case.TestCase):

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()

  def runTest(self):
    if self._IsAnyDevicesOnDPAuxBus() and self._IsUsingPanelSimpleDPAuxDriver():
      self._CheckPanelTiming()

  def _IsAnyDevicesOnDPAuxBus(self):
    """Check dp-aux bus has devices."""
    return len(self._dut.Glob('/sys/bus/dp-aux/devices/*')) != 0

  def _IsUsingPanelSimpleDPAuxDriver(self):
    """Check the panel is using panel-simple-dp-aux driver."""
    drivers = self._dut.Glob('/sys/bus/dp-aux/devices/*/driver')
    if len(drivers) != 1:
      devices = [os.path.dirname(path) for path in drivers]
      self.fail(f'Should only be 1 device, found multiple {devices}')

    # TODO(lschyi): as the SystemInterface is not yet support read link, use the
    # os.path.realpath for now
    return os.path.realpath(
        drivers[0]) == '/sys/bus/dp-aux/drivers/panel-simple-dp-aux'

  def _CheckPanelTiming(self):
    """Check the content in debugfs and fail if the debug value is 'UNKNOWN'"""
    debug_detected_panels = self._dut.Glob(
        '/sys/kernel/debug/dri/*/eDP*/panel/detected_panel')
    if len(debug_detected_panels) != 1:
      self.fail(f'Should only be 1 debug file, found {debug_detected_panels}')

    debug_content = self._dut.ReadFile(debug_detected_panels[0]).strip()
    self.assertNotEqual(
        debug_content, 'UNKNOWN',
        f'panel-simple-dp-aux driver does not have dedicated power sequence'
        f'timings for this panel. Content from debugfs'
        f'{debug_detected_panels[0]} is {debug_content}')
