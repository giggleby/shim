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
from cros.factory.utils.process_utils import Spawn, CheckOutput

DEFAULT_LOG_PATH = '/var/log/messages'
WATCH_FOR = 'EMI?'

ACTION_MSG = 'Please stop testing and call a factory team member to investigate'
OUTPUT_TRIGGER_ACTION_MSG = 'Please unplug and plug the charger, reboot, rerun.'

COMMAND = 'ectool powerinfo'
OUTPUT_WATCH_FOR = 'USB Device Type: 0x60000'
OUTPUT_TRIGGER_TIME = 3

COLOR_RED = '\033[1;31m'
COLOR_YELLOW = '\033[1;33m'

class StandaloneLogWatcher(object):

  def __init__(self,
               log_path=DEFAULT_LOG_PATH,
               watch_str=WATCH_FOR,
               action_str=ACTION_MSG,
               command=COMMAND,
               output_watch_str=OUTPUT_WATCH_FOR,
               output_trigger_times=OUTPUT_TRIGGER_TIME,
               output_trigger_action_str=OUTPUT_TRIGGER_ACTION_MSG,
               watch_period_sec=10):
    self._watch_period_sec = watch_period_sec
    self._log_path = log_path
    self._watch_str = watch_str
    self._action_str = action_str
    self._last_size = None
    self._command = command
    self._output_watch_str = output_watch_str
    self._output_trigger_times = output_trigger_times
    self._output_trigger_count = 0
    self._output_trigger_action_str = output_trigger_action_str
    self._exception_caught_scan = False
    self._exception_caught_command = False

  def Alert(self, msg, action=None, color=COLOR_RED, die=True):
    if die:
      Spawn(['goofy_rpc', 'StopTest()'], call=True)
      time.sleep(2)
      Spawn(['chvt', '4'], call=True)
      with open('/dev/tty4', 'w') as f:
        f.write(color)
        mark_line = '!' * 80 + '\n'
        f.writelines([mark_line, mark_line, msg + '\n\n',
                      (action if action else '') + '\n', mark_line, mark_line])
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
          self.Alert('Found "%s" in %s.' % (self._watch_str, self._log_path),
                     self._action_str)
        self._last_size = log_size
    except: # pylint: disable=W0702
      # Only reports the first exception caught
      if not self._exception_caught_scan:
        self.Alert('StandaloneLogWatcher: %s' %
                   traceback.format_exc().replace('\n', '|'),
                   die=False)
        self._exception_caught_scan = True
      return

  def CheckCommand(self):
    try:
      output = CheckOutput(self._command.split(' '))
      if self._output_watch_str in output:
        self._output_trigger_count += 1
        if self._output_trigger_count == self._output_trigger_times:
          self.Alert(('Found "%s" in %s output:\n%s for %d times.' %
              (self._output_watch_str, self._command, output,
               self._output_trigger_count)), self._output_trigger_action_str,
              color=COLOR_YELLOW)
      else:
        self._output_trigger_count = 0
    except: # pylint: disable=W0702
      # Only reports the first exception caught
      if not self._exception_caught_command:
        self.Alert('StandaloneLogWatcher: %s' %
                   traceback.format_exc().replace('\n', '|'),
                   die=False)
        self._exception_caught_command = True
      return

  def WatchForever(self):
    while True:
      self.ScanNewLogLines()
      self.CheckCommand()
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
  parser.add_argument('--command', '-c', default=COMMAND,
                      help='The command to check its output')
  parser.add_argument('--output_watch_str', '-p', default=OUTPUT_WATCH_FOR,
                      help='The pattern to check in command output')
  parser.add_argument('--output_trigger_times', '-t',
                      default=OUTPUT_TRIGGER_TIME,
                      help='The consecutive times to trigger alert for checking'
                           ' command output')
  parser.add_argument('--output_trigger_action_str', '-o',
                      default=OUTPUT_TRIGGER_ACTION_MSG,
                      help='String to display in error message when alert is '
                           'triggered by command output')
  args = parser.parse_args()
  watcher = StandaloneLogWatcher(
      log_path=args.log_path,
      watch_str=args.watch_str,
      action_str=args.action_str,
      command=args.command,
      output_watch_str=args.output_watch_str,
      output_trigger_times=args.output_trigger_times,
      output_trigger_action_str=args.output_trigger_action_str)

  watcher.WatchForever()

if __name__ == '__main__':
  main()
