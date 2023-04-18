# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc

from cros.factory.device import device_types


class IHygrometer(device_types.DeviceComponent, abc.ABC):
  """System module for hygrometers."""

  @abc.abstractmethod
  def GetRelativeHumidity(self):
    """Get the relative humidity.

    Returns:
      A float indicating the relative humidity in percentage.
    """
    raise NotImplementedError


class SysFSHygrometer(IHygrometer):
  """System module for hygrometers.

  Implementation for systems which able to read humidities with sysfs api.
  """

  def __init__(self, device, rh_filename_pattern, rh_map=float):
    """Constructor.

    Args:
      device: Instance of cros.factory.device.device_types.DeviceInterface.
      rh_filename_pattern: The glob pattern to find the file containing
          relative humidity information.
      rh_map: A function (str -> float) that translates the content of file
          indicated by "rh_filename_pattern" to relative humidity in
          percentage. Default is float.
    """
    super().__init__(device)
    candidates = self._device.Glob(rh_filename_pattern)
    assert len(candidates) == 1, 'Not having exactly one candidate.'
    self._rh_filename = candidates[0]
    self._rh_map = rh_map

  def GetRelativeHumidity(self):
    """See IHygrometer.GetRelativeHumidity."""
    try:
      return self._rh_map(self._device.ReadFile(self._rh_filename))
    except Exception as e:
      raise self.Error(f'Unable to get relative humidity: {e}')
