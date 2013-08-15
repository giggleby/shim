#!/usr/bin/env python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import argparse
import collections
import logging
import os


# Stub for mockability.
_Open = open


VFSInfo = collections.namedtuple('VFSInfo', ['mount_points', 'statvfs'])
DiskUsedPercentage = collections.namedtuple('DiskUsedPercentage',
    ['bytes_used_pct', 'inodes_used_pct'])
def GetAllVFSInfo():
  '''Returns results for statvfs on all filesystems.

  The returned value is a map from device to VFSInfo object.  VFSInfo
  is a named tuple with fields:

     mount_points: List of all mount points for the device.
     statvfs: Result of calling os.statvfs on the device.
  '''
  # Path from each device to the paths it is mounted at
  device_to_path = collections.defaultdict(lambda: [])

  for line in _Open('/etc/mtab'):
    device, path, fs_type = line.split()[0:3]
    if fs_type in [
        'sysfs', 'proc', 'fusectl', 'debugfs', 'rootfs', 'pstore', 'devpts']:
      continue
    device_to_path[device].append(path)

  ret = {}
  for k, v in sorted(device_to_path.items()):
    try:
      ret[k] = VFSInfo(sorted(v), os.statvfs(v[0]))
    except OSError:
      # Oh well; skip this guy
      pass

  return ret


def FormatSpaceUsed(vfs_info):
  '''Formats disk space used for a single filesystem.

  Returns:
    A string like

      /a /b: 87%/17%

    meaning that on the device that /a and /b are mounted from, 87% of bytes
    and 17% of inodes are used (unavailable to unprivileged users).
  '''
  return ' '.join(vfs_info.mount_points) + (': %d%%/%d%%' %
    GetPartitionUsage(vfs_info))


def FormatSpaceUsedAll(vfs_infos):
  '''Formats disk space used by all filesystems in vfs_infos.

  The list is arranged in descending order of space used.

  Args:
    vfs_infos: a map from device to VFSInfo object.

  Returns:
    A string like

      Disk space used (bytes%/inode%): [/a /b: 87%/17%] [/c: 5%/3%]
  '''
  return 'Disk space used (bytes%/inodes%): ' + ' '.join(
      '[' + FormatSpaceUsed(v) + ']'
      for v in sorted(
          vfs_infos.values(),
          key=lambda x: GetUsedPercentage(x.statvfs.f_bavail,
                                          x.statvfs.f_blocks),
          reverse=True))


def GetUsedPercentage(avail, total):
  '''Gets used percentage.

  Returns:
    Used percentage if total is not zero.
    Returns 0.0 if avail == total == 0. This occurs for '/sys/fs/cgroup/cpu' and
    '/sys/fs/cgroup/freezer' whose f_blocks=0L and f_bavail=0L.

  Raises:
    ZeroDivisionError if total == 0 and avail != 0.
  '''
  if avail == total == 0:
    return 0.0
  return (100 - 100.0 * avail / total)


def GetPartitionUsage(vfs_info):
  '''Gets the disk space usage.

  Args:
    vfs_info: a VFSInfo object.

  Returns:
    A DiskUsedPercentage namedtuple like (bytes_used_pct=87,
                                          inodes_used_pct=17).
  '''
  return DiskUsedPercentage(
             GetUsedPercentage(vfs_info.statvfs.f_bavail,
                               vfs_info.statvfs.f_blocks),
             GetUsedPercentage(vfs_info.statvfs.f_favail,
                               vfs_info.statvfs.f_files))

def GetEncyptedStatefulPartitionUsage():
  '''Gets encrypted stateful partition usage.

  Returns:
    A DiskUsedPercentage namedtuple like (bytes_used_pct=87,
                                          inodes_used_pct=17).
  Raises:
    DiskException if usage can not be obtained.
  '''
  vfs_infos = GetAllVFSInfo()
  for vfs_info in vfs_infos.values():
    if '/mnt/stateful_partition/encrypted' in vfs_info.mount_points:
      return GetPartitionUsage(vfs_info)
  raise DiskException('Can not get encrypted stateful partition usage')

def GetMaxStatefulPartitionUsage():
  '''Gets the max stateful partition usage.

  Returns:
    A tuple (max_partition, max_usage_type, max_usage) where
      max_partition is "stateful" or "encrypted",
      max_usage_type is "bytes" or "inodes",
      and max_usage is the usage in percentage.
  '''
  vfs_infos = GetAllVFSInfo()
  stateful_usage = dict()
  for vfs_info in vfs_infos.values():
    if '/mnt/stateful_partition' in vfs_info.mount_points:
      stateful_usage["stateful"] = GetPartitionUsage(vfs_info)
    if '/mnt/stateful_partition/encrypted' in vfs_info.mount_points:
      stateful_usage["encrypted"] = GetPartitionUsage(vfs_info)

  logging.debug('stateful usage: %s', stateful_usage)

  max_partition, max_usage_type, max_usage = None, None, 0
  for partition, usage in stateful_usage.iteritems():
    larger_usage = max(usage.bytes_used_pct, usage.inodes_used_pct)
    larger_usage_type = ('bytes'
        if (usage.bytes_used_pct > usage.inodes_used_pct) else 'inodes')
    if larger_usage > max_usage:
      max_partition, max_usage_type, max_usage = (partition, larger_usage_type,
                                                  larger_usage)
  return (max_partition, max_usage_type, max_usage)


class DiskException(Exception):
  pass


class DiskSpace(object):
  """Checks disk space usage"""
  args = None
  vfs_infos = GetAllVFSInfo()

  def Main(self):
    self.ParseArgs()
    self.ShowDiskSpace()
    self.CheckStatefulThreshold()

  def ParseArgs(self):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--stateful-partition-threshold-pct', metavar='PCT', default='95',
        help="Checks if stateful partition disk usage is above threshold")
    self.args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

  def ShowDiskSpace(self):
    """Shows all disk space usage"""
    print FormatSpaceUsedAll(GetAllVFSInfo())

  def CheckStatefulThreshold(self):
    """Raises an exception if stateful usage is greater than threshold.

    Raises:
      DiskException if stateful partition or encrypted stateful partition
        usage is larger than threshold.
    """
    self.args.stateful_partition_threshold_pct = int(
        self.args.stateful_partition_threshold_pct)
    max_partition, max_usage_type, max_usage = GetMaxStatefulPartitionUsage()
    if max_usage > self.args.stateful_partition_threshold_pct:
      raise DiskException(
            ('%s partition %s usage %d%% is above threshold %d%%' %
             (max_partition, max_usage_type, max_usage,
              self.args.stateful_partition_threshold_pct)))


if __name__ == '__main__':
  DiskSpace().Main()
