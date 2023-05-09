# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Generic LED components."""

import enum
import logging
import re

from cros.factory.device import device_types


_PATTERN = re.compile(r'\t([a-z]+)\t: (0x[0-9A-Fa-f]+)\n')
"""The pattern of entries of output of 'ectool led <name> query'"""

class LED(device_types.DeviceComponent):
  """LED control using Chrome OS ectool."""

  class Color(str, enum.Enum):
    """Charger LED colors.

    - ``AUTO``: Use the default logic to select the LED color.
    - ``OFF``: Turn the LED off.
    - others: The respective colors.
    """
    AUTO = 'AUTO'
    OFF = 'OFF'
    RED = 'RED'
    GREEN = 'GREEN'
    BLUE = 'BLUE'
    YELLOW = 'YELLOW'
    WHITE = 'WHITE'
    AMBER = 'AMBER'

    def __str__(self):
      return self.name

  class CrOSIndexes(str, enum.Enum):
    """All LED names published by `ectool` today.

    Run `ectool led non-exist x` or look up src/platform/ec/util/ectool.c for
    latest known names.

    Note 'SYSRQ DEBUG' is one single index with space in name, not typo.
    """
    BATTERY = 'BATTERY'
    POWER = 'POWER'
    ADAPTER = 'ADAPTER'
    LEFT = 'LEFT'
    RIGHT = 'RIGHT'
    RECOVERY_HWREINIT = 'RECOVERY_HWREINIT'
    SYSRQ_DEBUG = 'SYSRQ DEBUG'

    def __str__(self):
      return self.value

  Index = None
  """List of LEDs available on DUT. Usually a subset from CrOSIndexes."""

  def __init__(self, device):
    """Probe all maximum brightnesses in advance."""
    super().__init__(device)
    self.led_infoes = {}
    self._GetLEDInfo()

    if self.Index is None:
      self.Index = tuple(self.led_infoes.keys())

  def _GetLEDInfo(self):
    for index in self.CrOSIndexes:
      output = self._device.CallOutput(
          ['ectool', 'led', index.lower(), 'query'])
      if output is None:
        continue

      self.led_infoes[index] = {
          color: int(brightness, 0)
          for color, brightness in _PATTERN.findall(output)
          if int(brightness, 0)
      }
      self.led_infoes[index][self.Color.OFF] = 0

  def _CheckSetColorParameters(self, color, led_name, brightness):
    """Check parameters."""
    if led_name is not None and led_name.upper() not in self.Index:
      raise ValueError(f'Invalid led name: {led_name!r}')
    if color not in self.Color.__members__:
      raise ValueError(f'Invalid color: {color!r}')
    if brightness is not None:
      if not isinstance(brightness, int):
        raise TypeError(f'Invalid brightness: {brightness!r}')
      # pylint: disable=superfluous-parens
      if not (0 <= brightness <= 100):
        raise ValueError(
            f'brightness ({int(brightness)}) out-of-range [0, 100]')

  def SetColor(self, color, led_name=None, brightness=None):
    """Sets LED color.

    Args:
      color: LED color of type LED.Color enum.
      led_name: target LED name, or None for all.
      brightness: LED brightness in percentage [0, 100].
          If color is 'auto' or 'off', brightness is ignored.
    """
    self._CheckSetColorParameters(color, led_name, brightness)
    if brightness is None:
      brightness = 100

    for name in [led_name] if led_name else self.Index:
      self._SetColor(color, name, brightness)

  def _SetColor(self, color, led_name, brightness):
    """Sets one LED color.

    Args:
      color: LED color of type LED.Color enum.
      led_name: target LED name.
      brightness: LED brightness in percentage [0, 100].
          If color is 'auto' or 'off', brightness is ignored.
    """
    try:
      if color in [self.Color.AUTO, self.Color.OFF]:
        color_brightness = color.lower()
      else:
        max_brightness = self.led_infoes[led_name][color.lower()]
        scaled_brightness = int(round(brightness / 100.0 * max_brightness))
        color_brightness = f'{color.lower()}={int(scaled_brightness)}'
    except Exception:
      logging.exception('Failed deciding LED command for %r (%r,%r)',
                        led_name, color, brightness)
      raise

    try:
      self._device.CheckCall(
          ['ectool', 'led', led_name.lower(), color_brightness])
    except Exception:
      logging.exception(
          'Unable to set LED %r to %r', led_name, color_brightness)
      raise


class BatteryLED(LED):
  """Devices with only Battery LED (usually Tablet or Chromebook)."""
  Index = (LED.CrOSIndexes.BATTERY, )


class PowerLED(LED):
  """Devices with only Power LED (usually Chromebox)."""
  Index = (LED.CrOSIndexes.POWER, )


class BatteryPowerLED(LED):
  """Devices with Battery and Power LEDs (most recent x86 Chromebooks)."""
  Index = (LED.CrOSIndexes.BATTERY, LED.CrOSIndexes.POWER)


class BatteryPowerAdapterLED(LED):
  """Devices with Battery, Power and Adapter LEDs. (older Chromebooks)."""
  Index = (LED.CrOSIndexes.BATTERY, LED.CrOSIndexes.POWER,
           LED.CrOSIndexes.ADAPTER)


class LeftRightLED(LED):
  """Devices with only Left and Right LEDs (modern Chromebooks with 2 TypeC)."""
  Index = (LED.CrOSIndexes.LEFT, LED.CrOSIndexes.RIGHT)


class LeftRightPowerLED(LED):
  """Devices with Left, Right and Power LEDs.

     Modern convertible Chromebooks with 2 TypeC and power button with LED.
  """
  Index = (LED.CrOSIndexes.LEFT, LED.CrOSIndexes.RIGHT, LED.CrOSIndexes.POWER)


class PWMLeftRightLED(LED):
  """Devices with only Left and Right LEDs which are controlled by PWM."""
  Index = (LED.CrOSIndexes.LEFT, LED.CrOSIndexes.RIGHT)
  DefaultDutyMap = {
      LED.CrOSIndexes.LEFT: 65535,
      LED.CrOSIndexes.RIGHT: 0,
      None: 32767
  }

  def __init__(self, device, ectool_led_name=LED.CrOSIndexes.POWER,
               pwm_idx=3, duty_map=None):
    """Construct PWMLeftRightLED.

    Args:
      device: The sys_interface.
      ectool_led_name: The led name in ectool.
      pwm_idx: The index of 'ectool pwmsetduty'.
      duty_map: The map from led_name to duty value of 'ectool pwmsetduty'.
    """
    # pylint: disable=super-init-not-called
    # pylint: disable=non-parent-init-called
    device_types.DeviceComponent.__init__(self, device)
    self.led_infoes = {}
    self._GetLEDInfo()
    self._ectool_led_name = ectool_led_name
    self._pwm_idx = pwm_idx
    self._duty_map = duty_map or self.DefaultDutyMap
    if not set(self._duty_map).issuperset(list(self.Index) + [None]):
      raise ValueError(f'Invalid duty map: {self._duty_map!r}')

  def SetColor(self, color, led_name=None, brightness=None):
    """See LED.SetColor."""
    self._CheckSetColorParameters(color, led_name, brightness)
    if brightness is None:
      brightness = 100

    self._SetColor(color, self._ectool_led_name, brightness)

    if color == self.Color.AUTO or led_name not in self._duty_map:
      led_name = None
    duty_value = self._duty_map[led_name]

    self._device.CheckCall(
        ['ectool', 'pwmsetduty', str(self._pwm_idx), str(duty_value)])
