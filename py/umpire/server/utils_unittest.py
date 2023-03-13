#!/usr/bin/env python3
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import errno
import unittest
from unittest import mock

from cros.factory.umpire.server import utils


class CreateLoopDeviceTest(unittest.TestCase):
  @mock.patch('os.mknod', return_value=True)
  @mock.patch('os.chown', return_value=True)
  @mock.patch('os.path.exists', return_value=False)
  @mock.patch('cros.factory.umpire.server.utils._GetLoopDeviceStat',
              return_value=utils.DEFAULT_LOOP_DEVICE_STAT)
  @mock.patch('os.makedev', return_value=True)
  def testCreateLoopDeviceSuccess(self, mocked_makedev, *unused_mocked_funcs):
    loop_path_prefix = '/dev/loop'
    start = 0
    end = 256
    self.assertTrue(utils.CreateLoopDevice(loop_path_prefix, start, end))
    self.assertEqual(mocked_makedev.call_args_list, [
        mock.call(utils.DEFAULT_LOOP_DEVICE_STAT.major_number, i)
        for i in range(start, end)
    ])

  @mock.patch('os.makedev', return_value=True)
  @mock.patch('os.mknod', return_value=True)
  @mock.patch('os.chown', side_effect=OSError(errno.ENOENT, 'No such file'))
  @mock.patch('os.path.exists', return_value=False)
  @mock.patch('cros.factory.umpire.server.utils._GetLoopDeviceStat',
              return_value=utils.DEFAULT_LOOP_DEVICE_STAT)
  def testCreateLoopDeviceRaiseException(self, *unused_mocked_funcs):
    self.assertFalse(utils.CreateLoopDevice('/dev/loop', 0, 256))


if __name__ == '__main__':
  unittest.main()
