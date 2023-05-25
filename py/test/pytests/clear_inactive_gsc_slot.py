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

import functools
import logging

from cros.factory.device import device_utils
from cros.factory.gooftool import common as gooftool_common
from cros.factory.gooftool import gsctool
from cros.factory.test import test_case


class ClearInactiveGscSlot(test_case.TestCase):

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    dut_shell = functools.partial(gooftool_common.Shell, sys_interface=self.dut)
    self.gsctool = gsctool.GSCTool(dut_shell)

  def runTest(self):
    logging.info('Clearing inactive GSC slot ...')
    self.gsctool.ClearInactiveGSCSlot()
