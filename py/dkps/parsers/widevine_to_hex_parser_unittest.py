#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest

from cros.factory.dkps.parsers import widevine_to_hex_parser

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

MOCK_WIDEVINE_FILE_PATH = os.path.join(SCRIPT_DIR, 'testdata', 'widevine.xml')

# The first expected keybox is the concatenation of the following strings:
# - DeviceID (b'WidevineTestOnlyKeybox000') padded to 32 bytes in hex format:
#     '5769646576696e65546573744f6e6c794b6579626f7830303000000000000000'
# - Key:
#     'e4ff574c322ef53426212cb3ed37f35e'
# - ID:
#     '0000000200001......2da05b209aed515d13d6'
# - Magic (b'kbox' in hex):
#     '6b626f78'
# - CRC (checksum):
#     '39f294a7'
EXPECTED_PARSED_MOCK_WIDEVINE_KEY_LIST = [
    '5769646576696e65546573744f6e6c794b6579626f7830303000000000000000e4ff574c322ef53426212cb3ed37f35e0000000200001ee8ca1e717cfbe8a394520a6b7137d269fa5ac6b54c6b46639bbe803dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4314113d0d52da05b209aed515d13d66b626f7839f294a7',  # pylint: disable=line-too-long
    '5769646576696e65546573744f6e6c794b6579626f783030310000000000000076871bcafd8333332cf040c03c5421ca0db0958013e7636212e389638759264916a6b63c3e271c2115f30b3496857de0c893e84dd712f6b944216afd271384761d7ddcf045b7827636212e389638754720835e583c0a64d46b626f783ed12b9d'  # pylint: disable=line-too-long
]


class WidevineToHexParserTest(unittest.TestCase):

  def testParse(self):
    with open(MOCK_WIDEVINE_FILE_PATH) as f:
      self.assertEqual(EXPECTED_PARSED_MOCK_WIDEVINE_KEY_LIST,
                       widevine_to_hex_parser.Parse(f.read()))


if __name__ == '__main__':
  unittest.main()
