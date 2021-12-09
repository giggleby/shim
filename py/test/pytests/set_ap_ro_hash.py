# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to set/clear AP RO hash.

Description
-----------
Currently we can't make ap_ro_verification.py run automatically, and the whole
AP RO verification test takes much time. To minimize waiting time of operator,
we split the automatic part into this file.

Test Procedure
--------------
These steps describe the whole procedure of AP RO verification test.
1. Set RO hash to be verified.
2. Verify RO hash by ap_ro_verification.py.
3. Clear RO Hash after verifying.

Dependency
----------
- The test will set RO hash, which needs board id not being set on DUT.

Examples
--------
To set AP RO hash, add this to test list::

  {
    "pytest_name": "set_ap_ro_hash",
  }

"""

import logging

from cros.factory.gooftool.core import Gooftool
from cros.factory.test import test_case


class APROHashTest(test_case.TestCase):

  def setUp(self):
    self.gooftool = Gooftool()
    if self.gooftool.IsCr50BoardIDSet():
      raise Exception('Please run this test without setting board id.')

  def runTest(self):
    logging.info('Setting RO hash.')
    self.gooftool.Cr50SetROHash()
    logging.info('Finish setting RO hash.')
