# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to set/clear AP RO hash.

Description
-----------
When re-flowing, RO hash can't be modified since board id is set.
We decided to skip this test with the following assumptions: (might hold in
most cases, but not always)
- If board id is set, then DUT must have been finalized.
- AP RO verification is always tested before finalization, and this feature
won't be broken after that.

Test Procedure
--------------
These steps describe the whole procedure of AP RO verification test.
1. Set RO hash to be verified.
2. Verify RO hash by ap_ro_verification.py.
3. Clear RO Hash after verifying.

Dependency
----------
- The test will set/clear RO hash, which needs board id not being set on DUT.

Examples
--------
To set/clear AP RO hash, add this to test list::

  {
    "pytest_name": "ap_ro_hash",
    "args": {
      "action": "set"
    }
  }

  {
    "pytest_name": "ap_ro_hash",
    "args": {
      "action": "clear"
    }
  }

"""

from cros.factory.gooftool.core import Gooftool
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class APROHashTest(test_case.TestCase):
  ARGS = [Arg('action', str, "The action for AP RO hash ('set', 'clear').")]

  def setUp(self):
    self.gooftool = Gooftool()

  def runTest(self):
    if self.gooftool.IsCr50BoardIDSet():
      session.console.warn('Unable to modify RO hash, test skipped.')
      return

    action = self.args.action
    if action == 'set':
      self.gooftool.Cr50SetROHash()
    elif action == 'clear':
      self.gooftool.Cr50ClearRoHash()
    else:
      raise Exception(f'Unknown action: {action}')
