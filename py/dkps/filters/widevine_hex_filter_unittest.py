#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

import os

from cros.factory.dkps.filters import widevine_hex_filter

try:
  # pylint: disable=import-error
  import crcmod
except Exception:
  crcmod = None

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

CORRECT_CRC_KEYBOXES = ['5769646576696e65546573744f6e6c794b6579626f7830303000000000000000e4ff574c322ef53426212cb3ed37f35e0000000200001ee8ca1e717cfbe8a394520a6b7137d269fa5ac6b54c6b46639bbe803dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4314113d0d52da05b209aed515d13d66b626f7839f294a7']  # pylint: disable=line-too-long

WRONG_CRC_KEYBOXES = ['58595a4244313233343830384b564a483030383332340000000000000000000076871bcafd8333332cf040c03c5421ca0db0958013e7636212e389638759264916a6b63c3e271c2115f30b3496857de0c893e84dd712f6b944216afd271384761d7ddcf045b7827636212e389638754720835e583c0a64d46b626f783ed12b9d', '58595a5f4244313233345f3830384b564a48303038333235000000000000000087123bcafd8333332cf040c03c5421dbaa80801ace39b4cef6d527364ed9ce79c0fa38d41871c7b81dc399dc0c7885a4a8eaf82a6973808ea694cef6d527364ed9c5c0926370325e30a368b8e07d2384b724812e754638926b626f783ed12b9d']  # pylint: disable=line-too-long

SHORT_KEYBOXES = ['deadbeef']


class WidevineParserTest(unittest.TestCase):

  def testFilter(self):
    mock_keybox_list = (
        CORRECT_CRC_KEYBOXES + WRONG_CRC_KEYBOXES + SHORT_KEYBOXES)

    # TODO(treapking): This makes the unit test work in chroot. Remove this if
    # we can run unit test in container.
    if crcmod:
      filtered_list = widevine_hex_filter.Filter(mock_keybox_list)
    else:
      with mock.patch(widevine_hex_filter.__name__ + '.ComputeCRC',
                      return_value='39f294a7'):
        filtered_list = widevine_hex_filter.Filter(mock_keybox_list)

    self.assertEqual(filtered_list, CORRECT_CRC_KEYBOXES)


if __name__ == '__main__':
  unittest.main()
