#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest
from unittest.mock import patch

from cros.factory.probe.functions import generic_fingerprint


_BOARD_NAME = 'dartmonkey'
_RO_VERSION = 'v2.0.2887-311310808-RO'
_RW_VERSION = 'v2.0.7304-441100b93-RW'
_RW_ALT_VERSION = 'v2.0.10543-eecc13818-RW'
_FIRMWARE = f'{_BOARD_NAME}_{_RO_VERSION}_{_RW_VERSION}.bin'
_FIRMWARE_ALT = f'{_BOARD_NAME}_{_RO_VERSION}_{_RW_ALT_VERSION}.bin'

_FIRMWARE_DIR = generic_fingerprint._FIRMWARE_DIR  # pylint: disable=protected-access
_RELEASE_FIRMWARE_DIR = os.path.join('/tmp/mount.2kq', _FIRMWARE_DIR)
_FIRMWARE_PATH = os.path.join(_RELEASE_FIRMWARE_DIR, _FIRMWARE)
_FIRMWARE_ALT_PATH = os.path.join(_RELEASE_FIRMWARE_DIR, _FIRMWARE_ALT)


class GetReferenceFirmwareUnitTest(unittest.TestCase):

  @patch('glob.glob')
  def testOneMatched(self, mock_glob):
    mock_glob.return_value = [_FIRMWARE_PATH]
    reference_firmware = generic_fingerprint.GetReferenceFirmware(
        _RELEASE_FIRMWARE_DIR, _BOARD_NAME)
    self.assertEqual(reference_firmware, _FIRMWARE_PATH)

  @patch('glob.glob')
  def testNoFirmwareMatched(self, mock_glob):
    mock_glob.return_value = []
    with self.assertRaises(generic_fingerprint.ReferenceFirmwareError):
      generic_fingerprint.GetReferenceFirmware(_RELEASE_FIRMWARE_DIR,
                                               _BOARD_NAME)

  @patch('glob.glob')
  def testMultipleFirmwaresMatched(self, mock_glob):
    mock_glob.return_value = [_FIRMWARE_PATH, _FIRMWARE_ALT_PATH]
    with self.assertRaises(generic_fingerprint.ReferenceFirmwareError):
      generic_fingerprint.GetReferenceFirmware(_RELEASE_FIRMWARE_DIR,
                                               _BOARD_NAME)


if __name__ == '__main__':
  unittest.main()
