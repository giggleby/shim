# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import logging
import os
import re
import statistics
import typing

from cros.factory.device import device_types
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


IIO_DEVICES_PATTERN = '/sys/bus/iio/devices/iio:device*'
LABEL_FROM_LOCATION = {
    'base': 'accel-base',
    'lid': 'accel-display',
    'camera': 'accel-camera'
}

class SensorError(device_types.DeviceException):
  TEMPLATE = ('%s To resolve this, modify the driver and pass the '
              'sensor_iioservice.go tast test.')

  def __init__(self, messages):
    super().__init__(SensorError.TEMPLATE % messages)


class SensorState(str, enum.Enum):
  ON = '1'
  OFF = '0'

  def __str__(self):
    return self.name


def FindDevice(dut, path_pattern, allow_multiple=False, **attr_filter):
  """Find device under given path.

  Args:
    path_pattern: The path to search, can contain wildcards.
    attr_filter: A filter to filter out unwanted devices. If the value of the
      attribute is None then only check if the path exists.
    allow_multiple: bool. If True, the function will return a list of devices
      that match the given criteria. Otherwise, the function will raise an
      exception if there is more than one matching device.

  Returns:
    String of the path of the matched device.
    List of the matched devices if allow_multiple is `True`.

  Raises:
    DeviceException if no device found.
    DeviceException if more than one device found and allow_multiple is `False`.
  """
  devices = []
  for path in dut.Glob(path_pattern):
    match = True
    for name, value in attr_filter.items():
      try:
        attr_path = dut.path.join(path, name)
        if value is None:
          if not dut.path.exists(attr_path):
            match = False
            break
        elif dut.ReadSpecialFile(attr_path).strip() != value:
          match = False
          break
      except Exception:
        match = False
    if match:
      devices.append(path)

  if not devices:
    raise device_types.DeviceException(
        f'Device with constraint {attr_filter!r} not found')
  if allow_multiple:
    return devices
  if len(devices) > 1:
    raise device_types.DeviceException(
        f'Multiple devices found with constraint {attr_filter!r}')
  return devices[0]


class BasicSensorController(device_types.DeviceComponent):
  """A sensor controller that only supports direct read."""

  @type_utils.ClassProperty
  def raw_to_sys_weight(self):
    """The unit transformation weight between system and raw values."""
    return 1.0

  def __init__(self, dut, name, location, signal_names, scale=False):
    """Constructor.

    Args:
      dut: The DUT instance.
      name: The name attribute of sensor.
      location: The location attribute of sensor.
      signal_names: A list of signals to read.
      scale: Whether to scale the return value.
    """
    super().__init__(dut)
    self.signal_names = signal_names
    self.location = location
    try:
      # TODO(jimmysun) Remove searching location after all boards are using
      # kernel 6.1+.
      self._iio_path = FindDevice(self._device, IIO_DEVICES_PATTERN, name=name,
                                  location=location)
    except device_types.DeviceException:
      if location not in LABEL_FROM_LOCATION:
        raise
      self._iio_path = FindDevice(self._device, IIO_DEVICES_PATTERN, name=name,
                                  label=LABEL_FROM_LOCATION[location])
    self.scale = 1.0 if not scale else float(self._GetSysfsValue('scale'))

  def CleanUpCalibrationValues(self):
    """Clean up calibration values.

    The sysfs trigger only captures calibrated input values, so we reset
    the calibration to allow reading raw data from a trigger.
    """
    for signal_name in self.signal_names:
      self._SetSysfsValue(f'{signal_name}_calibbias', '0')

  def CalculateCalibrationBias(self, data, orientations=None):
    # Calculating calibration data.
    if not orientations:
      orientations = {}

    calib_bias = {}
    for signal_name in data:
      ideal_value = orientations.get(signal_name, 0.0)
      current_calib_bias = (
          int(self._GetSysfsValue(f'{signal_name}_calibbias')) /
          self.raw_to_sys_weight)
      # Calculate the difference between the ideal value and actual value
      # then store it into _calibbias.  In release image, the raw data will
      # be adjusted by _calibbias to generate the 'post-calibrated' values.
      calib_bias[signal_name + '_' + self.location + '_calibbias'] = (
          ideal_value - data[signal_name] + current_calib_bias)
    return calib_bias

  def UpdateCalibrationBias(self, calib_bias):
    """Update calibration bias to RO_VPD

    Args:
      calib_bias: A dict of calibration bias, in m/s^2.
        E.g., {'in_accel_x_base_calibbias': 0.1,
               'in_accel_y_base_calibbias': -0.2,
               'in_accel_z_base_calibbias': 0.3}
    """
    # Writes the calibration results into ro vpd.
    logging.info('Calibration results: %s.', calib_bias)
    scaled = {
        k: str(int(v * self.raw_to_sys_weight))
        for k, v in calib_bias.items()
    }
    self._device.vpd.ro.Update(scaled)
    mapping = []
    for signal_name in self.signal_names:
      mapping.append((f'{signal_name}_{self.location}_calibbias',
                      f'{signal_name}_calibbias'))
    for vpd_entry, sysfs_entry in mapping:
      self._SetSysfsValue(sysfs_entry, scaled[vpd_entry])

  def _GetRepresentList(self) -> list:
    """Returns a list of strings that represents the contents."""
    return [
        f'iio_path={self._iio_path!r}',
        f'signal_names={self.signal_names!r}',
        f'scale={self.scale!r}',
    ]

  def __repr__(self) -> str:
    inner = ',\n'.join(f'    {element}' for element in self._GetRepresentList())
    return f'{self.__class__.__name__}(\n{inner})'

  def _GetSysfsValue(self, filename, path=None) -> typing.Union[str, None]:
    """Read the content of given path.

    Args:
      filename: name of the file to read.
      path: Path to read the given filename, default to the path of
        current iio device.

    Returns:
      A string as stripped contents, or None if error.
    """
    if path is None:
      path = self._iio_path
    try:
      return self._device.ReadFile(os.path.join(path, filename)).strip()
    except Exception:
      return None

  def _SetSysfsValue(self, filename, value, check_call=True, path=None):
    """Assigns corresponding values to a list of sysfs.

    Args:
      filename: name of the file to write.
      value: the value to be write.
      path: Path to write the given filename, default to the path of
        current iio device.
    """
    if path is None:
      path = self._iio_path
    try:
      self._device.WriteFile(os.path.join(path, filename), value)
    except Exception:
      if check_call:
        raise

  def GetSamplingFrequencies(self):
    """Returns the sampling frequencies in Hz.

    Returns:
      A tuple of 2 floats, the minimum frequency and the maximum frequency.

    Raises:
      SensorError if sampling_frequency_available does not exist or there is a
      format error.
    """
    node_name = 'sampling_frequency_available'
    raw_frequencies = self._GetSysfsValue(node_name)
    if raw_frequencies is None:
      raise SensorError(f'{node_name!r} does not exist.')
    frequencies = raw_frequencies.split()
    if not frequencies:
      raise SensorError(f'{node_name!r} is empty.')
    try:
      frequencies = tuple(map(float, frequencies))
    except ValueError:
      raise SensorError(
          f'Can not convert {node_name!r} to floating point numbers. '
          f'{raw_frequencies!r}.') from None
    if len(frequencies) == 1:
      result = (frequencies[0], frequencies[0])
    elif len(frequencies) >= 2:
      if frequencies[0] == 0.0:
        result = (frequencies[1], frequencies[-1])
      else:
        result = (frequencies[0], frequencies[-1])
      if result[0] > result[1]:
        raise SensorError(
            f'The minimum frequency:{result[0]} is larger than the maximum '
            f'frequency:{result[1]}.')
    return result

  def GetData(self, capture_count: int = 1, sample_rate: float = 20.0,
              average: bool = True):
    """Returns (averaged) sensor data.

    Use `iioservice_simpleclient` to capture the sensor data.

    Args:
      capture_count: how many records to read to compute the average.
      sample_rate: sample rate in Hz to read data from sensors. If it is None,
        set to the maximum frequency.
      average: return the average of data or not.

    Returns:
      A dict of the format {'signal_name': value}
      if `average=True`, value will be a single number.
      E.g., {'in_accel_x': 0,
             'in_accel_y': 0,
             'in_accel_z': 9.8}
      if `average=False`, it will be a list with length of `capture_count`.
      E.g., {'in_accel_x': [0.0, 0.0, -0.1],
             'in_accel_y': [0.0, 0.1, 0.0],
             'in_accel_z': [9.8, 9.7, 9.9]}

    Raises:
      Raises SensorError if there is no calibration value in VPD.
    """
    # Initializes the returned dict.
    ret = {signal_name: 0.0
           for signal_name in self.signal_names}

    def ToChannelName(signal_name):
      """Transform the signal names (in_(accel|anglvel)_(x|y|z)) to the channel
      names used in iioservice ((accel|anglvel)_(x|y|z))."""

      return signal_name[3:] if signal_name.startswith('in_') else signal_name

    iioservice_channels = [
        ToChannelName(signal_name) for signal_name in self.signal_names
    ]

    # We only test `iioservice_simpleclient` with maximum frequency in
    # sensor_iioservice_hard.go. Use maximum frequency by default to make sure
    # that our tests are using tested commands.
    if sample_rate is None:
      frequencies = self.GetSamplingFrequencies()
      sample_rate = frequencies[1]

    iioservice_cmd = [
        'iioservice_simpleclient',
        f"--channels={' '.join(iioservice_channels)}",
        f'--frequency={sample_rate:f}',
        f"--device_id={int(self._GetSysfsValue('dev').split(':')[1])}",
        f'--samples={int(capture_count)}'
    ]
    logging.info('iioservice_simpleclient command: %r', iioservice_cmd)

    # Reads the captured data.
    proc = process_utils.CheckCall(iioservice_cmd, read_stderr=True)
    for signal_name in self.signal_names:
      channel_name = ToChannelName(signal_name)
      matches = re.findall(f'(?<={channel_name}'
                           r': )-?\d+', proc.stderr_data)
      if len(matches) != capture_count:
        error_msg = ('Failed to read channel "%s" from iioservice_simpleclient.'
                     'Expect %d data, but %d captured. stderr:\n%s',
                     channel_name, capture_count, len(matches),
                     proc.stderr_data)
        logging.error(error_msg)
        raise SensorError(error_msg)
      logging.info('Getting %d data on channel %s: %s', len(matches),
                   channel_name, matches)

      ret[signal_name] = [int(value) * self.scale for value in matches]

      # Calculates average value and convert to SI unit.
      if average:
        ret[signal_name] = statistics.mean(ret[signal_name])

    if average:
      logging.info('Average of %d data: %s', capture_count, ret)

    return ret
