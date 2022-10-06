# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to check the correctness of widevine keybox.

Description
-----------
To verify if the keybox is written by provision_drm_key.py.

Test Procedure
--------------
1. Read keybox from vpd.
2. Calculate the checksum of the keybox.
3. Compare the calculated checksum with the current checksum.

Dependency
----------
This test relies on ``vpd`` component in Device API to access VPD.

Examples
--------
To verify the keybox, add this to test list::

  {
    "pytest_name": "verify_keybox",
  }

"""

import logging
import zlib

from cros.factory.device import device_utils
from cros.factory.test import test_case


class VerifyKeybox(test_case.TestCase):

  def runTest(self):
    dut = device_utils.CreateDUTInterface()
    wrapped_keybox = dut.vpd.ro.get('widevine_keybox')
    logging.info('Read keybox: %s', wrapped_keybox)

    checksum = format(zlib.crc32(bytes.fromhex(wrapped_keybox[:-8])), '08x')
    self.assertEqual(wrapped_keybox[-8:], checksum)
