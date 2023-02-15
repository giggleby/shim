#!/usr/bin/env python3
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An integration test for SSHLink

Manually run this unittest with following command::

  ./bin/factory_env py/device/links/ssh_integration_test.py DUT_IP

You may need to explicitly specify a key to authenticate::

  ./bin/factory_env py/device/links/ssh_integration_test.py \
  DUT_IP -i /path/to/key
"""

import argparse
import logging
import os
import random
import string
import tempfile
from typing import List, Union
import unittest

from cros.factory.device import device_types
from cros.factory.device.links import local
from cros.factory.device.links import ssh
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


dut_options = {}


def _GenerateRandomString() -> str:
  """Generate a random string with length 256."""
  return ''.join(random.choices(string.ascii_letters, k=256))


class SSHLinkIntegrationTest(unittest.TestCase):

  ssh_link: ssh.SSHLink

  @type_utils.Overrides
  def setUp(self):
    self.ssh_link = ssh.SSHLink(**dut_options)

  def _GetOutput(self, link: device_types.DeviceLink,
                 cmd: Union[str, List[str]]) -> str:
    with tempfile.TemporaryFile('w+') as stdout:
      self.assertEqual(link.Shell(cmd, stdout=stdout).wait(), 0)
      stdout.seek(0)
      output = stdout.read()
    return output

  def testListEchoQuote(self):
    cmd = ['echo', '\'']
    local_link = local.LocalLink()
    self.assertEqual(
        self._GetOutput(self.ssh_link, cmd), self._GetOutput(local_link, cmd))

  def testShellEchoQuote(self):
    cmd = 'echo "\'"'
    local_link = local.LocalLink()
    self.assertEqual(
        self._GetOutput(self.ssh_link, cmd), self._GetOutput(local_link, cmd))

  def testShellSemiColon(self):
    cmd = 'echo 123; echo 456; echo 789'
    local_link = local.LocalLink()
    self.assertEqual(
        self._GetOutput(self.ssh_link, cmd), self._GetOutput(local_link, cmd))

  def testListSemiColon(self):
    cmd = ['echo', '123', ';', 'echo', '456', ';', 'echo', '789']
    local_link = local.LocalLink()
    self.assertEqual(
        self._GetOutput(self.ssh_link, cmd), self._GetOutput(local_link, cmd))

  def testCommandFailed(self):
    cmd = '>&2 echo -n error; false'
    with tempfile.TemporaryFile('w+') as stdout, tempfile.TemporaryFile(
        'w+') as stderr:
      proc = self.ssh_link.Shell(cmd, stdout=stdout, stderr=stderr)
      returncode = proc.wait()
      stdout.seek(0)
      stderr.seek(0)
      self.assertEqual(stdout.read(), '')
      self.assertEqual(stderr.read(), 'error')
      self.assertEqual(returncode, 1)

  def testPush(self):
    """Tests that SSHLink can push a file from local to remote."""
    remote_file = '/tmp/test_file'
    test_file_content = _GenerateRandomString()

    with file_utils.UnopenedTemporaryFile() as temp_file:
      file_utils.WriteFile(temp_file, test_file_content)
      self.ssh_link.Push(temp_file, remote_file)

    cmd = f'cat "{remote_file}" && rm "{remote_file}"'
    self.assertEqual(self._GetOutput(self.ssh_link, cmd), test_file_content)

  def testPushDirectory(self):
    """Tests that SSHLink can push a directory from local to remote."""
    remote_dir = '/tmp/test_dir'
    test_file_content = _GenerateRandomString()

    with file_utils.TempDirectory() as temp_dir:
      test_file = file_utils.CreateTemporaryFile(dir=temp_dir)
      file_utils.WriteFile(test_file, test_file_content)
      self.ssh_link.PushDirectory(temp_dir, remote_dir)

    remote_file = os.path.join(remote_dir, os.path.basename(test_file))
    cmd = f'[ -d "{remote_dir}" ] && cat "{remote_file}" && rm -r {remote_dir}'
    self.assertEqual(self._GetOutput(self.ssh_link, cmd), test_file_content)

  def testPull(self):
    """Tests that SSHLink can pull a file from remote to local."""
    test_file_content = _GenerateRandomString()
    self.assertEqual(
        self.ssh_link.Shell(
            f'echo -n "{test_file_content}" > /tmp/content').wait(), 0)

    with file_utils.UnopenedTemporaryFile() as temp_file:
      self.ssh_link.Pull('/tmp/content', temp_file)
      self.assertEqual(file_utils.ReadFile(temp_file), test_file_content)

    # Delete test file on remote.
    self.assertEqual(self.ssh_link.Shell('rm -f /tmp/content').wait(), 0)

  def testPullAndThenRead(self):
    """Tests that SSHLink can read a file on remote."""
    test_file_content = _GenerateRandomString()
    self.assertEqual(
        self.ssh_link.Shell(
            f'echo -n "{test_file_content}" > /tmp/content').wait(), 0)
    self.assertEqual(self.ssh_link.Pull('/tmp/content'), test_file_content)

    # Delete test file on remote.
    self.assertEqual(self.ssh_link.Shell('rm -f /tmp/content').wait(), 0)


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)

  parser = argparse.ArgumentParser(description='Integration test for SSHLink')
  parser.add_argument('host', help='hostname of ssh target')
  parser.add_argument('-i', '--identity', help='path to an identity file')
  parser.add_argument('-u', '--user', help='user name')
  parser.add_argument('-p', '--port', type=int, help='port')
  args = parser.parse_args()
  dut_options.update([x for x in vars(args).items() if x[1] is not None])

  logging.info('dut_options: %s', dut_options)

  suite = unittest.TestLoader().loadTestsFromTestCase(SSHLinkIntegrationTest)
  unittest.TextTestRunner().run(suite)
