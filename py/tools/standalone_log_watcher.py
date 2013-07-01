#!/usr/bin/env python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import syslog
import time

import factory_common  # pylint: disable=W0611
from cros.factory.event_log import EventLog
from cros.factory.test import factory
from cros.factory.utils.process_utils import Spawn

COLOR_RED = '\033[1;31m'

class StandaloneWatcherAlert(Exception):
  def __init__(self, msg, action=None, color=COLOR_RED, die=True):
    super(StandaloneWatcherAlert, self).__init__()
    self.msg = msg
    self.action = action
    self.color = color
    self.die = die

class StandaloneLogWatcher(object):

  def __init__(self, watchers, watch_period_sec=10):
    syslog.openlog('standalone_watcher')
    self._event_log = EventLog('standalone_watcher')
    self._watchers = watchers
    self._watch_period_sec = watch_period_sec
    factory.init_logging()
    logging.info('Standalone watchers: %s',
                 ', '.join([w.__class__.__name__ for w in watchers]))

  def _Log(self, log_str):
    logging.error(log_str)
    syslog.syslog(log_str)

  def Alert(self, msg, action=None, color=COLOR_RED, die=True):
    self._Log('Watcher error: %s' % msg)
    self._event_log.Log('watcher_error', message=msg, action=action, die=die)
    if action:
      self._Log('Displaying action: %s' % action)
    if die:
      self._Log('Watcher says "die"...stopping running test.')
      Spawn(['goofy_rpc', 'StopTest()'], call=True, log=True)
      time.sleep(2)
      Spawn(['chvt', '4'], call=True, log=True)
      with open('/dev/tty4', 'w') as f:
        f.write(color)
        mark_line = '!' * 80 + '\n'
        f.writelines([mark_line, mark_line, '%s\n\n' % msg,
                      '%s\n' % action if action else '',
                      mark_line, mark_line])

  def WatchForever(self):
    while True:
      for w in self._watchers:
        try:
          w.Check()
        except StandaloneWatcherAlert as alert:
          self.Alert(msg=alert.msg,
                     action=alert.action,
                     color=alert.color,
                     die=alert.die)
      time.sleep(self._watch_period_sec)
