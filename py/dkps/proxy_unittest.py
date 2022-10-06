#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The DKPS proxy server test module."""

import json
import os
import unittest
from unittest import mock
import xmlrpc.client

from cros.factory.dkps import helpers
from cros.factory.dkps import proxy as proxy_module
from cros.factory.utils import file_utils
from cros.factory.utils import net_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
# Copied from Widevine website.
FAKE_KEYBOX = '5769646576696e65546573744f6e6c794b6579626f7830303000000000000000e4ff574c322ef53426212cb3ed37f35e0000000200001ee8ca1e717cfbe8a394520a6b7137d269fa5ac6b54c6b46639bbe803dbb4ff74c5f6f550e3d3d9acf81125d52e0478cda0bf4314113d0d52da05b209aed515d13d66b626f7839f294a7'  # pylint: disable=line-too-long

ENCRYPTED_KEYBOX = '091b3f8205cebdbd95f894a11d68a60bc71156b13818baa597e819f83569975249d29be705315b8b09a9042f742b6536f057d1502c21a531db136813001ba902bda0fe15eaea83c2a2d26ac7229f5385ba04f361503c7d302a79d56dc689b9e38156f2d51e740e91a7a3af1097d956bab13bd229e293c075f11fe2e7753e1725'  # pylint: disable=line-too-long


class DKPSProxyTest(unittest.TestCase):

  def setUp(self):
    self.helper = mock.Mock()
    self.helper.Request.return_value = json.dumps(FAKE_KEYBOX)
    self.proxy = proxy_module.DKPSProxy(self.helper)

  def testRequest(self):
    # Request with fake device serial, SoC serial, and SoC model ID.
    encrypted_keybox = self.proxy.Request('SN000000', '7f' * 32, 16)

    self.assertEqual(encrypted_keybox, ENCRYPTED_KEYBOX)

  def testRequestError(self):
    self.helper.Request.side_effect = xmlrpc.client.Fault
    with self.assertRaisesRegex(
        Exception, 'The proxy server failed to request keyboxes from DKPS'):
      self.proxy.Request('SN000000', '7f' * 32, 16)

  def testListenForever(self):
    ip = net_utils.LOCALHOST
    port = net_utils.FindUnusedTCPPort()
    process_utils.StartDaemonThread(target=self.proxy.ListenForever,
                                    args=(ip, port))
    sync_utils.WaitFor(lambda: net_utils.ProbeTCPPort(ip, port), 2)

    rpc_proxy = xmlrpc.client.ServerProxy('http://%s:%d' % (ip, port))

    # Call `Request()` without any argument because we only want to make sure
    # the port is listening.
    with self.assertRaisesRegex(xmlrpc.client.Fault,
                                'missing 3 required positional arguments'):
      rpc_proxy.Request()


class ProxyMainFunctionTest(unittest.TestCase):

  def setUp(self):
    self.mock_dkps_proxy = mock.Mock()
    self.log_path = '/tmp/dkps_proxy.log'
    file_utils.TryUnlink(self.log_path)

  @mock.patch.object(helpers, 'RequesterHelper')
  @mock.patch('cros.factory.dkps.proxy.DKPSProxy')
  def testMain(self, mock_proxy_class, mock_requester_helper):
    mock_requester_helper.return_value = 'DUMMY_HELPER'
    mock_proxy_class.return_value = self.mock_dkps_proxy

    with mock.patch('sys.argv', [
        'proxy.py', '--server_ip', '12.34.56.78', '--server_port', '5438',
        '--server_key_file_path', '/path/to/server_public_key',
        '--client_key_file_path', '/path/to/client_private_key',
        '--passphrase_file_path', '/path/to/passphrase_file', '--ip',
        '123.9.87.65', '--port', '8089', '--log_file_path', self.log_path
    ]):
      proxy_module.main()

    self.assertTrue(os.path.exists(self.log_path))
    mock_requester_helper.assert_called_with(
        '12.34.56.78', 5438, '/path/to/server_public_key',
        '/path/to/client_private_key', '/path/to/passphrase_file')
    mock_proxy_class.assert_called_with('DUMMY_HELPER')
    self.mock_dkps_proxy.ListenForever.assert_called_with('123.9.87.65', 8089)

  def tearDown(self):
    file_utils.TryUnlink(self.log_path)


if __name__ == '__main__':
  unittest.main()
