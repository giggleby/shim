#!/usr/bin/env python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time

import factory_common  # pylint: disable=W0611
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
    self._watchers = watchers
    self._watch_period_sec = watch_period_sec

  def Alert(self, msg, action=None, color=COLOR_RED, die=True):
    if die:
      Spawn(['goofy_rpc', 'StopTest()'], call=True)
      time.sleep(2)
      Spawn(['chvt', '4'], call=True)
      with open('/dev/tty4', 'w') as f:
        f.write(color)
        mark_line = '!' * 80 + '\n'
        f.writelines([mark_line, mark_line, '%s\n\n' % msg,
                      '%s\n' % action if action else '',
                      mark_line, mark_line])
    else:
      with open(factory.FACTORY_LOG_PATH, 'a') as f:
        f.write(msg + '\n')

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
