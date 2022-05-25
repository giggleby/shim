# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to ensure the AP RO verification works.

Description
-----------
The test is to verify the functionality of AP RO verification in early phase
(The hash is usually written in PVT), but not the correctness of the hash.

If the verification failed, then the device won't be bootable. Reinsert the
battery or cr50 reboot to recover.
To avoid the risk of bricking the DUT, we should try to clear RO hash after
verifying. And it's recommended to set RO hash by ap_ro_hash.py to make sure
RO hash is set correctly, .

We decided to skip this test when Board ID has already been set. This might
happen when re-flowing or RMA. Details are in ap_ro_hash.py.

Test Procedure
--------------
First round (`rebooted` flag should be None)
  1. Trigger the AP RO verification, and the device will reboot.
Second round (`rebooted` flag should be true)
  2. Deal with the verification result.

Dependency
----------
- The verification needs AP RO hash set, or it won't do anything.
- OS version >= 14704.0.0 (`gsctool -aB` and `gsctool -aB start`)
- cr50 version >= 0.5.100 (vendor command to trigger RO verification)
- In cr50 factory mode (enable the vendor command to trigger RO verification)

Examples
--------
To test AP RO verification, add this to test list::

  {
    "pytest_name": "ap_ro_verification",
    "allow_reboot": true
  }

"""

import logging

from cros.factory.device import device_utils
from cros.factory.gooftool.core import Gooftool
from cros.factory.gooftool import gsctool
from cros.factory.test import device_data
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_case


class APROVerficationTest(test_case.TestCase):

  def setUp(self):
    self.gooftool = Gooftool()
    self.dut = device_utils.CreateDUTInterface()
    self.goofy = state.GetInstance()
    self.device_data_key = f'factory.{type(self).__name__}.has_rebooted'

  def HandleError(self, status):
    if status == gsctool.APROResult.AP_RO_NOT_RUN:
      # Since the verification is triggered by command, the only case that the
      # the verification won't be triggered is the reboot to recover from brick
      # when the verification failed.
      self.FailTask('The verification is failed.')
    elif status == gsctool.APROResult.AP_RO_UNSUPPORTED_NOT_TRIGGERED:
      # If AP RO verification is not supported, the test should fail in the
      # first round.
      raise Exception('Unexpected error, please retry the test.')
    elif status == gsctool.APROResult.AP_RO_FAIL:
      logging.exception(
          'Should not be here, device is expected to be not bootable.')
      self.FailTask('The verification is failed.')
    else:
      raise Exception(f'Unknown status {status}.')

  def runTest(self):
    if self.gooftool.IsCr50BoardIDSet():
      session.console.warn('Unable to verify RO hash '
                           'since the board ID is set, test skipped.')
      return
    if not self.gooftool.IsCr50ROHashSet():
      raise Exception('Please set RO hash first.')

    rebooted = device_data.GetDeviceData(self.device_data_key)
    if rebooted:
      status = self.gooftool.Cr50GetAPROResult()
      if status != gsctool.APROResult.AP_RO_PASS:
        self.HandleError(status)
    else:
      self.goofy.SaveDataForNextBoot()
      device_data.UpdateDeviceData({self.device_data_key: True})
      try:
        self.gooftool.Cr50VerifyAPRO()
      finally:
        # If the command works properly, the device will reboot and won't
        # execute this line.
        self.FailTask('CR50 version should >= 0.5.100, '
                      'and check if you are in CR50 factory mode.')

  def tearDown(self):
    device_data.DeleteDeviceData(self.device_data_key, True)
