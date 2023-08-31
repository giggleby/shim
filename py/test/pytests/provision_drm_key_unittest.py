#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
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


class MockProxy:

  def Request(self, device_serial, soc_serial, soc_id):
    del device_serial, soc_serial, soc_id  # unused
    # The keybox encrypted with the transport key has 128 bytes.
    return '0a' * 128


def GetGoodDeviceData(key, throw_if_none=True):
  del throw_if_none  # unused

  _DEVICE_DATA = {
      'factory.widevine_device_id': 'WidevineTestOnlyKeybox000',
      'factory.widevine_key': 'e4ff574c322ef53426212cb3ed37f35e',
      'factory.widevine_id':
          '0000000200001ee8ca1e717cfbe8a394520a6b7137d269fa5ac6b54c6b46639bbe80'
          '3dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4314113d0d52da05b209aed'
          '515d13d6',
      'factory.widevine_magic': '6b626f78',
      'factory.widevine_crc': '39f294a7',
  }
  return _DEVICE_DATA[key]


def GetBadDeviceData(unused_key, throw_if_none=True):
  del unused_key, throw_if_none  # unused
  return ''


class ProvisionDRMKeyTest(unittest.TestCase):

  def setUp(self):
    self.test = provision_drm_key.ProvisionDRMKey()
    self.test.dut = mock.Mock()
    mock_oemcrypto = mock.Mock()
    mock_oemcrypto.GetFactoryTransportKeyMaterial.return_value = (16, '7f' * 32)
    mock_oemcrypto.WrapFactoryKeybox.return_value = '7f' * 176
    self.test.oemcrypto_client = mock_oemcrypto
    self.test.args = object()
    patcher = mock.patch(
        'cros.factory.test.utils.oemcrypto_utils.OEMCryptoClient')
    patcher.start()

  @mock.patch('cros.factory.test.device_data.GetDeviceData')
  def testGetKeyboxFromDeviceDataNormal(self, mock_get_device_data):
    mock_get_device_data.side_effect = GetGoodDeviceData

    keybox = self.test.GetKeyboxFromDeviceData()

    self.assertEqual(
        keybox,
        '5769646576696e65546573744f6e6c794b6579626f7830303000000000000000e4ff57'
        '4c322ef53426212cb3ed37f35e0000000200001ee8ca1e717cfbe8a394520a6b7137d2'
        '69fa5ac6b54c6b46639bbe803dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4'
        '314113d0d52da05b209aed515d13d66b626f7839f294a7')

  @mock.patch('cros.factory.test.device_data.GetDeviceData')
  def testGetKeyboxFromDeviceDataInvalid(self, mock_get_device_data):
    mock_get_device_data.side_effect = GetBadDeviceData

    with self.assertRaisesRegex(Exception, 'CRC verification failed'):
      self.test.GetKeyboxFromDeviceData()

  @mock.patch(
      provision_drm_key.__name__ + '.ProvisionDRMKey.GetKeyboxFromDeviceData')
  def testRunTestFromDeviceData(self, mock_get_keybox):
    mock_get_keybox.return_value = '0a' * 128

    self.test.runTest()

    self.test.oemcrypto_client.WrapFactoryKeybox.assert_called_with(
        '115709591f9ba24e655619e1748a287897b6ec5d0ff87201633a176a4f35a2bf8c9c16'
        '666a78d74a69144fba04258cad4c9def6c55fbde6eaaafc56043dc95076a53e3018ea7'
        '701450f137d296d09422718d941971e4d39cb7cc33d557631da8d26b5eac60782ca778'
        'a748505eabeb85d57cad0d2a2980bd76a5e3105a19f09f')
    # 'df9c1a9e' is the CRC32 sum of b'\x7f' * 176 in hex.
    self.test.dut.vpd.ro.Update.assert_called_with(
        {'widevine_keybox': '7f' * 176 + 'df9c1a9e'})
    mock_get_keybox.assert_called_once()


if __name__ == '__main__':
  unittest.main()
