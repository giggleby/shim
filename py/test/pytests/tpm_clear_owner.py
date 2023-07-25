# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Requests that the firmware clear the TPM owner on the next reboot.

Description
-----------

It's required that the owner is cleared on the first boot out of factory.

Users want to minimize the number of reboot in GRT so we don't put this in GRT.

If a user forgets to clear the owner before :doc:`Finalize <finalize>` then the
Finalize will fail at the VerifyTPM.

This should generally be followed by a reboot step.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

Dependency
----------
- ``crossystem clear_tpm_owner_request``
- ``crossystem clear_tpm_owner_done``

Examples
--------
An example::

  {
    "pytest_name": "tpm_clear_owner"
  }
"""

import unittest

from cros.factory.test import test_tags
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils


class ClearTPMOwnerRequest(unittest.TestCase):
  related_components = (test_tags.TestCategory.TPM, )
  ARGS = [
      Arg('only_check_clear_done', bool, 'Only check crossystem '
          'clear_tpm_owner_done=1', default=False)]

  def runTest(self):
    if self.args.only_check_clear_done:
      self.assertEqual(
          process_utils.CheckOutput(['crossystem', 'clear_tpm_owner_done']),
          '1')
    else:
      process_utils.Spawn(['crossystem', 'clear_tpm_owner_request=1'],
                          check_call=True)
