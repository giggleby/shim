# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


'''This is a factory test that only pass when battery is charged to specific level.
'''

import logging
import threading
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory import system
from cros.factory.test.event_log import Log
from cros.factory.system.board import Board
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg

_TEST_TITLE = test_ui.MakeLabel('Charging', u'充电')

_LABEL_TIME_EN = 'Time elapsed: %s' + '&nbsp;' * 8 + 'Time remaining: %s'
_LABEL_TIME_ZH = u'经过时间: %s' + u'&nbsp;' * 8 + u'剩余时间: %s'
_LABEL_CHARGING_EN = (
    'Charging to %d%% (Start: %d%%. Current: %d%%.)<br>' +
    _LABEL_TIME_EN)
_LABEL_CHARGING_ZH = (
    u'充电至 %d%% (起始电量: %d%%. 当前电量: %d%%.)<br>' +
    _LABEL_TIME_ZH)
_LABEL_REQUIRE_AC_EN = (
    'Plug in external power to charge.<br>' +
    _LABEL_TIME_EN)
_LABEL_REQUIRE_AC_ZH = (
    u'请插上外接电源以充电。<br>' +
    _LABEL_TIME_ZH)

def FormatTime(seconds):
  return '%d:%02d:%02d' % (seconds / 3600, (seconds / 60) % 60, seconds % 60)


def MakeChargeTextLabel(ac_present, start, current, target, elapsed, remaining):
  if not ac_present:
    values = (FormatTime(elapsed), FormatTime(remaining))
    return test_ui.MakeLabel(
        _LABEL_REQUIRE_AC_EN % values,
        _LABEL_REQUIRE_AC_ZH % values)

  values = (target, start, current, FormatTime(elapsed), FormatTime(remaining))
  return test_ui.MakeLabel(
      _LABEL_CHARGING_EN % values,
      _LABEL_CHARGING_ZH % values)


def MakeSpriteHTMLTag(src, height, width):
  return (('<div id="batteryIcon" style="background-image: url(%s);' +
           'width: %dpx; height: %dpx; margin:auto;"></div>') %
          (src, width, height))


class ChargerTest(unittest.TestCase):
  ARGS = [
      Arg('target_charge_pct', int, 'Target charge level',
          default=78),
      Arg('target_charge_pct_is_delta', bool,
          'Specify target_charge_pct is a delta of current charge',
          default=False),
      Arg('wait_for_external_power', bool,
          'Waits for external power if it is not found',
          default=False),
      Arg('timeout_secs', int, 'Maximum allowed time to charge battery',
          default=3600),
  ]

  def setUp(self):
    self._board = system.GetBoard()
    self._power = self._board.power
    self._ui = test_ui.UI()
    self._template = ui_templates.TwoSections(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    self._thread = threading.Thread(target=self._ui.Run)

  def CheckPower(self):
    self.assertTrue(self._power.CheckBatteryPresent(), 'Cannot find battery.')
    if not self.args.wait_for_external_power:
      self.assertTrue(self._power.CheckACPresent(), 'Cannot find AC power.')

  def Charge(self):
    start_charge = self._power.GetChargePct()
    self.assertTrue(start_charge, 'Error getting battery state.')
    target_charge = self.args.target_charge_pct
    if self.args.target_charge_pct_is_delta is True:
      target_charge = min(target_charge + start_charge, 100)
    if start_charge >= target_charge:
      return
    self._board.SetChargeState(Board.ChargeState.CHARGE)
    self._template.SetState(MakeSpriteHTMLTag('charging_sprite.png', 256, 256))
    logging.info('Charging starting at %d%%', start_charge)


    for elapsed in xrange(self.args.timeout_secs):
      charge = self._power.GetChargePct()

      if charge >= target_charge:
        Log('charged', charge=charge, target=target_charge,
            elapsed=elapsed)
        return
      self._ui.RunJS('$("batteryIcon").style.backgroundPosition = "-%dpx 0px"' %
                     ((elapsed % 4) * 256))
      self._template.SetInstruction(MakeChargeTextLabel(
          self._power.CheckACPresent(),
          start_charge,
          charge,
          target_charge,
          elapsed,
          self.args.timeout_secs - elapsed))
      if elapsed % 300 == 0:
        logging.info('Battery level is %d%% after %d minutes',
                     charge,
                     elapsed / 60)
      time.sleep(1)

    Log('failed_to_charge', charge=charge, target=target_charge,
        timeout_sec=self.args.timeout_secs)
    self.fail('Cannot charge battery to %d%% in %d seconds.' %
              (target_charge, self.args.timeout_secs))

  def runTest(self):
    self._thread.start()
    try:
      self.CheckPower()
      self.Charge()
    except Exception, e:
      self._ui.Fail(str(e))
      raise
    else:
      self._ui.Pass()

  def tearDown(self):
    self._thread.join()
