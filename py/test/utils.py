#!/usr/bin/python -u
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility functions that are useful to factory tests."""

import array
import fcntl
import glob
import inspect
import logging
import multiprocessing
import os
import pipes
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from contextlib import contextmanager

import factory_common  # pylint: disable=W0611
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import time_utils
from cros.factory.utils import type_utils


# For backward compatibility. TODO(hungte) Remove or add wrapper functions.
CheckOutput = process_utils.CheckOutput
LogAndCheckCall = process_utils.LogAndCheckCall
LogAndCheckOutput = process_utils.LogAndCheckOutput
StartDaemonThread = process_utils.StartDaemonThread
is_process_alive = process_utils.IsProcessAlive
kill_process_tree = process_utils.KillProcessTree
TryMakeDirs = file_utils.TryMakeDirs
ReadOneLine = file_utils.ReadOneLine
TimeString = time_utils.TimeString
Enum = type_utils.Enum
DrainQueue = type_utils.DrainQueue
FlattenList = type_utils.FlattenList


def in_chroot():
  """Returns True if currently in the chroot."""
  return 'CROS_WORKON_SRCROOT' in os.environ


def in_qemu():
  """Returns True if running within QEMU."""
  return 'QEMU' in open('/proc/cpuinfo').read()


def in_cros_device():
  """Returns True if running on a Chrome OS device."""
  if not os.path.exists('/etc/lsb-release'):
    return False
  with open('/etc/lsb-release') as f:
    lsb_release = f.read()
  return re.match('^CHROMEOS_RELEASE', lsb_release, re.MULTILINE) is not None


def are_shift_keys_depressed():
  """Returns True if both shift keys are depressed."""
  # From #include <linux/input.h>
  KEY_LEFTSHIFT = 42
  KEY_RIGHTSHIFT = 54

  for kbd in glob.glob("/dev/input/by-path/*kbd"):
    try:
      f = os.open(kbd, os.O_RDONLY)
    except OSError:
      if in_chroot():
        # That's OK; we're just not root
        continue
      else:
        raise
    buf = array.array('b', [0] * 96)

    # EVIOCGKEY (from #include <linux/input.h>)
    fcntl.ioctl(f, 0x80604518, buf)

    def is_pressed(key):
      return (buf[key / 8] & (1 << (key % 8))) != 0

    if is_pressed(KEY_LEFTSHIFT) and is_pressed(KEY_RIGHTSHIFT):
      return True

  return False


def var_log_messages_before_reboot(lines=100,
                                   max_length=5*1024*1024,
                                   path='/var/log/messages'):
  """Returns the last few lines in /var/log/messages before the current boot.

  Args:
    lines: number of lines to return.
    max_length: maximum amount of data at end of file to read.
    path: path to /var/log/messages.

  Returns:
    An array of lines. Empty if the marker indicating kernel boot
    could not be found.
  """
  offset = max(0, os.path.getsize(path) - max_length)
  with open(path) as f:
    f.seek(offset)
    data = f.read()

  # Find the last element matching the RE signaling kernel start.
  matches = list(re.finditer(
      r'^(\S+)\s.*kernel:\s+\[\s+0\.\d+\] Linux version', data, re.MULTILINE))
  if not matches:
    return []

  match = matches[-1]
  tail_lines = data[:match.start()].split('\n')
  tail_lines.pop() # Remove incomplete line at end

  # Skip some common lines that may have been written before the Linux
  # version.
  while tail_lines and any(
    re.search(x, tail_lines[-1])
    for x in [r'0\.000000\]',
         r'rsyslogd.+\(re\)start',
         r'/proc/kmsg started']):
    tail_lines.pop()

  # Done! Return the last few lines.
  return tail_lines[-lines:] + [
      '<after reboot, kernel came up at %s>' % match.group(1)]


def FormatExceptionOnly():
  """Formats the current exception string.

  Must only be called from inside an exception handler.

  Returns:
    A string.
  """
  return '\n'.join(
    traceback.format_exception_only(*sys.exc_info()[:2])).strip()


def ResetCommitTime():
  """Remounts partitions with commit=0.

  The standard value on CrOS (commit=600) is likely to result in
  corruption during factory testing.  Using commit=0 reverts to the
  default value (generally 5 s).
  """
  if in_chroot():
    return

  devices = set()
  with open('/etc/mtab', 'r') as f:
    for line in f.readlines():
      cols = line.split(' ')
      device = cols[0]
      options = cols[3]
      if 'commit=' in options:
        devices.add(device)

  # Remount all devices in parallel, and wait.  Ignore errors.
  for process in [
      process_utils.Spawn(['mount', p, '-o', 'commit=0,remount'], log=True)
      for p in sorted(devices)]:
    process.wait()


class LoadManager(object):
  """A class to manage cpu load using stressapptest.
  This manager runs stressapptest with 20% memory and specified num_threads
  and duration.
  Usage:
    with LoadManager(num_threads, duration_secs):
      do_something_under_load
  Properties:
    _process: The process to run stressapptest
    _num_threads: The number of threads in running stressapptest.
    _memory_ratio: The memory ratio in running stressapptest.
  """
  def __init__(self, duration_secs, num_threads=None, memory_ratio=0.2, ):
    """Initialize LoadManager.

    Args:
      duration_secs: The duration of stressapptest.
      num_threads: Number of threads for stressapptest. Default value
        is number of cpus.
        If set, this should be less than or equal to number of cpus.
      memory_ratio: The ratio of memory used in stressapptest.
        Default value is 0.2.
        This should be less than or equal to 0.9.
    """
    self._process = None
    self._memory_ratio = None
    self._num_threads = None
    if num_threads is None:
      self._num_threads = multiprocessing.cpu_count()
    elif num_threads == 0:
      # No need to run stressapptest
      return
    else:
      self._num_threads = min(num_threads, multiprocessing.cpu_count())
    self._memory_ratio = min(0.9, memory_ratio)
    mem = open('/proc/meminfo').readline().split()[1]
    mem_usage = int(int(mem) * self._memory_ratio / 1024)
    self._process = process_utils.Spawn(
        ['stressapptest', '-m', '%d' % self._num_threads,
         '-M', '%d' %  mem_usage, '-s',  '%d' % duration_secs])
    logging.info('LoadManager: Start LoadManager with %d processes'
                 ' %d M memory %d seconds.',
                 self._num_threads, mem_usage, duration_secs)

  def __enter__(self):
    return self

  def __exit__(self, *args, **kwargs):
    self.Stop()

  def Stop(self):
    logging.info('LoadManager: Try to stop the process if there is one.')
    if self._process and self._process.poll() is None:
      logging.info('LoadManager: Terminating the process.')
      self._process.terminate()


# TODO(hungte) Move TimeoutError, Timeout, WaitFor, Retry, FormatExceptionOnly
# to py/utils/*.
def Retry(max_retry_times, interval, callback, target, *args, **kwargs):
  """Retries a function call with limited times until it returns True.

  Args:
    max_retry_times: The max retry times for target function to return True.
    interval: The sleep interval between each trial.
    callback: The callback after each retry iteration. Caller can use this
              callback to track progress. Callback should accept two arguments:
              callback(retry_time, max_retry_times).
    target: The target function for retry. *args and **kwargs will be passed to
            target.

  Returns:
    Within max_retry_times, if the return value of target function is
    neither None nor False, returns the value.
    If target function returns False or None or it throws
    any exception for max_retry_times, returns None.
  """
  result = None
  for retry_time in xrange(max_retry_times):
    try:
      result = target(*args, **kwargs)
    except Exception: # pylint: disable=W0703
      logging.exception('Retry...')
    if(callback):
      callback(retry_time, max_retry_times)
    if result:
      logging.info('Retry: Get result in retry_time: %d.', retry_time)
      break
    time.sleep(interval)
  return result


class TimeoutError(Exception):
  """Timeout error."""
  pass


@contextmanager
def Timeout(secs):
  """Timeout context manager. It will raise TimeoutError after timeout.
  It does not support nested "with Timeout" blocks.
  """
  def handler(signum, frame): # pylint: disable=W0613
    raise TimeoutError('Timeout')

  if secs:
    old_handler = signal.signal(signal.SIGALRM, handler)
    prev_secs = signal.alarm(secs)
    assert not prev_secs, 'Alarm was already set before.'

  try:
    yield
  finally:
    if secs:
      signal.alarm(0)
      signal.signal(signal.SIGALRM, old_handler)


def SendKey(key_sequence):
  """Send the given key sequence through X server.

  Args:
    key_sequence: This can be a list of keys to send or a string of key
        sequence.  For example:
          - list: ['f', 'o', 'o'] sends the string 'foo' through xdotool.
          - string: 'Alt+F4' sends the F4 key wth modifier Alt through xdotool.
        For more details, see the help of xdotool.
  """
  os.environ['DISPLAY'] = ':0'
  os.environ['XAUTHORITY'] = '/home/chronos/.Xauthority'
  if isinstance(key_sequence, list):
    process_utils.Spawn(['xdotool', 'key'] + key_sequence)
  elif isinstance(key_sequence, basestring):
    process_utils.Spawn(['xdotool', 'key', key_sequence])
  else:
    raise ValueError('key_sequence must be a list or a string')


def WaitFor(condition, timeout_secs, poll_interval=0.1):
  """Wait for the given condition for at most the specified time.

  Args:
    condition: A function object.
    timeout_secs: Timeout value in seconds.
    poll_interval: Interval to poll condition.

  Raises:
    ValueError: If condition is not a function.
    TimeoutError: If cond does not become True after timeout_secs seconds.
  """
  if not callable(condition):
    raise ValueError('condition must be a callable object')

  def _GetConditionString():
    condition_string = condition.__name__
    if condition.__name__ == '<lambda>':
      try:
        condition_string = inspect.getsource(condition).strip()
      except IOError:
        pass
    return condition_string

  end_time = time_utils.MonotonicTime() + timeout_secs
  while True:
    if condition():
      break
    if time_utils.MonotonicTime() > end_time:
      raise TimeoutError('Timeout waititng for %r' % _GetConditionString())
    time.sleep(poll_interval)


def SetTouchpadTwoFingerScrollingX(enabled):
  """Enables / disables two-finger scrolling.

  Currently this function only disables X-axis two-finger scrolling, as it can
  accidentally trigger 'last page'.

  Args:
    enabled: True or False indicating the state of two-finger scrolling to set.
  """
  TPSCONTROL_XINPUT = '/opt/google/touchpad/tpcontrol_xinput'
  def GetPropIdValue(prop_name):
    # Example 'xinput list-props <id>' output format:
    #        ...
    #        Scroll X Out Scale (379):       2.500000
    #        Scroll Y Out Scale (380):       2.500000
    #        ...
    prop_id_re = re.compile(
        r'^\s*(?:%s).*'       # Match property name.
        r'\((\d+)\):\s*'      # Get property ID.
        r'(.*)$' % prop_name, # Get property value.
        flags=re.M)
    xinput_list_props = CheckOutput([TPSCONTROL_XINPUT, 'status'])
    matched_obj = prop_id_re.search(xinput_list_props)
    if matched_obj:
      return matched_obj.groups()
    else:
      return (None, None)

  os.environ['DISPLAY'] = ':0'
  os.environ['XAUTHORITY'] = '/home/chronos/.Xauthority'
  property_name = 'Scroll X Out Scale'    # We only disable X-axis scrolling.
  default_scale = '2.5'

  prop_id = GetPropIdValue(property_name)[0]
  if not prop_id:
    # Cannot find the requested property ID.  This can happen during early
    # development stages if touchpad driver is not in place.
    return

  if bool(enabled):
    prop_value = default_scale
  else:
    prop_value = '0'
  process_utils.Spawn([TPSCONTROL_XINPUT, 'set', prop_id, prop_value])


def HasX():
  """Checks whether X is present on the system."""
  return os.path.exists('/opt/google/input/xinput.sh')


def _CrOSTouchXInput(args):
  """Helper method to invoke shell functions defined in xinput.sh

  Args:
    args: The code snippet to run in the context of xinput.sh.

  Returns:
    The evaluated result.
  """
  DUMMY_SCRIPT = '. /opt/google/input/xinput.sh\n%s'
  with tempfile.NamedTemporaryFile(prefix='cros_touch_xinput.') as f:
    f.write(DUMMY_SCRIPT % args)
    f.flush()
    return process_utils.CheckOutput(['sh', f.name], log=True)


def GetTouchscreenDeviceIds():
  """Gets xinput device ids of touchscreen.

  Returns:
    The xinput device ids of touchscreen as a list of integers.
  """
  return [int(x.strip()) for x in _CrOSTouchXInput('list_touchscreens').split()]


def GetTouchpadDeviceIds():
  """Gets xinput device ids of touchpads.

  Returns:
    The xinput device ids of touchpads as a list of integers.
  """
  return [int(x.strip()) for x in _CrOSTouchXInput('list_touchpads').split()]


def IsXinputDeviceEnabled(device_id):
  """Reports current enabled state of the given xinput device.

  Args:
    device_id: The id of the xinput device.

  Returns:
    True if the device is enabled; False otherwise.
  """
  return _CrOSTouchXInput(
      'device_get_prop %d "Device Enabled"' % device_id).strip() == '1'


def SetXinputDeviceEnabled(device_id, enabled):
  """Enables / disables the given xinput device.

  Args:
    device_id: The id of the xinput device.
    enabled: True or False indicating the state of the device.
  """
  _CrOSTouchXInput(
      'device_set_prop %d "Device Enabled" %d' %
      (device_id, 1 if enabled else 0))
  assert IsXinputDeviceEnabled(device_id) == enabled
