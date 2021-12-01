# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to set/clear AP RO hash.

Description
-----------
Currently we can't make ap_ro_verification.py run automatically, and the whole
AP RO verification test takes much time. To minimize waiting time of operator,
we split the automatic part into this file.

We should keep RO hash clear after test, to avoid the risk of bricking the DUT.

Test Procedure
--------------
These steps describe the whole procedure of AP RO verification test.
1. Set RO hash which to be verified.
2. Verify RO hash by ap_ro_verification.py.
3. Clear RO Hash.

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

"""

import logging

from cros.factory.gooftool.core import Gooftool
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class OperationError(Exception):

  def __init__(self):
    super().__init__('Please retry the test.')


class APROHashTest(test_case.TestCase):
  ARGS = [Arg('action', str, "The action for AP RO hash ('set', 'clear').")]

  def setUp(self):
    self.gooftool = Gooftool()
    if self.gooftool.IsCr50BoardIDSet():
      raise Exception('Please run this test without setting board id.')

  def runTest(self):
    action = self.args.action
    if action == 'set':
      logging.info('Set RO hash.')
      self.gooftool.Cr50SetROHash()
    elif action == 'clear':
      logging.info('Clear RO hash.')
      self.gooftool.Cr50ClearRoHash()
    else:
      raise Exception(f'Unknown action: {action}')
