# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to set/clear AP RO hash.

Description
-----------
When re-flowing, RO hash can't be modified since board ID is set.
We decided to skip this test with the following assumptions: (might hold in
most cases, but not always)
- If board ID is set, then DUT must have been finalized.
- AP RO verification is always tested before finalization, and this feature
won't be broken after that.
- Even if the hash is set in cr50, the verification will always fail since
the stored hash is calculated with gbb flags 0, which is not the same as the
gbb flags we use in the factory.

Test Procedure
--------------
These steps describe the whole procedure of AP RO verification test.
1. Set RO hash to be verified.
2. Verify RO hash by ap_ro_verification.py.
3. Clear RO Hash after verifying.

Dependency
----------
- The test will set/clear RO hash, which needs board ID not being set on DUT.

Examples
--------
To set/clear AP RO hash, add this to test list::

  {
    "pytest_name": "cr50_ap_ro_hash",
    "args": {
      "action": "set"
    }
  }

  {
    "pytest_name": "cr50_ap_ro_hash",
    "args": {
      "action": "clear"
    }
  }

"""

from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.test.utils import gsc_utils
from cros.factory.test.utils.gsc_utils import GSCUtils
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.chromeos_cli import gsctool


class Cr50APROHashTest(test_case.TestCase):
  related_components = (test_case.TestCategory.TPM, )
  ARGS = [Arg('action', str, "The action for AP RO hash ('set', 'clear').")]

  def setUp(self):
    self.gsctool = gsctool.GSCTool()
    self.gsc_utils = gsc_utils.GSCUtils()

  def runTest(self):
    # skip the test if the firmware is Ti50
    if GSCUtils().IsTi50():
      session.console.info('Skip Cr50 AP RO hash test '
                           'since the firmware is Ti50.')
      return
    if self.gsctool.IsGSCBoardIdTypeSet():
      session.console.warn('Unable to modify RO hash, test skipped.')
      return

    action = self.args.action
    if action == 'set':
      self.gsc_utils.Cr50SetROHash()
    elif action == 'clear':
      self.gsc_utils.Cr50ClearROHash()
    else:
      raise Exception(f'Unknown action: {action}')
