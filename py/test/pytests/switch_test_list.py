# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A step to switch test list.

Description
-----------
Switching test list automatically to support different factory process.
ref: go/factory-smt-flow

Test Procedure
--------------
1. Switch to the given test list id.

Dependency
----------
None

Examples
--------
To switch to RMA test list, add this to test list::

  {
    "pytest_name": "switch_test_list",
    "args": {
      "test_list_id": "generic_rma"
    }
  }
"""

from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class SwtichTestListTest(test_case.TestCase):
  ARGS = [
      Arg('test_list_id', str, 'An id of a test list needed to be switched.'),
  ]

  def setUp(self):
    self.goofy = state.GetInstance()

  def runTest(self):
    self.goofy.SwitchTestList(self.args.test_list_id)
