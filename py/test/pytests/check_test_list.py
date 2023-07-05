# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A step to check test list.

Description
-----------
Check if the test list exists before we use it.
ref: go/factory-smt-flow

Test Procedure
--------------
1. Check if the given test list id exists.

Dependency
----------
None

Examples
--------
To check if RMA test list exists, add this to test list::

  {
    "pytest_name": "check_test_list",
    "args": {
      "test_list_id": "generic_rma"
    }
  }
"""

from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class CheckTestListTest(test_case.TestCase):
  ARGS = [
      Arg('test_list_id', str, 'An id of a test list needed to be checked.'),
  ]

  def setUp(self):
    self.goofy = state.GetInstance()

  def runTest(self):
    test_list_ids = {list["id"]
                     for list in self.goofy.GetTestLists()}

    self.assertIn(self.args.test_list_id, test_list_ids)
