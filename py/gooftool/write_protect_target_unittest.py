#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.gooftool import write_protect_target


class WriteProtectTargetUnittest(unittest.TestCase):

  def testCreateAvailableTargets(self):
    for target in write_protect_target.WriteProtectTargetType:
      write_protect_target.CreateWriteProtectTarget(target)

  def testCreateTargetWithWrongType(self):
    with self.assertRaises(TypeError):
      write_protect_target.CreateWriteProtectTarget('inexistent_type')


if __name__ == '__main__':
  unittest.main()
