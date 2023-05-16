# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import statistics

from cros.factory.device import device_types
from cros.factory.device import sensor_utils
from cros.factory.utils import type_utils


_GRAVITY = 9.80665

class AccelerometerException(Exception):
  pass


class AccelerometerController(sensor_utils.BasicSensorController):
  """Utility class for the two accelerometers.

  Attributes:
    name: the name of the accelerometer, e.g., 'cros-ec-accel', or None.
      This will be used to lookup a matched name in
      /sys/bus/iio/devices/iio:deviceX/name to get
      the corresponding iio:deviceX.
      At least one of name or location must present.

    location: the location of the accelerometer, e.g., 'base' or 'lid', or
      None. This will be used to lookup a matched location in
      /sys/bus/iio/devices/iio:deviceX/location to get
      the corresponding iio:deviceX.
      At least one of name or location must present.

  Raises:
    Raises AccelerometerException if there is no accelerometer.
  """

  @type_utils.ClassProperty
  def raw_to_sys_weight(self):
    """Maps m/s^2 to 1/1024G."""
    return 1024 / _GRAVITY

  def __init__(self, board, name, location):
    """Cleans up previous calibration values and stores the scan order.

    We can get raw data from below sysfs:
      /sys/bus/iio/devices/iio:deviceX/in_accel_(x|y|z)_raw.

    However, there is no guarantee that the data will have been sampled
    at the same time. So we use `iioservice_simpleclient` to query the
    sensor data.
    """
    super().__init__(board, name, location,
                     ['in_accel_x', 'in_accel_y', 'in_accel_z'], scale=True)
    self.location = location

  def CalculateCalibrationBias(self, data, orientations=None):
    if not orientations:
      raise AccelerometerException(
          '|orientations| is essential to calculate calibration bias')
    orientations = {k: v * _GRAVITY
                    for k, v in orientations.items()}
    return super().CalculateCalibrationBias(data, orientations)

  @classmethod
  def IsVarianceOutOfRange(cls, data: dict, threshold: float = 5.0):
    """Checks whether the variance of sensor data is higher than the threshold.

    Args:
      data: a dict containing digital output for each signal, in m/s^2.
        E.g., {'in_accel_x': [0.0, 0.0, -0.1],
               'in_accel_y': [0.0, 0.1, 0.0],
               'in_accel_z': [9.8. 9.7, 9.9]}
      threshold: a float indicating maximum value of data variance.

    Returns:
      True if the data variance is higher than the threshold.
    """
    ret = False
    for channel_name, values in data.items():
      if not isinstance(values, list):
        raise TypeError(
            f'Expect a list of values in channel "{channel_name}". Please use '
            'AccelerometerController.GetData(average=False) to get the data')
      data_variance = statistics.variance(values)
      if data_variance > threshold:
        logging.error('data variance=%f too high in channel "%s".(expect < %f)',
                      data_variance, channel_name, threshold)
        ret = True
    return ret

  @classmethod
  def IsWithinOffsetRange(cls, data, orientations, spec_offset):
    """Checks whether the value of sensor data is within the spec or not.

    It is used before calibration to filter out abnormal accelerometers.

    Args:
      data: a dict containing digital output for each signal, in m/s^2.
        E.g., {'in_accel_x': 0,
               'in_accel_y': 0,
               'in_accel_z': 9.8}

      orientations: a dict indicating the orentation in gravity
        (either 0 or -/+1) of the signal.
        E.g., {'in_accel_x': 0,
               'in_accel_y': 0,
               'in_accel_z': 1}
      spec_offset: a tuple of two integers, ex: (0.5, 0.5) indicating the
        tolerance for the digital output of sensors under zero gravity and
        one gravity, respectively.

    Returns:
      True if the data is within the tolerance of the spec.
    """
    ret = True
    for signal_name in data:
      value = data[signal_name]
      orientation = orientations[signal_name]
      # Check the sign of the value for -/+1G orientation.
      if orientation and orientation * value < 0:
        logging.error('The orientation of %s is wrong.', signal_name)
        return False
      # Check the abs value is within the range of -/+ offset.
      index = abs(orientation)
      ideal_value = _GRAVITY * orientation
      if abs(value - ideal_value) > spec_offset[index]:
        logging.error('Signal %s out of range. Detected = %f; Expected = %f',
                      signal_name, value, ideal_value)
        ret = False
    return ret


class Accelerometer(device_types.DeviceComponent):
  """Accelerometer component module."""

  def GetController(self, location):
    """Gets a controller with specified arguments.

    See AccelerometerController for more information.
    """
    return AccelerometerController(self._device, 'cros-ec-accel', location)
