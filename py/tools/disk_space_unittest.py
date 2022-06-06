#!/usr/bin/env python3
#
# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import collections
import os
import textwrap
import unittest
from unittest import mock

from cros.factory.tools import disk_space

FakeStatVFSResult = collections.namedtuple(
    'FakeStatVFSResult',
    ['f_bavail', 'f_blocks', 'f_favail', 'f_files'])


class DiskSpaceTest(unittest.TestCase):

  def setUp(self):
    self.stateful_stats = FakeStatVFSResult(f_blocks=261305, f_bavail=60457,
                                            f_files=65536, f_favail=35168)
    self.media_stats = FakeStatVFSResult(f_blocks=497739, f_bavail=497699,
                                         f_files=497739, f_favail=497698)

    mocked_open = mock.mock_open(
        read_data=textwrap.dedent('''\
            /dev/sda1 /mnt/stateful_partition ext4 rw
            /dev/sda1 /home ext4 rw
            /dev/sdb1 /media/usb ext4 rw
            none /root ext4 ro
            tmp /tmp tmpfs rw
            fusectl /sys/fs/fuse/connections fusectl rw
        '''))
    patcher = mock.patch('builtins.open', mocked_open)
    self.patched_open = patcher.start()
    # TODO(b/233844450): Remove this patch after migrating to Python 3.7 with
    # __iter__ implemented in mock.mock_open().
    self.patched_open.return_value.__iter__ = lambda f: iter(f.readline, '')
    self.addCleanup(patcher.stop)

    def StatvfsSideEffect(*args, **unused_kwargs):
      if args[0] == '/mnt/stateful_partition':
        return self.stateful_stats
      if args[0] == '/media/usb':
        return self.media_stats
      return None

    os.statvfs = mock.Mock(side_effect=StatvfsSideEffect)

  def tearDown(self):
    statvfs_calls = [
        mock.call('/mnt/stateful_partition'),
        mock.call('/media/usb')]

    self.patched_open.assert_called_once_with('/etc/mtab', encoding='utf8')
    self.assertEqual(os.statvfs.call_args_list, statvfs_calls)

  def testGetAllVFSInfo(self):
    self.assertEqual(
        {'/dev/sdb1': disk_space.VFSInfo(['/media/usb'], self.media_stats),
         '/dev/sda1': disk_space.VFSInfo(['/home', '/mnt/stateful_partition'],
                                         self.stateful_stats)},
        disk_space.GetAllVFSInfo())

  def testFormatSpaceUsed(self):
    self.assertEqual(
        ('Disk space used (bytes%/inodes%): '
         '[/home /mnt/stateful_partition: 76%/46%] [/media/usb: 0%/0%]'),
        disk_space.FormatSpaceUsedAll(
            disk_space.GetAllVFSInfo()))


if __name__ == '__main__':
  unittest.main()
