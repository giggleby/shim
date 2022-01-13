#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.pytests import provision_drm_key
from cros.factory.test.pytests.provision_drm_key import GetDeviceSerial


class MockDeviceInfo:

  def __init__(self, serial_number=None, mlb_serial_number=None):
    self.serial_number = serial_number
    self.mlb_serial_number = mlb_serial_number


class GetDeviceSerialTest(unittest.TestCase):

  def testUseMLBSerialNumber(self):
    device_info = MockDeviceInfo(serial_number='will_be_ignored',
                                 mlb_serial_number='MLB_SN4321')

    self.assertEqual(GetDeviceSerial(device_info), 'MLB_SN4321')

  def testUseSerialNumber(self):
    device_info = MockDeviceInfo(serial_number='SN5678', mlb_serial_number=None)

    self.assertEqual(GetDeviceSerial(device_info), 'SN5678')

  def testUseUUID(self):
    device_info = MockDeviceInfo(serial_number=None, mlb_serial_number=None)

    device_serial = GetDeviceSerial(device_info)

    self.assertIsInstance(device_serial, str)
    self.assertEqual(len(device_serial), 32)
    self.assertTrue(device_serial.isalnum())


class FakeArgs:

  def __init__(self, url_spec=None):
    self.proxy_server_url = url_spec


class MockProxy:

  def Request(self, device_serial, soc_serial, soc_id):
    del device_serial, soc_serial, soc_id  # unused
    # The keybox encrypted with the transport key has 128 bytes.
    return '0a' * 128


class MockOEMCryptoClient:

  def GetFactoryTransportKeyMaterial(self):
    return 16, '7f' * 32

  def WrapFactoryKeybox(self, encrypted_keybox):
    del encrypted_keybox  # unused
    # Re-encrypted keybox will have 176 bytes.
    return '7f' * 176


class ProvisionDRMKeyTest(unittest.TestCase):

  def setUp(self):
    self.test = provision_drm_key.ProvisionDRMKey()
    self.test.dut = mock.Mock()
    self.test.oemcrypto_client = MockOEMCryptoClient()
    self.test.args = FakeArgs()
    patcher = mock.patch(
        'cros.factory.test.utils.oemcrypto_utils.OEMCryptoClient')
    patcher.start()

  @mock.patch('cros.factory.test.utils.url_spec.URLSpec.FindServerURL')
  @mock.patch('xmlrpc.client.ServerProxy')
  def testConnectToServer(self, mock_proxy, mock_find_url):
    mock_find_url.return_value = 'http://123.45.67.89:3456'

    self.test.setUp()

    mock_proxy.assert_called_with('http://123.45.67.89:3456')

  @mock.patch('cros.factory.test.utils.url_spec.URLSpec.FindServerURL')
  def testUrlNotFound(self, mock_find_url):
    mock_find_url.side_effect = mock.Mock(side_effect=ValueError())

    self.assertRaisesRegex(ValueError,
                           'Server Url not found, please check arguments.',
                           self.test.setUp)

  def testRunTest(self):
    self.test.dkps_proxy = MockProxy()

    self.test.runTest()

    # 'df9c1a9e` is the CRC32 sum of b'\x7f' * 176 in hex.
    self.test.dut.vpd.ro.Update.assert_called_with(
        {'widevine_keybox': '7f' * 176 + 'df9c1a9e'})


if __name__ == '__main__':
  unittest.main()
