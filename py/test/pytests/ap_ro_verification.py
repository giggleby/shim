# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to ensure the AP RO verification works.

Description
-----------
The test asks operator to trigger verification manually, and device will reboot
during the test. If reboot/verification is not triggered, there will be an
operation error to ask for a retry.

If the verification failed, then the device won't be bootable.

Test Procedure
--------------
First round (`rebooted` flag should be None)
  1. Wait operator to press power and (refresh*3).
  2. After the combo, device will reboot with verifying RO hash.
Second round (`rebooted` flag should be true)
  3. Deal with the verification result.

Dependency
----------
- The test needs to be run after setting AP RO hash by ap_ro_hash.py.
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
from cros.factory.gooftool.core import Gooftool
from cros.factory.test import device_data
from cros.factory.test.i18n import _
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
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
    if not self.gooftool.IsCr50ROHashSet():
      raise Exception('Please set ro hash first.')

    self.ui.ToggleTemplateClass('font-large', True)
    self.dut = device_utils.CreateDUTInterface()
    self.goofy = state.GetInstance()
    self.device_data_key = f'factory.{type(self).__name__}.has_rebooted'

  def GetStatus(self):
    # TODO(jasonchuang): Wrap tpm_manager_client as an util.
    status_txt = self.dut.CheckOutput(
        ['tpm_manager_client', 'get_ro_verification_status'], log=True)
    logging.info('RO verification status: %s.', status_txt)
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
      self.goofy.SaveDataForNextBoot()
      device_data.UpdateDeviceData({self.device_data_key: True})
      self.ui.SetState(
          _('Please press POWER and (REFRESH*3) in {seconds} seconds.',
            seconds=self.args.timeout_secs))
      self.Sleep(self.args.timeout_secs)
      logging.info('Reboot not triggered.')
      raise OperationError

  def tearDown(self):
    device_data.DeleteDeviceData(self.device_data_key)
