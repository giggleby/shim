# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import math
import os
import re

from cros.factory.device import device_types
from cros.factory.device import sensor_utils
from cros.factory.utils import type_utils


RADIAN_TO_DEGREE = 180 / math.pi


class MotionSensorException(Exception):
  pass


class GyroscopeController(sensor_utils.BasicSensorController):
  """Utility class for gyroscope.

  According to
  https://docs.google.com/document/d/1-ZLlS8oJNkFUA0wCNsPukJOZjwVIWOvs9404ihdEm6M/edit#heading=h.2bak5m7fwmoz
  the unit of (_raw data * scale) is rad/s and the unit of _calibbias is dps.

  Attributes:
    name: the name of the gyroscope, e.g., 'cros-ec-gyro', or None.
      This will be used to lookup a matched name in
      /sys/bus/iio/devices/iio:deviceX/name to get
      the corresponding iio:deviceX.
      At least one of name or location must present.

    location: the location of the accelerometer, e.g., 'base' or 'lid', or
      None. This will be used to lookup a matched location in
      /sys/bus/iio/devices/iio:deviceX/location to get
      the corresponding iio:deviceX.
      At least one of name or location must present.
  """

  @type_utils.ClassProperty
  def raw_to_sys_weight(self):
    """Maps rad/s to dps."""
    return 1024 * RADIAN_TO_DEGREE

  def __init__(self, board, name, location, gyro_id, freq):
    super().__init__(board, name, location,
                     ['in_anglvel_x', 'in_anglvel_y', 'in_anglvel_z'],
                     scale=True)
    self.gyro_id = gyro_id
    self.freq = freq

  def _GetRepresentList(self) -> list:
    """Returns a list of strings that represents the contents."""
    return super()._GetRepresentList() + [
        f'location={self.location!r}',
        f'gyro_id={self.gyro_id!r}',
        f'freq={self.freq!r}',
    ]

  def SetupMotionSensor(self):
    """Set up motion sensor for gyroscope.

    Essentially this method tries to execute this command to do setup:
      ectool motionsense odr ${self.gyro_id} ${self.freq}

    If some values are not properly provided (e.g. gyro sensor id, sampling
    freq), this method will try to get needed information from ectool and
    fill the blanks.

    Note that this method stores gyro info as string type in a local dict,
    so read parameters when you need them in string type (e.g. when doing
    command execution).

    Raises:
      Raise MotionSensorException if failed to setup motion sensor.
    """
    gyro = {}
    base_cmd = ['ectool', 'motionsense']
    gyro_id_path = os.path.join(self._iio_path, "id")

    # Find a default gyro id if it's not set
    if self.gyro_id is None:
      logging.info('gyro_id not set, trying to get default id...')
      self.gyro_id = int(self._device.ReadFile(gyro_id_path))

    gyro['id'] = str(self.gyro_id)
    logging.debug('Using gyro id: %s.', gyro['id'])

    # Query gyro information via ectool then parse
    raw_info_cmd = base_cmd + ['info', gyro['id']]
    try:
      raw_info = self._device.CheckOutput(raw_info_cmd)
      gyro.update(self._ParseGyroInfo(raw_info))
      self._CheckGyroAttr(gyro)
    except Exception as e:
      raise MotionSensorException(
          f'Failed to preprocess gyro info.  {e}') from None

    # Do the real motion sensor setup
    setup_cmd = base_cmd + ['odr', gyro['id'], gyro['freq']]
    try:
      self._device.CheckOutput(setup_cmd)
    except Exception as e:
      raise MotionSensorException(
          f'Failed to set up motion sensor.  {e}') from None

    logging.info('Motion sensor setup done.')

  def _ParseGyroInfo(self, raw_info):
    """Parse the raw dump from `ectool motionsense info ${id}'.

    Args:
      raw_info: a raw string to be parsed from ectool.

    Returns:
      A dict containing parsed result.
    """
    logging.debug('raw_info: %s', raw_info)
    re_dict = {
        'type': re.compile(r'Type:[\s]*(.+)'),
        'location': re.compile(r'Location:[\s]*(.+)'),
        'min_freq': re.compile(r'Min Frequency:[\s]*([\d]+) mHz'),
        'max_freq': re.compile(r'Max Frequency:[\s]*([\d]+) mHz'),
    }
    result = {}

    try:
      for key, re_exp in re_dict.items():
        result[key] = re_exp.search(raw_info).group(1)
    except AttributeError as e:
      raise MotionSensorException(f'Failed to parse key "{key}": {e}') from None

    return result

  def _CheckGyroAttr(self, gyro):
    """Check parameters and warn on those inadequate values.

    In addition, if freq is None (not provided in args), the minimal avaliable
    freq will be adapted here.

    Args:
      gyro: a dict containing gyro information.
    """
    if gyro['type'] != 'gyro':
      raise Exception('Specified sensor is not "gyro" type?  Try setting a'
                      'correct sensor id.')

    if gyro['location'] != self.location:
      raise Exception(
          f"Gyro location mismatched: \"{self.location}\" specified but found\""
          f"{gyro['location']}\".")

    #  Adapt gyro['freq'] to the minimal usable freq if it's None.
    if self.freq is None:
      logging.info('No freq specified, setting to %s', gyro['min_freq'])

      gyro['freq'] = gyro['min_freq']
      self.freq = int(gyro['min_freq'])
    else:
      gyro['freq'] = str(self.freq)

    if self.freq < int(gyro['min_freq']):
      logging.warning('Specified freq < %s, gyro test may fail due to it.  '
                      'Are you sure the setting is correct?', gyro['min_freq'])

    if self.freq > int(gyro['max_freq']):
      logging.warning('Specified freq > %s, gyro test may fail due to it.  '
                      'Are you sure the setting is correct?', gyro['max_freq'])

    logging.debug('Gyro: %s', gyro)


class Gyroscope(device_types.DeviceComponent):
  """Gyroscope component module."""

  def GetController(self, location='base', gyro_id=None, freq=None):
    """Gets a controller with specified arguments.

    See sensor_utils.BasicSensorController for more information.
    """
    return GyroscopeController(self._device, 'cros-ec-gyro', location, gyro_id,
                               freq)
