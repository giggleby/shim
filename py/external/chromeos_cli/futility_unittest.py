#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import textwrap
import unittest
from unittest import mock

from cros.factory.external.chromeos_cli import futility
from cros.factory.external.chromeos_cli import shell


class FutilityTest(unittest.TestCase):

  def setUp(self):
    self.futility = futility.Futility()
    self.shell = mock.Mock(spec=shell.Shell)
    self.futility._shell = self.shell  # pylint: disable=protected-access

  def testGetFlashSize(self):
    self._SetFutilityUtilityResult(
        stdout=textwrap.dedent("""
        ignored messages
        16777216
        """))
    flash_size = self.futility.GetFlashSize()
    self._CheckCalledCommand(['flashrom', '--flash-size'])
    self.assertEqual(flash_size, 16777216)

  def testGetFlashSizeError(self):
    self._SetFutilityUtilityResult(stdout='unknown messages')
    self.assertRaises(futility.FlashromError, self.futility.GetFlashSize)

  def testGetWriteProtectInfo(self):
    self._SetFutilityUtilityResult(
        stdout=textwrap.dedent("""
        ignored messages
        Expected WP SR configuration by FW image:(start = 0x00800000, length = 0x00700000)
        """))
    wp_conf = self.futility.GetWriteProtectInfo()
    self._CheckCalledCommand(['futility', 'flash', '--flash-info'])
    self.assertEqual(wp_conf['start'], '0x00800000')
    self.assertEqual(wp_conf['length'], '0x00700000')

  def testGetWriteProtectInfoError(self):
    self._SetFutilityUtilityResult(stdout='unknown messages')
    self.assertRaises(futility.FutilityError, self.futility.GetWriteProtectInfo)

  def _SetFutilityUtilityResult(self, stdout='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr='')

  def _CheckCalledCommand(self, cmd):
    self.assertEqual(self.shell.call_args[0][0], cmd)


if __name__ == '__main__':
  unittest.main()
