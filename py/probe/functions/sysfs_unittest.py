#!/usr/bin/env python3
# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil
import tempfile
import unittest

from cros.factory.probe.functions import sysfs
from cros.factory.utils import file_utils


class SysfsFunctionTest(unittest.TestCase):
  def setUp(self):
    self.tmp_dir = tempfile.mkdtemp()

  def tearDown(self):
    if os.path.isdir(self.tmp_dir):
      shutil.rmtree(self.tmp_dir)

  def testNormal(self):
    file_utils.WriteFile(os.path.join(self.tmp_dir, 'vendor'), 'google\n')
    file_utils.WriteFile(os.path.join(self.tmp_dir, 'device'), 'chromebook\n')

    func = sysfs.SysfsFunction(dir_path=self.tmp_dir, keys=['vendor', 'device'])
    result = func()
    self.assertEqual(result, [{'vendor': 'google', 'device': 'chromebook'}])

  def testOptionalKeys(self):
    file_utils.WriteFile(os.path.join(self.tmp_dir, 'device'), 'chromebook\n')
    file_utils.WriteFile(
        os.path.join(self.tmp_dir, 'optional_1'), 'OPTIONAL_1\n')

    func = sysfs.SysfsFunction(
        dir_path=self.tmp_dir, keys=['device'],
        optional_keys=['optional_1', 'optional_2'])
    result = func()
    self.assertEqual(result, [{'device': 'chromebook',
                               'optional_1': 'OPTIONAL_1'}])

  def testFail(self):
    """Device is not found."""
    file_utils.WriteFile(os.path.join(self.tmp_dir, 'vendor'), 'google\n')

    func = sysfs.SysfsFunction(dir_path=self.tmp_dir, keys=['vendor', 'device'])
    result = func()
    self.assertEqual(result, [])

  def testMultipleResults(self):
    os.mkdir(os.path.join(self.tmp_dir, 'foo'))
    file_utils.WriteFile(
        os.path.join(self.tmp_dir, 'foo', 'vendor'), 'google\n')
    file_utils.WriteFile(
        os.path.join(self.tmp_dir, 'foo', 'device'), 'chromebook\n')
    os.mkdir(os.path.join(self.tmp_dir, 'bar'))
    file_utils.WriteFile(os.path.join(self.tmp_dir, 'bar', 'vendor'), 'apple\n')
    file_utils.WriteFile(
        os.path.join(self.tmp_dir, 'bar', 'device'), 'macbook\n')

    file_utils.WriteFile(
        os.path.join(self.tmp_dir, 'NOT_DIR'), 'SHOULD NOT BE PROBED.')

    func = sysfs.SysfsFunction(dir_path=os.path.join(self.tmp_dir, '*'),
                               keys=['vendor', 'device'])
    result = func()
    self.assertEqual(sorted(result, key=lambda d: sorted(d.items())),
                     sorted([{'vendor': 'google', 'device': 'chromebook'},
                             {'vendor': 'apple', 'device': 'macbook'}],
                            key=lambda d: sorted(d.items())))


if __name__ == '__main__':
  unittest.main()
