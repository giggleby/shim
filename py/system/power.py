#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import os

from cros.factory.test.utils import Enum, ReadOneLine

class PowerException(Exception):
  pass


class Power(object):
  # Power source types
  PowerSource = Enum(['BATTERY', 'MAINS'])

  _sys = '/sys'

  def __init__(self):
    self._battery_path = None
    self._current_state = None

  def FindPowerPath(self, power_source):
    '''Find battery path in sysfs.'''
    if power_source == self.PowerSource.BATTERY:
      power_type = 'Battery'
    else:
      power_type = 'Mains'
    for p in glob.glob(os.path.join(self._sys, "class/power_supply/*/type")):
      if ReadOneLine(p) == power_type:
        return os.path.dirname(p)
    raise PowerException("Cannot find %s" % power_type)

  def CheckACPresent(self):
    '''Check if AC power is present.'''
    try:
      p = self.FindPowerPath(self.PowerSource.MAINS)
      return ReadOneLine(os.path.join(p, "online")) == "1"
    except (PowerException, IOError):
      return False

  def CheckBatteryPresent(self):
    '''Check if battery is present and also set battery path.'''
    try:
      self._battery_path = self.FindPowerPath(self.PowerSource.BATTERY)
      return True
    except PowerException:
      return False

  def GetBatteryAttribute(self, attribute_name):
    '''Get a battery attribute.

    Args:
      attribute_name: The name of attribute in sysfs.

    Returns:
      Content of the attribute in str.
    '''
    try:
      return ReadOneLine(os.path.join(self._battery_path, attribute_name))
    except IOError:
      # Battery driver is not fully initialized
      return None

  def GetCharge(self):
    '''Get current charge level in mAh.'''
    charge_now = self.GetBatteryAttribute('charge_now')
    if charge_now:
      return int(charge_now) / 1000
    else:
      return None

  def GetChargeFull(self):
    '''Get full charge level in mAh.'''
    charge_full = self.GetBatteryAttribute('charge_full')
    if charge_full:
      return int(charge_full) / 1000
    else:
      return None

  def GetChargePct(self, get_float=False):
    '''Get current charge level in percentage.

    Args:
      get_float: Returns charge percentage in float.

    Returns:
      Charge percentage in int/float.
    '''
    charge_now = self.GetBatteryAttribute('charge_now')
    charge_full = self.GetBatteryAttribute('charge_full')
    if charge_now is None or charge_full is None:
      return None

    if float(charge_full) <= 0:
      return None # Something wrong with the battery
    charge_pct = float(charge_now) * 100.0 / float(charge_full)
    if get_float:
      return charge_pct
    else:
      return round(charge_pct)
