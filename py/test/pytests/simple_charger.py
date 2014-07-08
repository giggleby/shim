# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""
This is a factory test to test that charger can charge battery.
The test checks current for several times and see if its median meets the
requirement.

dargs:
  min_starting_charge_pct: Minimum starting charge level when testing.
  max_starting_charge_pct: Maximum starting charge level when testing.
  min_charge_current: Minimum charge current in mA.
  check_interval_secs: Time interval in seconds between each check.
  check_duration_secs: Time duration in seconds to check current.
"""

import numpy
import time
import unittest

from cros.factory import system
from cros.factory.test import factory
from cros.factory.test.args import Arg


class SimpleChargerTest(unittest.TestCase):
  """This class tests that charger can charge/discharge battery for certain
  amount of change within certain time under certain load.

  Properties:
    _board: The Board object to provide interface to battery and charger.
    _power: The Power object to get AC/Battery info and charge percentage.
  """
  ARGS = [
      Arg('min_starting_charge_pct', (int, float),
          'minimum starting charge level when testing', default=10.0),
      Arg('max_starting_charge_pct', (int, float),
          'maximum starting charge level when testing', default=90.0),
      Arg('min_median_charge_current', (int, float),
          'minimum median charge current in mA', default=500.0),
      Arg('check_interval_secs', (int, float),
          'time interval in seconds between each check', default=1),
      Arg('check_duration_secs', (int, float),
          'time duration in seconds to check current', default=10)
      ]

  def setUp(self):
    """nitializes _board and _power."""
    self._board = system.GetBoard()
    self._power = self._board.power
    self._min_starting_charge = float(self.args.min_starting_charge_pct)
    self._max_starting_charge = float(self.args.max_starting_charge_pct)

  def _CheckPower(self):
    """Checks battery and AC power adapter are present."""
    self.assertTrue(self._power.CheckBatteryPresent(), 'Cannot find battery.')
    self.assertTrue(self._power.CheckACPresent(), 'Cannot find AC power.')

  def _GetCharge(self):
    """Gets charge level through power interface"""
    charge = self._power.GetChargePct(get_float=True)
    self.assertTrue(charge is not None, 'Error getting battery charge state.')
    return charge

  def _GetCurrent(self):
    """Gets current through power interface"""
    current = float(self._power.GetCurrent())
    self.assertTrue(current is not None, 'Error getting battery current.')
    return current

  def runTest(self):
    """Main entrance of charger test."""
    self._CheckPower()
    charge = self._GetCharge()

    self.assertGreater(
        charge, self._min_starting_charge,
        'Starting charge level %f%% less than %f%%.' % (
        charge, self._min_starting_charge))
    self.assertGreater(
        self._max_starting_charge, charge,
        'Starting charge level %f%% greater than %f%%.' % (
        charge, self._max_starting_charge))

    start_time = time.time()
    current_time = time.time()
    currents = []
    while current_time - start_time < self.args.check_duration_secs:
      current = self._GetCurrent()
      factory.console.info('Current = %f mA', current)
      currents.append(current)
      current_time = time.time()
      time.sleep(self.args.check_interval_secs)
    median_current = numpy.median(currents)
    factory.console.info('Median current= %f mA', median_current)
    self.assertTrue(
        median_current > self.args.min_median_charge_current,
        'Median current %f mA does not meet %f mA' % (
        median_current, self.args.min_median_charge_current))
