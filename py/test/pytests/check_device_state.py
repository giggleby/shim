# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Description
-----------
All devices in factory should have an MLB serial number.

Some tests, for example, RF graphyte, assume DUTs have MLB serial number
available (in VPD and device data).  And the test will fail if a DUT
doesn't have MLB SN (e.g. it skipped previous station).

Test Procedure
--------------
This is an automated test.  It requires user interaction only if the test
failed.  This test will,

1. try to connect to device's state server
2. get MLB SN from state server
3. get MLB SN from VPD
4. these two MLB SN must match

Dependency
----------

1. SSH connection
2. DUT is running factory software

Examples
--------
This test is already defined in `station_based.test_list.json` as
"CheckDeviceState", you can enable it by setting `constants.check_device_state`
to `true`::

  "constants": {
    "check_device_state": true
  }

"""

import factory_common  # pylint: disable=unused-import

from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test import test_ui


HTML = """
<div>
  <div>
    MLB SN in Device Data: <span id='device-mlb-sn'></span>
  <div>
  <div>
    MLB SN in VPD: <span id='vpd-mlb-sn'></span>
  <div>
  <div id='message' style='color:red'></div>
</div>
"""


class CheckDeviceState(test_case.TestCase):
  def setUp(self):
    self.ui.SetTitle(_('Checking Device State'))

  def runTest(self):
    self.ui.SetState(HTML)

    success = True

    dut = device_utils.CreateDUTInterface()
    proxy = state.get_instance(dut.link.host)

    # must have device_id
    if not dut.info.device_id:
      self.ui.SetHTML(
          'No device_id<br />',
          id='message',
          append=True)
      success = False

    device_mlb_sn = proxy.data_shelf.GetValue(
        'device.serials.mlb_serial_number', default=None)
    self.ui.SetHTML(repr(device_mlb_sn), id='device-mlb-sn')
    vpd_mlb_sn = dut.CallOutput('vpd -g mlb_serial_number') or None
    self.ui.SetHTML(repr(vpd_mlb_sn), id='vpd-mlb-sn')

    if not device_mlb_sn:
      self.ui.SetHTML(
          'MLB SN not in device data<br />',
          id='message',
          append=True)
      success = False
    if not vpd_mlb_sn:
      self.ui.SetHTML(
          'MLB SN not in VPD<br />',
          id='message',
          append=True)
      success = False
    if vpd_mlb_sn != device_mlb_sn:
      self.ui.SetHTML(
          "Device data and VPD doesn't match<br />",
          id='message',
          append=True)
      success = False

    if success:
      session.console.info('OK: MLB_SN=%s', device_mlb_sn)
    else:
      self.ui.SetHTML(
          "Failed, Press SPACE to continue<br />",
          id='message',
          append=True)
      self.ui.WaitKeysOnce(keys=[test_ui.SPACE_KEY, test_ui.ENTER_KEY])
      self.FailTask('Invalid device state (MLB SN error)')
