# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to ensure the AP RO verification works on Ti50.

Description
-----------
The test is an end-to-end test that verify the functionality and firmware
with AP RO verification on Ti50.
It helps to carefully verify AP RO verification on Ti50 in the factory flow,
and make sure the verification can pass with any google signed FW,
which prevent from ti50 bricking the shipped device.

Test Procedure
--------------
1. Enable software write protect (PVT/MP only).
2. Set board ID.
3. Set addressing mode and WPSR.
4. reboot GSC by 'gsctool -a --reboot'.
5. 'gsctool -a -B' should return 'apro result (36)'. Otherwise fail the test.
6. Disable software write protect.

Dependency
----------
- gsctool >= 15287.0.0 to include 'gsctool -a -reboot'.
- Ti50 >= 0.(24|23).20 (24 for prepvt and 23 for prod)
  to include 'apro result (36)'.
- That the write protect status register values have been provisioned on ti50.
- AP firmware is either preMP or MP signed.
  Will not work with test signed AP firmware.

Examples
--------
To test AP RO verification, add this to test list::

  {
    "pytest_name": "ti50_ap_ro_verification",
    "allow_reboot": true,
  }
"""

from cros.factory.gooftool.common import Util
from cros.factory.gooftool.core import Gooftool
from cros.factory.gooftool import write_protect_target
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.gsc_utils import GSCUtils

from cros.factory.external.chromeos_cli import gsctool


class Ti50APROVerficationTest(test_case.TestCase):
  """A test to ensure the AP RO verification works on Ti50."""
  ARGS = [
      Arg('enable_swwp', bool, 'True for enabling SWWP (PVT/MP only).',
          default=False),
      Arg('two_stages', bool,
          'Whether the factory_process is "TWOSTAGES" or not.', default=False),
      Arg('wpsr', str,
          'Write Protect Status Register (WPSR) values and masks.'),
  ]

  def setUp(self):
    self.gooftool = Gooftool()
    self.goofy = state.GetInstance()
    self._util = Util()
    self.ap_wp_target = write_protect_target.CreateWriteProtectTarget(
        write_protect_target.WriteProtectTargetType.AP)

    self.AddTask(self.PreCheck)
    self.AddTask(self.VerifyAPRO, reboot=True)
    self.AddTask(self.CheckAPROResult)

  def PreCheck(self):
    # Skip the test if thr firmware is not Ti50.
    if not GSCUtils().IsTi50():
      self.WaiveTask('Skip Ti50 AP RO Verification test '
                     'since the firmware is not Ti50.')

  def VerifyAPRO(self):
    try:
      # Enable software write protect.
      if self.args.enable_swwp:
        session.console.info('Enable SWWP.')
        self.ap_wp_target.SetProtectionStatus(enable=True,
                                              skip_enable_check=True)

      # Set board ID.
      session.console.info('Set board ID.')
      self.gooftool.Cr50SetBoardId(two_stages=self.args.two_stages)

      # Set Addressing mode and WPSR.
      session.console.info('Set Addressing mode and WPSR.')
      self.gooftool.Ti50SetAddressingMode()
      self.gooftool.Ti50SetSWWPRegister(
          no_write_protect=(not self.args.enable_swwp), wpsr=self.args.wpsr)

      # Reboot GSC.
      try:
        session.console.info('Start to reboot GSC...')
        self.gooftool.GSCReboot()
      finally:
        # If the command works properly, the device will reboot and won't
        # execute this line.
        self.FailTask('Reboot failed. '
                      'Please make sure gsctool version >= 15287.0.0.')
    finally:
      # Disable software write protect if reboot is not triggered.
      if self.args.enable_swwp:
        session.console.info('Disable SWWP.')
        self.ap_wp_target.SetProtectionStatus(enable=False)

  def CheckAPROResult(self):
    # Check the result after device has rebooted.
    # We cannot set zero GBB flags in factory mode,
    # so we want to look for:
    # 'apro result (36) : AP_RO_V2_NON_ZERO_GBB_FLAGS',
    # which will map to a failure only related to non-zero GBB flags,
    # but it would pass if GBB flags are zero.
    try:
      result = self.gooftool.GSCGetAPROResult()
      if result != gsctool.APROResult.AP_RO_V2_NON_ZERO_GBB_FLAGS:
        self.FailTask('Ti50 AP RO Verification failed '
                      f'with the following result: {result.name}')
        session.console.info('Ti50 AP RO Verification passed.')
    finally:
      # Disable software write protect.
      if self.args.enable_swwp:
        session.console.info('Disable SWWP.')
        self.ap_wp_target.SetProtectionStatus(enable=False)