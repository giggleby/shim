# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""System EC service provider.

This module provides accessing Embedded Controller (EC) on a device.
"""

import enum
import re

from cros.factory.device import device_types


class ECFWCopy(str, enum.Enum):
  RO = 'RO'
  RW = 'RW'

class EmbeddedController(device_types.DeviceComponent):
  """System module for embedded controller."""

  # Regular expression for parsing ectool output.
  I2C_READ_RE = re.compile(r'I2C port \d+ at \S+ offset \S+ = (0x[0-9a-f]+)')
  FIRMWARE_COPY_RE = re.compile(r'^Firmware copy:\s*(\S+)\s*$', re.MULTILINE)
  RO_VERSION_RE = re.compile(r'^RO version:\s*(\S+)\s*$', re.MULTILINE)
  RW_VERSION_RE = re.compile(r'^RW version:\s*(\S+)\s*$', re.MULTILINE)
  BUILD_INFO_RE = re.compile(r'^Build info:\s*([^\n]+)\s*$', re.MULTILINE)

  def _GetOutput(self, command):
    result = self._device.CallOutput(command)
    return result.strip() if result is not None else ''

  def _GetVersionInfoWithRegex(self, regex):
    """Calls `ectool version` and searches it using the given regex.

    Returns:
      The matched string.
    """
    ec_version = self._GetOutput(['ectool', 'version'])
    match = regex.search(ec_version)
    if not match:
      raise self.Error(f'Unexpected output from "ectool version": {ec_version}')
    return match.group(1)

  def GetBuildInfo(self):
    """Gets the EC firmware build info.

    Returns:
      A string of the EC firmware build info.
    """
    return self._GetVersionInfoWithRegex(self.BUILD_INFO_RE)

  def GetFirmwareCopy(self):
    """Gets the active EC firmware copy.

    Returns:
      A string of the active EC firmware copy.
    """
    return ECFWCopy(self._GetVersionInfoWithRegex(self.FIRMWARE_COPY_RE))

  def GetActiveVersion(self):
    """Gets the active EC firmware version.

    Returns:
      A string of the active EC firmware version.
    """
    active_firmware_copy = self.GetFirmwareCopy()
    if active_firmware_copy == ECFWCopy.RO:
      return self.GetROVersion()
    if active_firmware_copy == ECFWCopy.RW:
      return self.GetRWVersion()
    raise self.Error(f'Unhandled firmware copy: {active_firmware_copy.value}')

  def GetROVersion(self):
    """Gets the EC RO firmware version.

    Returns:
      A string of the EC RO firmware version.
    """
    return self._GetVersionInfoWithRegex(self.RO_VERSION_RE)

  def GetRWVersion(self):
    """Gets the EC RW firmware version.

    Returns:
      A string of the EC RW firmware version.
    """
    return self._GetVersionInfoWithRegex(self.RW_VERSION_RE)

  def GetECConsoleLog(self):
    """Gets the EC console log.

    Returns:
      A string containing EC console log.
    """
    return self._GetOutput(['ectool', 'console'])

  def GetECPanicInfo(self):
    """Gets the EC panic info.

    Returns:
      A string of EC panic info.
    """
    return self._GetOutput(['ectool', 'panicinfo'])

  def ProbeEC(self):
    """Says hello to EC.
    """
    try:
      if self._device.CallOutput(
          ['ectool', 'hello']).find('EC says hello') == -1:
        raise self.Error('Did not find "EC says hello".')
    except Exception as e:
      raise self.Error(f'Unable to say hello: {e}')
    return True

  def I2CRead(self, port, addr, reg):
    """Reads 16-bit value from I2C bus connected via EC.

    This function cannot access system I2C buses that are not routed via EC.

    Args:
      port: I2C port ID.
      addr: I2C target address.
      reg: Target register address.

    Returns:
      Integer value read from target.
    """
    try:
      ectool_output = self._device.CheckOutput(
          ['ectool', 'i2cread', '16', str(port), str(addr), str(reg)])
      return int(self.I2C_READ_RE.findall(ectool_output)[0], 16)
    except Exception as e:
      raise self.Error(f'Unable to read from I2C: {e}')

  def I2CWrite(self, port, addr, reg, value):
    """Writes 16-bit value to I2C bus connected via EC.

    This function cannot access system I2C buses that are not routed via EC.

    Args:
      port: I2C port ID.
      addr: I2C target address.
      reg: Target register address.
      value: 16-bit value to write.
    """
    try:
      self._device.CheckCall(
          ['ectool', 'i2cwrite', '16', str(port), str(addr), str(reg),
           str(value)])
    except Exception as e:
      raise self.Error(f'Unable to write to I2C: {e}')
