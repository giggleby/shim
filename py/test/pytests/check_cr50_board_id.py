# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Check the board ID of the Cr50 firmware.

Description
-----------
This test checks the board ID in the Cr50 firmware matched the given
expectation or not.  The test gains the board ID by invoking `gsctool`
utility on DUT.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

1. Firstly, this test gets the board ID from the Cr50 firmware.
2. If the argument ``board_id_type`` is set, the test checks if the
   board ID type field is equal to the argument value or not.
3. If the argument ``board_id_flags`` is set, the test checks if the
   board ID flags field is equal to the argument value or not.

Dependency
----------
- DUT link must be ready before running this test.
- `gsctool` on DUT.

Examples
--------
To check if the board ID is still unprogrammed, add this in test list::

  {
    "pytest_name": "check_cr50_board_id",
    "args": {
      "board_id_type": "ffffffff",
      "board_id_flags": "ffffffff"
    }
  }

To check if the board ID is set to "UNKNOWN", you can either set the argument
``board_id_flags`` to `"0000ff00"` or by using the pre-defined marcos (see the
arguemnt description for the details)::

  {
    "pytest_name": "check_cr50_board_id",
    "args": {
      "board_id_flags": "PHASE_UNKNOWN"
    }
  }
"""

from cros.factory.device import device_utils
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.chromeos_cli import gsctool


class CheckCr50FirmwareBoardIDTest(test_case.TestCase):
  _PREDEFINED_PHASES = {
      'PHASE_UNSET': 0xffffffff,
      'PHASE_UNKNOWN': 0x0000ff00,
      'PHASE_PREPVT': 0x00007f7f,
      'PHASE_PVT': 0x00007f80,
      # Customlabel devices have different flags to distinguish with PVT.
      # In cr50 scripts, it's still called "WHITELABEL".
      # TODO(b/169766857): rename it when cr50 scripts are updated.
      'PHASE_WHITELABEL': 0x00003f80,
  }

  ARGS = [
      Arg(
          'board_id_type', (int, str), 'The expected board ID type, can be '
          'either an integer or a string of hex code.', default=None),
      Arg(
          'board_id_flags', (int, str), 'The expected board ID flags, can be '
          'either an integer or a string.  If the value is a string, '
          'the value can be either the hex code of the board ID flags or' +
          ', '.join(f'{k} for {v:08x}' for k, v in _PREDEFINED_PHASES.items()),
          default=None),
  ]

  def setUp(self):
    # Preprocesses the arguments.
    if isinstance(self.args.board_id_type, str):
      self.args.board_id_type = int(self.args.board_id_type, 16)
    if isinstance(self.args.board_id_flags, str):
      if self.args.board_id_flags.startswith('PHASE_'):
        self.args.board_id_flags = self._PREDEFINED_PHASES[
            self.args.board_id_flags]
      else:
        self.args.board_id_flags = int(self.args.board_id_flags, 16)

    # Setups the DUT environments.
    self.dut = device_utils.CreateDUTInterface()
    self.gsctool = gsctool.GSCTool(dut=self.dut)

    # Setups the logging framework.
    testlog.UpdateParam('board_id_type',
                        description='Board ID type in hex code')
    testlog.UpdateParam('board_id_flags',
                        description='Board ID flags in hex code')

  def runTest(self):
    board_id = self.gsctool.GetBoardID()
    board_id_type_str = f'{board_id.type:08x}'
    board_id_flags_str = f'{board_id.flags:08x}'
    session.console.info('Board ID type: %s; Board ID flags: %s.',
                         board_id_type_str, board_id_flags_str)
    testlog.LogParam('board_id_type', board_id_type_str)
    testlog.LogParam('board_id_flags', board_id_flags_str)

    succ = True
    if self.args.board_id_type is not None:
      if board_id.type != self.args.board_id_type:
        testlog.AddFailure('BoardIDTypeMismatch', '')
        succ = False
    if self.args.board_id_flags is not None:
      if board_id.flags != self.args.board_id_flags:
        testlog.AddFailure('BoardIDFlagsMismatch', '')
        succ = False
    if not succ:
      self.FailTask('Board ID mismatched.')
