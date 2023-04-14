# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to check the state of TPM die.

Description
-----------
A test to verify if TPM is in fused off state from the `cbmem` command. This
test requires a normal version of the firmware. We cannot use "serial" or "dev"
version of firmware. We need the normal version because the HSP state log will
be washed off if using serial or dev firmware.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

Dependency
----------
- Normal firmware.
- ``cbmem`` utility.

Examples
--------
To verify the tpm state, add this to test list::

  {
    "pytest_name": "tpm_state",
  }

"""

import re

from cros.factory.device import device_utils
from cros.factory.test import session
from cros.factory.test import test_case


GET_TPM_STATE_CMD = 'cbmem -1 | grep -i hsp'
TPM_SUCCESS_STATE_REGEXP = r'HSP Secure state:\s+0x20'


class TPMStateNotFoundException(Exception):
  """Exception to raise when TPM state is not found in log."""


class VerifyTPMState(test_case.TestCase):
  """Factory Test for verifying tpm state."""

  def setUp(self) -> None:
    self._dut = device_utils.CreateDUTInterface()

  def _CheckTPMFusedOff(self) -> bool:
    """Returns if TPM chip is in fused off state or not.

    This function executes `cbmem` command to grep and verify if the TPM chip is
    in fused off state. In some situations, the command we use may return empty
    string. We will raise an exception if return value of the command is empty.

    Returns:
      Bool, boolean value of if the chip is in fused off state.

    Raises:
      TPMStateNotFoundException: if the log output from `cbmem` command
        didn't show HSP state.
    """
    state_result: str = self._dut.CallOutput(GET_TPM_STATE_CMD)

    if not state_result:
      session.console.error('cbmem did not show TPM log')
      raise TPMStateNotFoundException

    if re.match(TPM_SUCCESS_STATE_REGEXP, state_result):
      return True

    session.console.info(f'Incorrect TPM state, output: {state_result}')

    return False

  def runTest(self):
    self.assertTrue(self._CheckTPMFusedOff())
