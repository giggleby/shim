# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Umpire utility classes."""

from collections import namedtuple
import filecmp
import functools
import logging
import os
import stat

from twisted.internet import defer

from cros.factory.umpire import common
from cros.factory.utils import file_utils


def ConcentrateDeferreds(deferred_list):
  """Collects results from list of deferreds.

  Returns a deferred object that fires error callback on first error.
  And the original failure won't propagate back to original deferred object's
  next error callback.

  Args:
    deferred_list: Iterable of deferred objects.

  Returns:
    Deferred object that fires error on any deferred_list's errback been
    called. Its callback will be trigged when all callback results are
    collected. The gathered result is a list of deferred object callback
    results.
  """
  return defer.gatherResults(deferred_list, consumeErrors=True)


def Deprecate(method):
  """Logs error of calling deprecated function.

  Args:
    method: the deprecated function.
  """
  @functools.wraps(method)
  def _Wrapper(*args, **kwargs):
    logging.error('%s is deprecated', method.__name__)
    return method(*args, **kwargs)

  return _Wrapper


LoopDeviceStat = namedtuple('LoopDeviceStat', 'major_number mode uid gid')
DEFAULT_LOOP_DEVICE_STAT = LoopDeviceStat(7, 0o0660 | stat.S_IFBLK, 0, 0)


def _GetLoopDeviceStat():
  try:
    stat_result = os.stat('/dev/loop0')
    major_number = os.major(stat_result.st_rdev)
    mode = stat_result.st_mode
    uid = stat_result.st_uid
    gid = stat_result.st_gid
    return_value = LoopDeviceStat(major_number, mode, uid, gid)
  except OSError:
    logging.warning('Failed to stat /dev/loop0, try defalt value.',
                    exc_info=True)
    return_value = DEFAULT_LOOP_DEVICE_STAT
  return return_value


def CreateLoopDevice(loop_path_prefix: str, start: int, end: int):
  major_number, mode, uid, gid = _GetLoopDeviceStat()

  for i in range(start, end):
    loop_path = loop_path_prefix + str(i)
    if os.path.exists(loop_path):
      continue

    device_number = os.makedev(major_number, i)
    try:
      os.mknod(loop_path, mode, device_number)
      os.chown(loop_path, uid, gid)
    except OSError as e:
      logging.warning('Failed to create %s: %s', loop_path, e)
      return False

  return True


def CheckAndMoveFile(src_path, dst_path, use_move):
  """Check if destination file exists and move file.

  Args:
    src_path: source file path.
    dst_path: destination file path.
    use_move: use os.rename() or file_utils.AtomicCopy().

  Raise:
    UmpireError if dst_path exists but has different content from src_path.
  """
  if os.path.exists(dst_path):
    if filecmp.cmp(src_path, dst_path, shallow=False):
      logging.warning('Skip copying as file already exists: %s', dst_path)
      return
    raise common.UmpireError(
        f'Hash collision: file {src_path!r} != resource file {dst_path!r}')
  if use_move:
    os.rename(src_path, dst_path)
  else:
    file_utils.AtomicCopy(src_path, dst_path)
  os.chmod(dst_path, 0o644)
  logging.info('File added: %s', dst_path)
