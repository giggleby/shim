# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Test that charger can charge/discharge battery for certain amount
of change within certain time under certain load.
"""

from collections import namedtuple
import logging
import os
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import event_log
from cros.factory.test.i18n import _
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import session
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.utils import stress_manager
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils


def _REGULATE_CHARGE_TEXT(charge, target, timeout, load,
                          battery_current, use_percentage):
  """Makes label to show subtest information

  Args:
    charge: current battery charge percentage.
    target: target battery charge percentage.
    timeout: remaining time for this subtest.
    load: load argument for this subtest.
    battery_current: battery current.
    use_percentage: Whether to use percentage or mAh.

  Returns:
    A html label to show in test ui.
  """
  unit = '%' if use_percentage else 'mAh'
  action = _('Discharging') if charge > target else _('Charging')
  return i18n_test_ui.MakeI18nLabel(
      '{action} to {target:.2f}{unit} '
      '(Current charge: {charge:.2f}{unit},'
      ' battery current: {battery_current} mA)'
      ' under load {load}.<br>'
      'Time remaining: {timeout} sec.',
      action=action, target=target, unit=unit, charge=charge,
      battery_current=battery_current, load=load, timeout=timeout)


def _MEET_TEXT(target, use_percentage):
  """Makes label to show subtest completes.

  Args:
    target: target battery charge percentage of this subtest.
    use_percentage: Whether to use percentage or mAh.

  Returns:
    A html label to show in test ui.
  """
  unit = '%' if use_percentage else 'mAh'
  return i18n_test_ui.MakeI18nLabel(
      'OK! Meet {target:.2f}{unit}', target=target, unit=unit)


_CHARGE_TEXT = i18n_test_ui.MakeI18nLabel('Testing charger')
_DISCHARGE_TEXT = i18n_test_ui.MakeI18nLabel('Testing discharge')

Spec = namedtuple('Spec', 'charge_change timeout_secs load')

CHARGE_TOLERANCE = 0.001


class ChargerTest(unittest.TestCase):
  """This class tests that charger can charge/discharge battery for certain
  amount of change within certain time under certain load.

  Properties:
    _power: The Power object to get AC/Battery info and charge percentage.
    _ui: Test UI.
    _template: Test template.
  """
  ARGS = [
      Arg('min_starting_charge_pct', (int, float),
          'minimum starting charge level when testing', default=20.0),
      Arg('max_starting_charge_pct', (int, float),
          'maximum starting charge level when testing', default=90.0),
      Arg('starting_timeout_secs', int, 'Maximum allowed time to regulate'
          'battery to starting_charge_pct', default=300),
      Arg('check_battery_current', bool, 'Check battery current > 0'
          'when charging and < 0 when discharging', default=True),
      Arg('battery_check_delay_sec', int, 'Delay of checking battery current. '
          'This can be used to handle slowly settled battery current.',
          default=3),
      Arg('verbose_log_period_secs', int, 'Log debug data every x seconds '
          'to verbose log file.', default=3),
      Arg('log_period_secs', int, 'Log test data every x seconds.',
          default=60),
      Arg('use_percentage', bool, 'True if using percentage as charge unit '
          'in spec list. False if using mAh.', default=True),
      Arg('charger_type', str, 'Type of charger required.',
          default=None),
      Arg('spec_list', list, 'A list of tuples. Each tuple contains\n'
          '(charge_change, timeout_secs, load)\n'
          'Charger needs to achieve charge_change difference within\n'
          'timeout_secs seconds under load.\n'
          'Positive charge_change is for charging and negative one is\n'
          'for discharging.\n'
          'One unit of load is one thread doing memory copy in stressapptest.\n'
          'The default value for load is the number of processor',
          default=[(2, 300, 1), (-2, 300)])
  ]

  def setUp(self):
    """Sets the test ui, template and the thread that runs ui. Initializes
    _board and _power."""
    self._dut = device_utils.CreateDUTInterface()
    self._power = self._dut.power
    self._ui = test_ui.UI()
    self._template = ui_templates.OneSection(self._ui)
    self._min_starting_charge = float(self.args.min_starting_charge_pct)
    self._max_starting_charge = float(self.args.max_starting_charge_pct)
    self._unit = '%' if self.args.use_percentage else 'mAh'
    verbose_log_path = session.GetVerboseTestLogPath()
    file_utils.TryMakeDirs(os.path.dirname(verbose_log_path))
    logging.info('Raw verbose logs saved in %s', verbose_log_path)
    self._verbose_log = open(verbose_log_path, 'a')

  def _NormalizeCharge(self, charge_pct):
    if self.args.use_percentage:
      return charge_pct
    else:
      return charge_pct * self._power.GetChargeFull() / 100.0

  def _CheckPower(self):
    """Checks battery and AC power adapter are present."""
    self.assertTrue(self._power.CheckBatteryPresent(), 'Cannot find battery.')
    self.assertTrue(self._power.CheckACPresent(), 'Cannot find AC power.')
    if self.args.charger_type:
      self.assertTrue(self.args.charger_type in self._power.GetACTypes(),
                      'Incorrect charger type: %s' % self._power.GetACTypes())

  def _GetCharge(self, use_percentage=True):
    """Gets charge level through power interface"""
    if use_percentage:
      charge = self._power.GetChargePct(get_float=True)
    else:
      charge = float(self._power.GetChargeMedian())
    self.assertTrue(charge is not None, 'Error getting battery charge state.')
    return charge

  def _GetBatteryCurrent(self):
    """Gets battery current through board"""
    try:
      battery_current = self._power.GetBatteryCurrent()
    except Exception, e:
      self.fail('Cannot get battery current on this board. %s' % e)
    else:
      return battery_current

  def _GetChargerCurrent(self):
    """Gets current that charger wants to drive through board"""
    try:
      charger_current = self._power.GetChargerCurrent()
    except NotImplementedError:
      return None
    else:
      return charger_current

  def _GetPowerInfo(self):
    """Gets power info on this board"""
    try:
      power_info = self._power.GetPowerInfo()
    except NotImplementedError:
      return None
    else:
      return power_info

  def _Meet(self, charge, target, moving_up):
    """Checks if charge has meet the target.

    Args:
      charge: The current charge value.
      target: The target charge value.
      moving_up: The direction of charging. Should be True or False.

    Returns:
      True if charge is close to target enough, or charge > target when
        moving up, or charge < target when moving down.
      False otherwise.
    """
    self.assertTrue(moving_up is not None)
    if abs(charge - target) < CHARGE_TOLERANCE:
      return True
    if moving_up:
      return charge > target
    else:
      return charge < target

  def _RegulateCharge(self, spec):
    """Checks if the charger can meet the spec.

    Checks if charge percentage and battery current are available.
    Decides whether to charge or discharge battery based on
    spec.charge_change.
    Sets the load and tries to meet the difference within timeout.

    Args:
      spec: A Spec namedtuple.
    """
    charge = self._GetCharge(self.args.use_percentage)
    battery_current = self._GetBatteryCurrent()
    target = charge + spec.charge_change
    moving_up = None
    if abs(target - charge) < CHARGE_TOLERANCE:
      logging.warning('Current charge is %.2f%s, target is %.2f%s.'
                      ' They are too close so there is no need to'
                      'charge/discharge.', charge, self._unit,
                      target, self._unit)
      event_log.Log('target_too_close', charge=charge, target=target)
      return

    elif charge > target:
      logging.info('Current charge is %.2f%s, discharge the battery to %.2f%s.',
                   charge, self._unit, target, self._unit)
      self._SetDischarge()
      moving_up = False
    elif charge < target:
      logging.info('Current charge is %.2f%s, charge the battery to %.2f%s.',
                   charge, self._unit, target, self._unit)
      self._SetCharge()
      moving_up = True

    # charge should move up or down.
    self.assertTrue(moving_up is not None)

    if spec.load > 0:
      stress_manager_instance = stress_manager.StressManager(self._dut)
    else:
      stress_manager_instance = stress_manager.DummyStressManager()

    with stress_manager_instance.Run(num_threads=spec.load):
      start_time = time.time()
      last_verbose_log_time = None
      last_log_time = None
      spec_end_time = start_time + spec.timeout_secs
      while time.time() < spec_end_time:
        elapsed = time.time() - start_time
        self._template.SetState(_REGULATE_CHARGE_TEXT(
            charge, target, spec.timeout_secs - elapsed, spec.load,
            battery_current, self.args.use_percentage))
        time.sleep(1)
        self._CheckPower()
        charge = self._GetCharge(self.args.use_percentage)
        battery_current = self._GetBatteryCurrent()
        if self._Meet(charge, target, moving_up):
          logging.info('Meet difference from %.2f%s to %.2f%s'
                       ' in %d secs under %d load.',
                       target - spec.charge_change, self._unit,
                       target, self._unit,
                       elapsed, spec.load)
          event_log.Log('meet', elapsed=elapsed, load=spec.load, target=target,
                        charge=charge)
          self._template.SetState(_MEET_TEXT(target, self.args.use_percentage))
          time.sleep(1)
          return
        elif elapsed >= self.args.battery_check_delay_sec:
          charger_current = self._GetChargerCurrent()
          if (not last_verbose_log_time or
              elapsed - last_verbose_log_time >
              self.args.verbose_log_period_secs):
            self._VerboseLog(charge, charger_current, battery_current)
            last_verbose_log_time = elapsed
          if (not last_log_time or
              elapsed - last_log_time >
              self.args.log_period_secs):
            self._Log(charge, charger_current, battery_current)
            last_log_time = elapsed
          if charge < target:
            self._CheckCharge(charger_current, battery_current)
          else:
            self._CheckDischarge(battery_current)

      event_log.Log('not_meet', load=spec.load, target=target, charge=charge)
      self.fail('Cannot regulate battery to %.2f%s in %d seconds.' %
                (target, self._unit, spec.timeout_secs))

  def _VerboseLog(self, charge, charger_current, battery_current):
    """Log data to verbose log"""
    self._verbose_log.write(time.strftime('%Y-%m-%d %H:%M:%S\n', time.gmtime()))
    self._verbose_log.write('Charge = %.2f%s\n' % (charge, self._unit))
    if charger_current is not None:
      self._verbose_log.write('Charger current = %d\n' % charger_current)
    self._verbose_log.write('Battery current = %d\n' % battery_current)
    self._verbose_log.write('Power info =\n%s\n' % self._GetPowerInfo())
    self._verbose_log.flush()

  def _Log(self, charge, charger_current, battery_current):
    """Log data"""
    logging.info('Charge = %.2f%s', charge, self._unit)
    if charger_current is not None:
      logging.info('Charger current = %d', charger_current)
    logging.info('Battery current = %d', battery_current)

  def _CheckCharge(self, charger_current, battery_current):
    """Checks current in charging state"""
    if charger_current:
      self.assertTrue(charger_current > 0, 'Abnormal charger current')
    if self.args.check_battery_current:
      self.assertTrue(battery_current > 0, 'Abnormal battery current')

  def _CheckDischarge(self, battery_current):
    """Checks current in discharging state"""
    if self.args.check_battery_current:
      self.assertTrue(battery_current < 0, 'Abnormal battery current')

  def _SetCharge(self, update_ui=True):
    """Sets charger state to CHARGE"""
    if update_ui:
      self._template.SetState(_CHARGE_TEXT)
    try:
      self._power.SetChargeState(self._power.ChargeState.CHARGE)
    except Exception, e:
      self.fail('Cannot set charger state to CHARGE on this board. %s' % e)
    else:
      time.sleep(1)

  def _SetDischarge(self):
    """Sets charger state to DISCHARGE"""
    self._template.SetState(_DISCHARGE_TEXT)
    try:
      self._power.SetChargeState(self._power.ChargeState.DISCHARGE)
    except Exception, e:
      self.fail('Cannot set charger state to DISCHARGE on this board. %s' % e)
    else:
      time.sleep(1)

  def _GetSpec(self, charge_change, timeout_secs, load=None):
    """Gets Spec with default load value set as number of cpus"""
    if load is None:
      load = self._dut.info.cpu_count
    return Spec(charge_change, timeout_secs, load)

  def runTest(self):
    self._ui.RunInBackground(self._runTest)
    self._ui.Run()

  def _runTest(self):
    """Main entrance of charger test."""
    self._CheckPower()
    charge = self._GetCharge(self.args.use_percentage)

    min_charge = self._NormalizeCharge(self._min_starting_charge)
    max_charge = self._NormalizeCharge(self._max_starting_charge)

    if charge < min_charge:
      start_charge_diff = min_charge - charge
    elif charge > max_charge:
      start_charge_diff = max_charge - charge
    else:
      start_charge_diff = None

    # Try to meet start_charge_diff as soon as possible.
    # When trying to charge, use 0 load.
    # When trying to discharge, use full load.
    if start_charge_diff:
      self._RegulateCharge(
          self._GetSpec(start_charge_diff,
                        self.args.starting_timeout_secs,
                        0 if start_charge_diff > 0 else None))
    # Start testing the specs when battery charge is between
    # min_starting_charge_pct and max_starting_charge_pct.
    for spec in self.args.spec_list:
      self._RegulateCharge(self._GetSpec(*spec))

  def tearDown(self):
    # Must enable charger to charge or we will drain the battery!
    self._SetCharge(update_ui=False)
