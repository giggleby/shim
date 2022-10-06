#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The test module for Widevine keybox provisioning utility functions."""

import unittest

from cros.factory.dkps import widevine_utils


class WidevineUtilsTest(unittest.TestCase):

  def testTransportKeyKDF(self):
    FAKE_SOC_SERIAL = '7f' * 32
    FAKE_SOC_ID = 16

    self.assertEqual(
        widevine_utils.TransportKeyKDF(FAKE_SOC_SERIAL, FAKE_SOC_ID),
        b'\xa5\xb2#\xa3>\x1eR\x12\x88\xc3\xfb\xb9\xf7\xa04\xf5')

  def testEncryptKeyboxWithTransportKey(self):
    FAKE_KEYBOX = '0a' * 128
    FAKE_TRANSPORT_KEY = b'\xcf' * 16

    self.assertEqual(
        widevine_utils.EncryptKeyboxWithTransportKey(FAKE_KEYBOX,
                                                     FAKE_TRANSPORT_KEY),
        '31b74d844afd47639a49a7a042d0b5eb4c77d608d9c8cb78b82a666dc277614ba93a3a'
        'b5ce1bd0714d894cd60781c8148f151d0c4a08165a20869dd34184f8ae542533883be3'
        '4bffe1c116edcd8b44fb121d9fb7cccd1059ed278ed5702e7d7668eebaedfd7c1b46ba'
        '1fddf40d074703cd6f593017fe84b677025e5c03ec77dd')

  def testComputeCRC(self):
    # pylint: disable=protected-access
    self.assertEqual(widevine_utils._ComputeCRC('deadbeef'), '81da1a18')

  def testFormatDeviceIDNormal(self):
    device_id = widevine_utils.FormatDeviceID('abcd0000')

    # '6162636430303030' == 'abcd0000'.encode('ascii').hex()
    self.assertEqual(device_id, '6162636430303030' + '00' * 24)

  def testFormatDeviceIDNoPadding(self):
    device_id = widevine_utils.FormatDeviceID(
        '_this_is_a_32_bytes_long_string_')

    self.assertEqual(device_id,
                     '_this_is_a_32_bytes_long_string_'.encode('ascii').hex())

  def testIsValidKeybox(self):
    VALID_KEYBOX = (
        '5769646576696e65546573744f6e6c794b6579626f7830303000000000000000e4ff57'
        '4c322ef53426212cb3ed37f35e0000000200001ee8ca1e717cfbe8a394520a6b7137d2'
        '69fa5ac6b54c6b46639bbe803dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4'
        '314113d0d52da05b209aed515d13d66b626f7839f294a7')
    self.assertTrue(widevine_utils.IsValidKeybox(VALID_KEYBOX))

  def testIsValidKeyboxInvalidChecksum(self):
    self.assertFalse(widevine_utils.IsValidKeybox('0a' * 128))


if __name__ == '__main__':
  unittest.main()
