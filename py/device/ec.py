# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""System EC service provider.

This module provides accessing Embedded Controller (EC) on a device.
"""

import re

from cros.factory.device import device_types


class EmbeddedController(device_types.DeviceComponent):
  """System module for embedded controller."""

  # Regular expression for parsing ectool output.
  I2C_READ_RE = re.compile(r'I2C port \d+ at \S+ offset \S+ = (0x[0-9a-f]+)')
  FIRMWARE_COPY = re.compile(r'^Firmware copy:\s*(\S+)\s*$', re.MULTILINE)
  RO_VERSION_RE = re.compile(r'^RO version:\s*(\S+)\s*$', re.MULTILINE)
  RW_VERSION_RE = re.compile(r'^RW version:\s*(\S+)\s*$', re.MULTILINE)

  def _GetOutput(self, command):
    result = self._device.CallOutput(command)
    return result.strip() if result is not None else ''

  def GetECVersion(self):
    """Gets the active EC firmware version.

    Returns:
      A string of the active EC firmware version.
    """
    ec_version = self._GetOutput(['ectool', 'version'])
    match = self.FIRMWARE_COPY.search(ec_version)
    if not match:
      raise self.Error(f'Unexpected output from "ectool version": {ec_version}')

    if match.group(1) == 'RO':
      return self.GetROVersion()
    if match.group(1) == 'RW':
      return self.GetRWVersion()
    raise self.Error(
        f'Unexpected firmware copy from "ectool version": {ec_version}')

  def GetROVersion(self):
    """Gets the EC RO firmware version.

    Returns:
      A string of the EC RO firmware version.
    """
    ec_version = self._GetOutput(['ectool', 'version'])
    match = self.RO_VERSION_RE.search(ec_version)
    if match:
      return match.group(1)
    raise self.Error(
        'Unexpected output from "ectool version": %s' % ec_version)

  def GetRWVersion(self):
    """Gets the EC RW firmware version.

    Returns:
      A string of the EC RW firmware version.
    """
    ec_version = self._GetOutput(['ectool', 'version'])
    match = self.RW_VERSION_RE.search(ec_version)
    if match:
      return match.group(1)
    raise self.Error(
        'Unexpected output from "ectool version": %s' % ec_version)

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
      raise self.Error('Unable to say hello: %s' % e)
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
      raise self.Error('Unable to read from I2C: %s' % e)

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
      raise self.Error('Unable to write to I2C: %s' % e)
