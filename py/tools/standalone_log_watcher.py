#!/usr/bin/env python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import os
import time
import traceback

import factory_common  # pylint: disable=W0611
from cros.factory.utils.process_utils import Spawn

DEFAULT_LOG_PATH = '/var/log/messages'
WATCH_FOR = 'EMI?'

ACTION_MSG = 'Please stop testing and call a factory team member to investigate'

COLOR_RED = '\033[1;31m'

class StandaloneLogWatcher(object):

  def __init__(self,
               log_path=DEFAULT_LOG_PATH,
               watch_str=WATCH_FOR,
               action_str=ACTION_MSG,
               watch_period_sec=10):
    self._watch_period_sec = watch_period_sec
    self._log_path = log_path
    self._watch_str = watch_str
    self._action_str = action_str
    self._last_size = None
    self._exception_caught = False

  def Alert(self, msg, die=True):
    if die:
      Spawn(['goofy_rpc', 'StopTest()'], call=True)
      time.sleep(2)
      Spawn(['chvt', '4'], call=True)
      with open('/dev/tty4', 'w') as f:
        f.write(COLOR_RED)
        mark_line = '!' * 80 + '\n'
        f.writelines([mark_line, mark_line, msg + '\n\n',
                      self._action_str + '\n', mark_line, mark_line])
    else:
      with open('/var/factory/log/factory.log', 'w') as f:
        f.write(msg + '\n')

  def ScanNewLogLines(self):
    try:
      log_size = os.stat(self._log_path).st_size

      # Initialize _last_size on first success read of the log
      if self._last_size is None:
        self._last_size = log_size
        return

      if log_size != self._last_size:
        with open(self._log_path, 'r') as f:
          seek_pos = max(0, self._last_size - len(self._watch_str))
          read_size = log_size - seek_pos
          f.seek(seek_pos)
          s = f.read(read_size)
        if self._watch_str in s:
          self.Alert('Found "%s" in %s.' % (self._watch_str, self._log_path))
        self._last_size = log_size
    except: # pylint: disable=W0702
      # Only reports the first exception caught
      if not self._exception_caught:
        self.Alert('StandaloneLogWatcher: %s' %
                   traceback.format_exc().replace('\n', '|'),
                   die=False)
        self._exception_caught = True
      return

  def WatchForever(self):
    while True:
      self.ScanNewLogLines()
      time.sleep(self._watch_period_sec)

def main():
  parser = argparse.ArgumentParser(
      description=('Watch a log file and display error message when '
                   'a watched string shows up.'))
  parser.add_argument('--log_path', '-l', default=DEFAULT_LOG_PATH,
                      help='Path to the log')
  parser.add_argument('--watch_str', '-w', default=WATCH_FOR,
                      help='String to watch for')
  parser.add_argument('--action_str', '-a', default=ACTION_MSG,
                      help='String to display in error message')
  args = parser.parse_args()
  watcher = StandaloneLogWatcher(log_path=args.log_path,
                                 watch_str=args.watch_str,
                                 action_str=args.action_str)
  watcher.WatchForever()

if __name__ == '__main__':
  main()
