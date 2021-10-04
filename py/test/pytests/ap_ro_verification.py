# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to ensure the AP RO verification works.

Description
-----------
The test updates RO hash, and asks operator to trigger verification manually.
Device will reboot during the test. If reboot/verification is not triggered,
there will be an operation error to ask for a retry.

If the verification failed, then the device won't be bootable.

Test Procedure
--------------
First round
  1. Update RO hash which to be verified. (`rebooted` flag should be None)
  2. Wait operator to press power and (refresh*3)
  3. After the combo, device will reboot with verifying RO hash
Second round
  4. Deal with the verification result. (`rebooted` flag should be true)

Dependency
----------
- The test updates RO hash, which needs board id not being set on the device.
- OS version >= 14196.0.0 (`tpm_manager_client get_ro_verification_status`)
- cr50 version >= 0.5.40 (vendor command to get RO verification status)

Examples
--------
To test AP RO verification, add this to test list::

  {
    "pytest_name": "ap_ro_verification",
    "allow_reboot": true
    "args": {
      "timeout_secs": 5
    }
  }

"""

import logging
from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test import test_case
from cros.factory.gooftool.core import Gooftool
from cros.factory.utils.arg_utils import Arg
from cros.factory.test import device_data
from cros.factory.utils import string_utils


class OperationError(Exception):

  def __init__(self):
    super().__init__('Please retry the test.')


class APROVerficationTest(test_case.TestCase):
  ARGS = [
      Arg('timeout_secs', int,
          'How many seconds to wait for the RO verification key combo.',
          default=5)
  ]

  def setUp(self):
    self.gooftool = Gooftool()
    if self.gooftool.IsCr50BoardIDSet():
      raise Exception('Please run this test without setting board id.')
    self.ui.ToggleTemplateClass('font-large', True)
    self.dut = device_utils.CreateDUTInterface()
    self.device_data_key = f'factory.{type(self).__name__}.has_rebooted'

  def GetStatus(self):
    # TODO(jasonchuang): Wrap tpm_manager_client as an util.
    status_txt = self.dut.CheckOutput(
        ['tpm_manager_client', 'get_ro_verification_status'], log=True)
    status_lines = status_txt.splitlines()
    return string_utils.ParseDict(status_lines[1:-1])['ro_verification_status']

  def HandleError(self, status):
    if status == 'RO_STATUS_NOT_TRIGGERED':
      raise OperationError
    if status == 'RO_STATUS_UNSUPPORTED':
      raise Exception('AP RO verification is not supported by this device. '
                      '(require cr50 version >= 0.5.40)')

    if status == 'RO_STATUS_FAIL':
      logging.exception(
          'Should not be here, device is expected to be not bootable.')
      self.FailTask('The verification is failed.')
    else:
      raise Exception(f'Unknown status {status}.')

  def runTest(self):
    rebooted = device_data.GetDeviceData(self.device_data_key)
    if rebooted:
      status = self.GetStatus()
      if status != 'RO_STATUS_PASS':
        self.HandleError(status)
    else:
      self.gooftool.Cr50SetROHash()
      device_data.UpdateDeviceData({self.device_data_key: True})
      self.ui.SetState(
          _('Please press POWER and (REFRESH*3) in {seconds} seconds.',
            seconds=self.args.timeout_secs))
      self.Sleep(self.args.timeout_secs)
      raise OperationError

  def tearDown(self):
    device_data.DeleteDeviceData(self.device_data_key)
