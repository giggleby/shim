# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test to initiate and verify memory re-training process.

Description
-----------
The test either requests memory re-training on next boot (if ``mode`` is
``'create'``), or verifies the MRC cache. (if ``mode`` is ``'verify_update'``
or ``'verify_no_update'``).

Please refer to py/tools/mrc_cache.py for more details.

Test Procedure
--------------
This is an automated test without user interaction.

Dependency
----------
``flashrom``

Examples
--------
To run the complete memory training and verification flow described in
py/tools/mrc_cache.py, add this to test list::

  {
    "label": "i18n! MRC Cache",
    "subtests": [
      {
        "pytest_name": "mrc_cache",
        "label": "i18n! Create Cache",
        "args": {
          "mode": "create"
        }
      },
      "RebootStep",
      {
        "pytest_name": "mrc_cache",
        "label": "i18n! Verify Cache Update",
        "args": {
          "mode": "verify_update"
        }
      },
      "RebootStep",
      {
        "pytest_name": "mrc_cache",
        "label": "i18n! Verify Cache No Update",
        "args": {
          "mode": "verify_no_update"
        }
      }
    ]
  }
"""

import enum
import unittest

from cros.factory.device import device_utils
from cros.factory.tools import mrc_cache
from cros.factory.utils.arg_utils import Arg


class TestMode(str, enum.Enum):
  create = 'create'
  verify_update = 'verify_update'
  verify_no_update = 'verify_no_update'

class MrcCacheTest(unittest.TestCase):
  ARGS = [
      Arg(
          'mode', str, 'Specify the phase of the test, valid values are:\n'
          '- "create": erase MRC cache and request memory retraining on the'
          ' next boot.\n'
          '- "verify_update": verify the MRC cache update result and request'
          ' memory retraining on next boot.\n'
          '- "verify_no_update": verify the MRC cache is not updated.\n')
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def runTest(self):
    mode = self.args.mode
    valid_mode = [m.value for m in TestMode]
    if mode not in valid_mode:
      raise KeyError(f'Mode {mode} is not valid. '
                     f'Valid modes: {valid_mode}')

    mode = TestMode(mode)
    if mode == TestMode.create:
      mrc_cache.EraseTrainingData(self.dut)
      mrc_cache.SetRecoveryRequest(self.dut)
      mrc_cache.CacheEventLog(self.dut)
    elif mode == TestMode.verify_update:
      mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.Success)
      # Though `verify_update` requests memory retraining, coreboot won't
      # retrain the memory if the cache is valid.
      mrc_cache.SetRecoveryRequest(self.dut)
      mrc_cache.CacheEventLog(self.dut)
    elif mode == TestMode.verify_no_update:
      mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.NoUpdate)
      mrc_cache.ClearEventlogCache()
