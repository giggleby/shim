#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.gooftool import write_protect_target


class WriteProtectTargetUnittest(unittest.TestCase):

  def testCreateAvailableTargets(self):
    for target in write_protect_target.WriteProtectTargetType:
      if target.name != 'FPMCU':
        write_protect_target.CreateWriteProtectTarget(target)

  @mock.patch('cros.factory.gooftool.write_protect_target.Shell')
  def testCreateBloonchipperWriteProtectTarget(self, mock_shell):
    mock_shell.return_value.stdout = 'bloonchipper'
    target = write_protect_target.CreateWriteProtectTarget(
        write_protect_target.WriteProtectTargetType.FPMCU)
    self.assertIsInstance(target,
                          write_protect_target.BloonchipperWriteProtectTarget)

  @mock.patch('cros.factory.gooftool.write_protect_target.Shell')
  def testCreateDartmonkeyWriteProtectTarget(self, mock_shell):
    mock_shell.return_value.stdout = 'dartmonkey'
    target = write_protect_target.CreateWriteProtectTarget(
        write_protect_target.WriteProtectTargetType.FPMCU)
    self.assertIsInstance(target,
                          write_protect_target.DartmonkeyWriteProtectTarget)

  def testCreateTargetWithWrongType(self):
    with self.assertRaises(TypeError):
      write_protect_target.CreateWriteProtectTarget('random_value')

  @mock.patch('cros.factory.gooftool.write_protect_target.Shell')
  def testUnimplmentedFPMCUTarget(self, mock_shell):
    mock_shell.return_value.stdout = 'unimplemented'
    with self.assertRaises(ValueError):
      write_protect_target.CreateWriteProtectTarget(
          write_protect_target.WriteProtectTargetType.FPMCU)


if __name__ == '__main__':
  unittest.main()
