#!/usr/bin/env python
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import logging
import os

import factory_common  # pylint: disable=unused-import
from cros.factory.device import component
from cros.factory.device import sensor_utils


_DEFAULT_MIN_DELAY = 0.2


class AmbientLightSensorException(Exception):
  pass


class AmbientLightSensorController(sensor_utils.BasicSensorController):

  def __init__(self, dut, name, location):
    """Constructor.

    Args:
      dut: The DUT instance.
      name: The name attribute of sensor.
      location: The location attribute of sensor.
    """
    super(AmbientLightSensorController, self).__init__(
        dut, name, location, ['in_illuminance_raw', 'in_illuminance_calibbias',
                              'in_illuminance_calibscale'])
    self.calib_signal_names = [
        'in_illuminance_calibbias', 'in_illuminance_calibscale']
    self.location = location

  def _SetSysfsValue(self, signal_name, value):
    try:
      self._dut.WriteSpecialFile(
          os.path.join(self._iio_path, signal_name), value)
    except Exception as e:
      raise AmbientLightSensorException(e.message)

  def _GetSysfsValue(self, signal_name):
    try:
      return self._dut.ReadSpecialFile(os.path.join(
          self._iio_path, signal_name)).strip()
    except Exception as e:
      raise AmbientLightSensorException(e.message)

  def CleanUpCalibrationValues(self):
    """Cleans up calibration values."""
    self._SetSysfsValue('in_illuminance_calibbias', '0.0')
    self._SetSysfsValue('in_illuminance_calibscale', '1.0')

  def GetCalibrationValues(self):
    """Reads the calibration values from sysfs."""
    vals = {}
    for signal_name in self.calib_signal_names:
      vals[signal_name] = float(self._GetSysfsValue(signal_name))
    return vals

  def SetCalibrationValue(self, signal_name, value):
    """Sets the calibration values to sysfs."""
    if signal_name not in self.calib_signal_names:
      raise KeyError(signal_name)
    try:
      self._SetSysfsValue(signal_name, value)
    except Exception as e:
      raise AmbientLightSensorException(e.message)

  def SetCalibrationIntercept(self, value):
    """Sets the calibration bias to sysfs."""
    try:
      self._SetSysfsValue('in_illuminance_calibbias', str(value))
    except Exception as e:
      raise AmbientLightSensorException(e.message)

  def SetCalibrationSlope(self, value):
    """Sets the calibration scale to sysfs."""
    try:
      self._SetSysfsValue('in_illuminance_calibscale', str(value))
    except Exception as e:
      raise AmbientLightSensorException(e.message)

  def GetLuxValue(self):
    """Reads the LUX raw value from sysfs."""
    try:
      return int(self._GetSysfsValue('in_illuminance_raw'))
    except Exception as e:
      logging.exception('Failed to get illuminance value')
      raise AmbientLightSensorException(e.message)

  def ForceLightInit(self):
    """Froce als to apply the vpd value."""
    try:
      device_name = os.path.basename(self._iio_path)
      self._dut.CheckCall('/lib/udev/light-init.sh', device_name, 'illuminance')
    except Exception as e:
      logging.exception('Failed to invoke light-init.sh (%s, illuminance)',
                        device_name)
      raise AmbientLightSensorException(e.message)


class AmbientLightSensor(component.DeviceComponent):
  """AmbientLightSensor (ALS) component module."""

  def GetController(self, name='cros-ec-light', location='lid'):
    """Gets a controller with specified arguments.

    See AmbientLightSensorController for more information.
    """
    return AmbientLightSensorController(self._dut, name, location)
