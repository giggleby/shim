#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.external.chromeos_cli import cros_config
from cros.factory.external.chromeos_cli import shell


class CrosConfigTest(unittest.TestCase):

  def setUp(self):
    self.cros_config = cros_config.CrosConfig()
    self.shell = mock.Mock(spec=shell.Shell)
    self.cros_config._shell = self.shell  # pylint: disable=protected-access

  def _SetShellResult(self, stdout='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr='')

  def testShimlessRmaCheck(self):
    self._SetShellResult('true')
    self.assertTrue(self.cros_config.GetShimlessEnabledStatus())

    self._SetShellResult(' true')
    self.assertTrue(self.cros_config.GetShimlessEnabledStatus())

    self._SetShellResult('True')
    self.assertFalse(self.cros_config.GetShimlessEnabledStatus())

    self._SetShellResult('false')
    self.assertFalse(self.cros_config.GetShimlessEnabledStatus())

    self._SetShellResult('', 1)
    self.assertFalse(self.cros_config.GetShimlessEnabledStatus())

    self.shell.assert_called_with(['cros_config', '/rmad', 'enabled'])


if __name__ == '__main__':
  unittest.main()
