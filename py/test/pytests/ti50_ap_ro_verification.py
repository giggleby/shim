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
Before leaving the factory mode, the WPSR can be written for multiple times,
and the WPSR written in this test will be overwritten in finalize.

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
  }
"""

import subprocess

from cros.factory.gooftool.common import Util
from cros.factory.gooftool.core import Gooftool
from cros.factory.gooftool import write_protect_target
from cros.factory.test import device_data
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.gsc_utils import GSCUtils

from cros.factory.external.chromeos_cli import gsctool as gsctool_module


class Ti50APROVerficationTest(test_case.TestCase):
  """A test to ensure the AP RO verification works on Ti50."""
  ARGS = [
      Arg('enable_swwp', bool, 'True for enabling SWWP (PVT/MP only).',
          default=False),
      Arg('two_stages', bool,
          'Whether the factory_process is "TWOSTAGES" or not.', default=False),
  ]

  def setUp(self):
    self.gooftool = Gooftool()
    self.gsctool = gsctool_module.GSCTool()
    self.goofy = state.GetInstance()
    self.device_data_key = f'factory.{type(self).__name__}.has_rebooted'
    self._util = Util()
    self.ap_wp_target = write_protect_target.CreateWriteProtectTarget(
        write_protect_target.WriteProtectTargetType.AP)

  def runTest(self):
    # Skip the test if thr firmware is not Ti50.
    if not GSCUtils().IsTi50():
      session.console.info('Skip Ti50 AP RO Verification test'
                           'since the firmware is not Ti50.')
      return

    # Check whether the device has rebooted or not.
    rebooted = device_data.GetDeviceData(self.device_data_key)

    try:
      if rebooted:
        # Check the result after device has rebooted.
        # We cannot set zero GBB flags in factory mode,
        # so we want to look for:
        # 'apro result (36) : AP_RO_V2_NON_ZERO_GBB_FLAGS',
        # which will map to a failure only related to non-zero GBB flags,
        # but it would pass if GBB flags are zero.
        result = self.gsctool.GSCGetAPROResult()
        if result != gsctool_module.APROResult.AP_RO_V2_NON_ZERO_GBB_FLAGS:
          self.FailTask('Ti50 AP RO Verification failed '
                        f'with the following result: {result.name}')
      else:
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
            no_write_protect=(not self.args.enable_swwp))

        # Reboot GSC.
        self.goofy.SaveDataForNextBoot()
        device_data.UpdateDeviceData({self.device_data_key: True})
        subprocess.check_call('sync')
        try:
          self.gsctool.Ti50VerifyAPRO()
        finally:
          # If the command works properly, the device will reboot and won't
          # execute this line.
          self.Sleep(5)
          self.FailTask('Please make sure gsctool version >= 15287.0.0.')
    finally:
      # Disable software write protect.
      if self.args.enable_swwp:
        session.console.info('Disable SWWP.')
        self.ap_wp_target.SetProtectionStatus(enable=False)

  def tearDown(self):
    device_data.DeleteDeviceData(self.device_data_key, True)
