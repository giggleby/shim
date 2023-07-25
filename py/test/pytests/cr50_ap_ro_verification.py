# Copyright 2021 The ChromiumOS Authors
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
  1. ccd open.
  2. Trigger the AP RO verification, and the device will reboot.
Second round (`rebooted` flag should be true)
  3. Deal with the verification result.

Dependency
----------
- The verification needs AP RO hash set, or it won't do anything.
- OS version >= 14704.0.0 (`gsctool -aB` and `gsctool -aB start`)
- cr50 version >= 0.5.111 (vendor commands to trigger RO verification)
- In cr50 factory mode to ccd open without physical presence.

Examples
--------
To test AP RO verification, add this to test list::

  {
    "pytest_name": "cr50_ap_ro_verification",
    "allow_reboot": true
  }

To use manual test of AP RO verification, add this to test list::

  {
    "pytest_name": "cr50_ap_ro_verification",
    "allow_reboot": true,
    "args": {
      "timeout_secs": 5,
      "manual_test": true
    }
  }
"""

import logging

from cros.factory.device import device_utils
from cros.factory.gooftool.core import Gooftool
from cros.factory.test.i18n import _
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test.utils.gsc_utils import GSCUtils
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.chromeos_cli import gsctool as gsctool_module


class OperationError(Exception):

  def __init__(self):
    super().__init__('Please retry the test.')


class Cr50APROVerficationTest(test_case.TestCase):
  related_components = (test_case.TestCategory.TPM, )
  ARGS = [
      Arg('timeout_secs', int,
          'How many seconds to wait for the RO verification key combo.',
          default=5),
      Arg('manual_test', bool, 'True to trigger the verification by key combo.',
          default=False),
  ]

  def setUp(self):
    self.gooftool = Gooftool()
    self.gsctool = gsctool_module.GSCTool()
    self.ui.ToggleTemplateClass('font-large', True)
    self.dut = device_utils.CreateDUTInterface()
    self.goofy = state.GetInstance()

    self.AddTask(self.PreCheck)
    self.AddTask(self.VerifyAPRO, reboot=True,
                 reboot_timeout_secs=self.args.timeout_secs)
    self.AddTask(self.CheckAPROResult)

  def HandleError(self, status):
    if status == gsctool_module.APROResult.AP_RO_NOT_RUN:
      # Since the verification is triggered by command, the only case that the
      # the verification won't be triggered is the reboot to recover from brick
      # when the verification failed.
      self.FailTask('The verification is failed.')
    elif status == gsctool_module.APROResult.AP_RO_UNSUPPORTED_NOT_TRIGGERED:
      # If AP RO verification is not supported, the test should fail in the
      # first round.
      if self.args.manual_test:
        raise OperationError
      raise Exception('Unexpected error, please retry the test.')
    elif status == gsctool_module.APROResult.AP_RO_FAIL:
      logging.exception(
          'Should not be here, device is expected to be not bootable.')
      self.FailTask('The verification is failed.')
    else:
      raise Exception(f'Unknown status {status}.')

  def PreCheck(self):
    # skip the test if the firmware is Ti50
    if GSCUtils().IsTi50():
      self.WaiveTest('Skip Cr50 AP RO Verification test '
                     'since the firmware is Ti50.')
    if self.gooftool.IsGSCBoardIDSet():
      self.WaiveTask('Unable to verify RO hash '
                     'since the board ID is set, test skipped.')
    if not self.gooftool.IsCr50ROHashSet():
      raise Exception('Please set RO hash first.')

  def VerifyAPRO(self):
    if self.args.manual_test:
      self.ui.SetState(
          _('Please press POWER and (REFRESH*3) in {seconds} seconds.',
            seconds=self.args.timeout_secs))
    else:
      try:
        self.gsctool.CCDOpen()
        self.gsctool.Cr50VerifyAPRO()
      finally:
        # If the command works properly, the device will reboot and won't
        # execute this line.
        self.FailTask('CR50 version should >= 0.5.111, '
                      'and check if DUT is in CR50 factory mode.')

  def CheckAPROResult(self):
    status = self.gsctool.GSCGetAPROResult()
    if status != gsctool_module.APROResult.AP_RO_PASS:
      self.HandleError(status)
