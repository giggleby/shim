# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


'''This is a factory test to test battery charging/discharging current.

dargs:
  min_charging_current: The minimum allowed charging current. In mA.
  min_discharging_current: The minimum allowed discharging current. In mA.
  timeout_secs: The timeout of detecting required charging/discharging current.
'''

import logging
import time
import unittest

from cros.factory import system
from cros.factory.system.board import Board
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg

_TEST_TITLE = test_ui.MakeLabel('Battery Current Test', u'充電放電电流測試')

_CHARGE_TEXT = lambda c, t: test_ui.MakeLabel(
    'Waiting for charging current to meet %d mA. (Current: %d mA)' % (t, c),
    u'等待充电电流大于 %d mA. (目前 %d mA)' % (t, c))

_DISCHARGE_TEXT = lambda c, t: test_ui.MakeLabel(
    'Waiting for discharging current to meet %d mA. (Current: %d mA)' % (t, c),
    u'等待放电电流大于 %d mA. (目前 %d mA)' % (t, c))

class BatteryCurrentTest(unittest.TestCase):
  """
  A factory test to test battery charging/discharging current.
  """
  ARGS = [
      Arg('min_charging_current', int,
          'minimum allowed charging current', optional=True),
      Arg('min_discharging_current', int,
          'minimum allowed discharging current', optional=True),
      Arg('timeout_secs', int,
          'Test timeout value', default=10, optional=True),
      ]

  def setUp(self):
    """Sets the test ui, template and the thread that runs ui. Initializes
    _board and _power."""
    self._board = system.GetBoard()
    self._power = self._board.power
    self._ui = test_ui.UI()
    self._template = ui_templates.OneSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)

  def _GetBatteryCurrent(self):
    """Gets battery current through board"""
    try:
      battery_current = self._board.GetBatteryCurrent()
    except Exception, e:
      self.fail('Cannot get battery current on this board. %s' % e)
    else:
      return battery_current

  def _TestCharge(self, target):
    self._board.SetChargeState(Board.ChargeState.CHARGE)
    end_time = time.time() + self.args.timeout_secs
    while time.time() < end_time:
      current = self._GetBatteryCurrent()
      logging.info('Charging current = %d mA', current)
      if current >= target:
        return
      self._template.SetState(_CHARGE_TEXT(current, target))
      time.sleep(0.5)
    self._ui.Fail('Charging current smaller than %d mA' % target)

  def _TestDischarge(self, target):
    self._board.SetChargeState(Board.ChargeState.DISCHARGE)
    end_time = time.time() + self.args.timeout_secs
    while time.time() < end_time:
      current = -self._GetBatteryCurrent()
      logging.info('Discharging current = %d mA', current)
      if current >= target:
        return
      self._template.SetState(_DISCHARGE_TEXT(current, target))
      time.sleep(0.5)
    self._ui.Fail('Discharging current smaller than %d mA' % target)

  def runTest(self):
    """Main entrance of charger test."""
    self._ui.Run(blocking=False)
    if self.args.min_charging_current:
      self._TestCharge(self.args.min_charging_current)
    if self.args.min_discharging_current:
      self._TestDischarge(self.args.min_discharging_current)

  def tearDown(self):
    # Must enable charger to charge or we will drain the battery!
    self._board.SetChargeState(Board.ChargeState.CHARGE)
