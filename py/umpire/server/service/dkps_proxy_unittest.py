#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.umpire.server.service import dkps_proxy


class MockEnv:

  def __init__(self):
    self.umpire_data_dir = '/cros_docker/umpire/<project>/umpire_data/'
    self.server_toolkit_dir = '/usr/local/factory'
    self.umpire_dkps_port = 8089
    self.log_dir = '/cros_docker/umpire/<project>/log/'


class DKPSProxyServiceTest(unittest.TestCase):

  def setUp(self):
    TEST_UMPIRE_CONFIG = {
        'services': {
            'dkps': {
                'active': False
            },
            'dkps_proxy': {
                'active': True,
                'server_ip': '123.45.67.89',
                'server_port': '5438'
            }
        }
    }
    self.env = MockEnv()
    self.umpire_config = TEST_UMPIRE_CONFIG
    self.service = dkps_proxy.DKPSProxyService()

  @mock.patch('os.makedirs')
  @mock.patch('os.path.isfile', return_value=False)
  def testCreateProcessNormal(self, mock_is_passphare_file_exist,
                              mock_makedirs):
    del mock_is_passphare_file_exist  # unused

    procs = self.service.CreateProcesses(self.umpire_config, self.env)

    mock_makedirs.assert_called_with(
        '/cros_docker/umpire/<project>/umpire_data/dkps_proxy')

    expected_config = {
        'executable': '/usr/local/factory/bin/factory_env',
        'name': 'dkps_proxy',
        'args': [
            '/usr/local/factory/py/dkps/proxy.py', '--server_ip',
            '123.45.67.89', '--server_port', '5438', '--server_key_file_path',
            'server.pub', '--client_key_file_path', 'requester.key', '--port',
            '8089', '--log_file_path',
            '/cros_docker/umpire/<project>/log/dkps_proxy.log'
        ],
        'path': '/cros_docker/umpire/<project>/umpire_data/dkps_proxy'
    }
    self.assertEqual(len(procs), 1)
    for key, value in expected_config.items():
      self.assertEqual(procs[0].config[key], value)

  @mock.patch('os.makedirs')
  @mock.patch('os.path.isfile', return_value=True)
  def testCreateProcessHasPassphrase(self, mock_is_passphare_file_exist,
                                     mock_makedirs):
    del mock_is_passphare_file_exist  # unused
    del mock_makedirs  # unused

    procs = self.service.CreateProcesses(self.umpire_config, self.env)

    args_config = procs[0].config['args']
    self.assertTrue(('--passphrase',
                     'passphrase') in zip(args_config, args_config[1:]))

  def testInvalidIP(self):
    self.umpire_config['services']['dkps_proxy']['server_ip'] = '1271.0.0.1'

    with self.assertRaisesRegex(RuntimeError, 'invalid ip string'):
      self.service.CreateProcesses(self.umpire_config, self.env)

  def testDKPSActive(self):
    self.service.CreateProcesses(self.umpire_config, self.env)

    self.umpire_config['services']['dkps']['active'] = True

    with self.assertRaisesRegex(
        RuntimeError, 'DKPS and its proxy should not run on the same machine.'):
      self.service.CreateProcesses(self.umpire_config, self.env)

  def testEmptyArgument(self):
    self.umpire_config['services']['dkps_proxy'].pop('server_ip')
    self.umpire_config['services']['dkps_proxy'].pop('server_port')

    with self.assertRaisesRegex(
        ValueError, 'service_ip and service_port are required arguments.'):
      self.service.CreateProcesses(self.umpire_config, self.env)


if __name__ == '__main__':
  unittest.main()
