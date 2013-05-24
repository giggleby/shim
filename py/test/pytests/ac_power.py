# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
A test to instruct the operator to plug/unplug AC power.
"""

import glob
import logging
import os
import time
import unittest

from cros.factory.test.args import Arg
from cros.factory.test import test_ui
from cros.factory.test import ui_templates

_TEST_TITLE_PLUG = test_ui.MakeLabel('Connect AC', u'连接充电器')
_TEST_TITLE_UNPLUG = test_ui.MakeLabel('Remove AC', u'移除充电器')

_PLUG_AC = test_ui.MakeLabel('Plug in the charger.', u'请连接充电器')
_UNPLUG_AC = test_ui.MakeLabel('Unplug the charger.', u'请移除充电器')

_POLLING_PERIOD_SECS = 1

POWER_SUPPLY_PATH = '/sys/class/power_supply/*'


class ACPowerTest(unittest.TestCase):
  """A test to instruct the operator to plug/unplug AC power.

  Args:
    power_type: The type of the power. Default to 'Mains'.
    online: True if expecting AC power. Otherwise, False.
  """

  ARGS = [
    Arg('power_type', str, 'Type of the power source',
        optional=True),
    Arg('online', bool, 'True if expecting AC power',
        default=True, optional=True),
  ]

  def setUp(self):
    self._ui = test_ui.UI()
    self._template = ui_templates.OneSection(self._ui)
    self._template.SetTitle(_TEST_TITLE_PLUG if self.args.online
                            else _TEST_TITLE_UNPLUG)
    self._template.SetState(_PLUG_AC if self.args.online else _UNPLUG_AC)

  def GetPowerType(self, path):
    type_path = os.path.join(path, 'type')
    if not os.path.exists(type_path):
      return None
    return open(type_path, 'r').read().strip()

  def PowerIsOnline(self, path):
    online_path = os.path.join(path, 'online')
    if not os.path.exists(online_path):
      return None
    return open(online_path, 'r').read().strip() == '1'

  def runTest(self):
    self._ui.Run(blocking=False)
    while True:
      for path in glob.glob(POWER_SUPPLY_PATH):
        if (self.args.power_type and
          self.GetPowerType(path) != self.args.power_type):
          continue
        if self.PowerIsOnline(path) == self.args.online:
          logging.info('Power supply %s is now %s', path,
                       'online' if self.args.online else 'offline')
          self._ui.Pass()
          return # Exit runTest
      time.sleep(_POLLING_PERIOD_SECS)
