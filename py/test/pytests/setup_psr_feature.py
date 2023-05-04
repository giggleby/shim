# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to set/check PSR EOM NVAR and start PSR Log.

Description
-----------
This test does one of these action: set EOM NVAR(close manufacturing), check
EOM NVAR value equals 1 or start PSR log.

Test Procedure
--------------
This pytest does not require operator interaction.

Dependency
----------
- `intel-psrtool`

Examples
--------
To set PSR EOM NVAR, add this to test list::

  {
    "pytest_name": "psr_tool",
    "args": {
      "action": "SET"
    }
  }

To check PSR EOM NVAR, add this to test list::

  {
    "pytest_name": "psr_tool",
    "args": {
      "action": "CHECK"
    }
  }

To start PSR log, add this to test list::

  {
    "pytest_name": "psr_tool",
    "args": {
      "action": "START"
    }
  }

"""
import enum

from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.chromeos_cli import intel_psrtool


class EnumAction(str, enum.Enum):
  set = 'set'
  check = 'check'
  start = 'start'

  def __str__(self):
    return self.name


class PSRToolTest(test_case.TestCase):
  ARGS = [Arg('action', EnumAction, "Which action to do")]

  def setUp(self):
    self._intel_psr_tool = intel_psrtool.IntelPSRTool()

  def runTest(self):
    action = self.args.action
    if action == EnumAction.set:
      self._intel_psr_tool.CloseManufacturing()
    elif action == EnumAction.check:
      EOM_NVAR = self._intel_psr_tool.GetManufacturingNVAR()
      self.assertEqual(
          1, EOM_NVAR, f'Current EOM NVAR value is {EOM_NVAR}. But it should '
          'be 1 after closing manufacturing and reboot')
    else:
      self._intel_psr_tool.StartPSREventLog()
