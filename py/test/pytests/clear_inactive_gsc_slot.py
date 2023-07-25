# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Clears the inactive GSC RW slot.

Description
-----------
Clears the inactive GSC RW slot to prevent unexpected version rollback.

Test Procedure
--------------
The test clears the inactive GSC slot by running `gsctool -a -c`. No user
interaction is required.

Dependency
----------
gsctool

Examples
--------
To run the test, do::

  {
    "pytest_name": "clear_inactive_gsc_slot"
  }

"""

import logging

from cros.factory.device import device_utils
from cros.factory.test import test_case

from cros.factory.external.chromeos_cli import gsctool


class ClearInactiveGscSlot(test_case.TestCase):

  related_components = (test_case.TestCategory.TPM, )
  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.gsctool = gsctool.GSCTool(dut=self.dut)

  def runTest(self):
    logging.info('Clearing inactive GSC slot ...')
    self.gsctool.ClearInactiveGSCSlot()
