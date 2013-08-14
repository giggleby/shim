#!/usr/bin/env python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import threading
import time

from cros.factory import system
from cros.factory.test import factory

class PowerMonitor(threading.Thread):
  """Power monitor used by test to monitor AC is normal.

  This monitor is a daemon thread to monitor AC status.
  If AC is abnormal, monitor will post a warning note. If it is abnormal
  for more than warning_countdown_secs, it will post a critical note to stop
  all tests. The usage is like:
  PowerMonitor(warning_countdown_secs=30, ac_type='Mains').start()

  Args:
    warning_countdown_secs: Warning duration in secs before posting
      a critical note to stop all tests.
    ac_type: The expected AC type.
    poll_interval_secs: The interval in seconds to check AC status.
  """
  def __init__(self, warning_countdown_secs, ac_type, poll_interval_secs=1):
    threading.Thread.__init__(self, name='PowerMonitor')
    self._warning_countdown_secs = warning_countdown_secs
    self._ac_type = ac_type
    self._board = system.GetBoard()
    self._power = self._board.power
    self._poll_interval_secs = poll_interval_secs
    self.daemon = True

  def _GetPowerInfo(self):
    """Gets power info of this board"""
    try:
      power_info = self._board.GetPowerInfo()
    except NotImplementedError:
      return None
    else:
      return power_info

  def ACIsNormal(self):
    """Checks AC is online and type is expected."""
    ac_present = self._power.CheckACPresent()
    current_type = self._power.GetACType()
    if ac_present and current_type == self._ac_type:
      return True
    else:
      if not ac_present:
        logging.warning('AC not present')
      elif current_type != self._ac_type:
        logging.warning('AC type mismatch: expect: %r, actual: %r',
            self._ac_type, current_type)
      logging.warning('Power info=\n%s', self._GetPowerInfo())
      return False

  def MonitorAC(self):
    """Monitors AC periodically.

    It is a busy loop polling AC status with period
    self._poll_interval_secs.
    """
    while True:
      time.sleep(self._poll_interval_secs)
      if not self.ACIsNormal():
        goofy = factory.get_state_instance()
        goofy.AddNote(dict(
            name='MonitorAC',
            text=('Please check AC is on within %s seconds.' %
                  self._warning_countdown_secs),
            level='WARNING'))

        # Waiting for AC to resume
        start_time = time.time()
        while True:
          time.sleep(self._poll_interval_secs)
          now_time = time.time()
          if self.ACIsNormal():
            logging.info('AC is back to normal.')
            goofy.AddNote(dict(
                name='MonitorAC',
                text=('AC is back to normal after %s seconds.' %
                      int(now_time - start_time)),
                level='INFO'))
            break
          if now_time - start_time > self._warning_countdown_secs:
            logging.error('AC is unplugged unexpectedly. End the test by'
                          ' posting a critical note.')
            goofy.AddNote(dict(
                name='MonitorAC',
                text=('AC is lost for more than %s seconds.' %
                      self._warning_countdown_secs),
                level='CRITICAL'))
            return

  def run(self):
    self.MonitorAC()
