#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.pytests import provision_drm_key


class FakeArgs:

  def __init__(self, ip, port):
    self.proxy_server_ip = ip
    self.proxy_server_port = port


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


class MockDevice:

  def __init__(self):
    self.info = mock.Mock()
    self.info.serial_number = 'SN000000'
    self.vpd = mock.Mock()


class ProvisionDRMKeyTest(unittest.TestCase):

  def setUp(self):
    self.test = provision_drm_key.ProvisionDRMKey()
    self.test.dut = MockDevice()
    self.test.oemcrypto_client = MockOEMCryptoClient()

  @mock.patch('cros.factory.test.utils.oemcrypto_utils.OEMCryptoClient')
  @mock.patch('xmlrpc.client.ServerProxy')
  def testSetUpWithURLArgs(self, mock_proxy, mock_oemcrypto_client):
    del mock_oemcrypto_client  # unused

    self.test.args = FakeArgs('123.45.67.89', 3456)
    self.test.setUp()

    mock_proxy.assert_called_with('http://123.45.67.89:3456')

  @mock.patch('cros.factory.test.utils.oemcrypto_utils.OEMCryptoClient')
  @mock.patch('cros.factory.test.server_proxy.GetServerURL')
  @mock.patch('xmlrpc.client.ServerProxy')
  def testSetUpWithoutURLArgs(self, mock_proxy, mock_get_url,
                              mock_oemcrypto_client):
    del mock_oemcrypto_client  # unused
    mock_get_url.return_value = 'http://102.30.40.50:8080'

    self.test.args = FakeArgs(None, None)
    self.test.setUp()

    mock_proxy.assert_called_with('http://102.30.40.50:8089')

  @mock.patch('logging.exception')
  @mock.patch('cros.factory.test.utils.oemcrypto_utils.OEMCryptoClient')
  @mock.patch('cros.factory.test.server_proxy.GetServerURL')
  def testSetUpInvalidServerURL(self, mock_get_url, mock_oemcrypto_client,
                                mock_logging_exception):
    del mock_oemcrypto_client  # unused
    mock_get_url.return_value = ''

    self.test.args = FakeArgs(None, None)
    with self.assertRaises(TypeError):
      self.test.setUp()

    mock_logging_exception.assert_called_once()

  def testSetUpMissingServerIP(self):
    self.test.args = FakeArgs(None, 3456)
    with self.assertRaises(ValueError):
      self.test.setUp()

  def testSetUpMissingServerPort(self):
    self.test.args = FakeArgs('123.45.67.89', None)
    with self.assertRaises(ValueError):
      self.test.setUp()

  def testRunTest(self):
    self.test.dkps_proxy = MockProxy()

    self.test.runTest()

    # 'df9c1a9e` is the CRC32 sum of b'\x7f' * 176 in hex.
    self.test.dut.vpd.ro.Update.assert_called_with(
        {'widevine_keybox': '7f' * 176 + 'df9c1a9e'})


if __name__ == '__main__':
  unittest.main()
