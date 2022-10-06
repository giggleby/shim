#!/usr/bin/env python3
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unit test for Widevine parser module."""

import os
import unittest

from cros.factory.dkps.parsers import widevine_to_json_parser
from cros.factory.utils import file_utils

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

MOCK_WIDEVINE_FILE_PATH = os.path.join(SCRIPT_DIR, 'testdata', 'widevine.xml')

EXPECTED_PARSED_MOCK_WIDEVINE_KEY_LIST = [
    {
        'CRC':
            '39f294a7',
        'DeviceID':
            'WidevineTestOnlyKeybox000',
        'ID':
            '0000000200001ee8ca1e717cfbe8a394520a6b7137d269fa5ac6b54c6b46639bbe803dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4314113d0d52da05b209aed515d13d6',  # pylint: disable=line-too-long
        'Key':
            'e4ff574c322ef53426212cb3ed37f35e',
        'Magic':
            '6b626f78'
    },
    {
        'CRC':
            '3ed12b9d',
        'DeviceID':
            'WidevineTestOnlyKeybox001',
        'ID':
            '0db0958013e7636212e389638759264916a6b63c3e271c2115f30b3496857de0c893e84dd712f6b944216afd271384761d7ddcf045b7827636212e389638754720835e583c0a64d4',  # pylint: disable=line-too-long
        'Key':
            '76871bcafd8333332cf040c03c5421ca',
        'Magic':
            '6b626f78'
    }
]


class WidevineToJSONParserTest(unittest.TestCase):

  def runTest(self):
    self.assertEqual(
        EXPECTED_PARSED_MOCK_WIDEVINE_KEY_LIST,
        widevine_to_json_parser.Parse(
            file_utils.ReadFile(MOCK_WIDEVINE_FILE_PATH)))


if __name__ == '__main__':
  unittest.main()
