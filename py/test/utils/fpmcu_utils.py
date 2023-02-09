# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Fingerprint MCU utilities"""

import enum
import logging
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple, Union, overload

from cros.factory.utils.sys_interface import SystemInterface


class FpmcuError(Exception):
  """Fpmcu device exception class."""


class FpmcuCommandError(FpmcuError):
  """Fpmcu command exception class."""

  def __init__(self, cmdline: List[str], stdout: Union[str, bytes],
               stderr: Union[str, bytes], returncode: int):
    super().__init__(
        f'cmd: {cmdline!r}, returncode: {int(returncode)}, stdout: {stdout!r}, '
        f'stderr: {stderr!r}')
    self.stdout = stdout
    self.stderr = stderr
    self.returncode = returncode


class FlashProtectFlags(enum.IntEnum):
  # Follow the design from EC:
  # go/cros-src/platform/ec/include/ec_commands.h;l=1815;drc=0b72d42b
  EC_FLASH_PROTECT_RO_AT_BOOT = (1 << 0)
  EC_FLASH_PROTECT_RO_NOW = (1 << 1)
  EC_FLASH_PROTECT_GPIO_ASSERTED = (1 << 3)


class SysinfoFlags(enum.IntEnum):
  # Follow the design from EC:
  # go/cros-src/platform/ec/include/ec_commands.h;l=2028;drc=0b72d42b
  SYSTEM_IS_LOCKED = (1 << 0)


class ImageSlot(enum.Enum):
  RO = 'RO'
  RW = 'RW'
  UNKNOWN = 'unknown'

  @classmethod
  def FromEctoolOutput(cls, image_name: str) -> 'ImageSlot':
    image_name_mapping: Dict[str, ImageSlot] = dict(
        {e.value: e
         for e in ImageSlot}, **{'?': ImageSlot.UNKNOWN})
    return image_name_mapping[image_name]

  def __str__(self):
    return self.value


def _LogFpmcuStdoutOnParseFailed(regexp: str, stdout: str):
  msg_fmt = ('Succeeded to execute FPMCU command but failed to parse the '
             'target. Following is the used regular expression, in multiline '
             'mode.\n\n%s\n\nFollowing is the stdout from the called FPMCU '
             'command.\n\n%s')
  logging.error(msg_fmt, regexp, stdout.strip())


def _ExtractTokenFromFpmcuStdout(regexp: str, stdout: str) -> str:
  """A helper function for extracting a token string from FPMCU command stdout
  with a regular expression.

  Args:
    regexp: A regular expression for parsing.
    command: The name of the ectool command.

  Returns: The parsed flags.

  Raises:
    FpmcuError:
      If there is no matching or contains more than on matchings in the text.
  """

  re_result = list(re.finditer(regexp, stdout, re.MULTILINE))
  if len(re_result) != 1:
    _LogFpmcuStdoutOnParseFailed(regexp, stdout)
    raise FpmcuError(
        'Failed to get the target string from called FPMCU command.')

  matching_groups = re_result[0].groups()
  if len(matching_groups) != 1:
    # This is an internal error caused by an an invalid regular expression. No
    # matter what FPMCU command stdout is, the matching group count should be
    # one if the regular expression is set correctly.
    raise ValueError(
        'Regular expression contains zero or more than one matching groups.')

  return matching_groups[0]


def _ExtractFlagsFromFpmcuStdout(regexp: str, stdout: str) -> int:
  """A helper function for extracting a single set of flags from FPMCU command
  stdout with a regular expression.

  This function assumes that the flags are written in lowercased hexadecimal.

  Args:
    regexp: A regular expression for parsing.
    command: The name of the ectool command.

  Returns: The parsed flags.

  Raises:
    FpmcuError:
      If there is no matching or contains more than on matchings in the text.
  """

  hex_flags = _ExtractTokenFromFpmcuStdout(regexp, stdout)
  try:
    return int(hex_flags, 16)
  except (TypeError, ValueError) as e:
    # A TypeError indicates hex_flags is not of type string; A ValueError
    # indicates hex_flags is a string but not a valid hexadecimal.
    _LogFpmcuStdoutOnParseFailed(regexp, stdout)
    raise FpmcuError(
        'Failed to get the flags from called FPMCU command.') from e


# Select the Fingerprint MCU cros_ec device
_CROS_FP_ARG = '--name=cros_fp'

# Regular expressions for fetching target information.
_RE_CHIPINFO_NAME = r'name:[^\S\r\n]*(\S+)'
_RE_RO_VERSION = r'^RO version:[^\S\r\n]*(\S+)'
_RE_RW_VERSION = r'^RW version:[^\S\r\n]*(\S+)'
_RE_FPINFO_ERROR_FLAGS = r'^Error flags:(.*)$'
_RE_VENDOR_ID = r'^Fingerprint sensor:[^\S\r\n]*vendor\s+(\S+)\s+product'
_RE_SENSOR_ID = r'^Fingerprint sensor:[^\S\r\n]*vendor.+model\s+(\S+)\s+version'
_RE_FLASH_PROTECT_FLAGS = r'^Flash protect flags:[^\S\r\n]*(\S+)'
_RE_SYSINFO_IMAGE_NAME = r'^Flags:[^\S\r\n]*(\S+)'
_RE_VERSION_FW_COPY_NAME = r'^Firmware copy:[^\S\r\n]*(\S+)$'


class FpmcuDevice:

  def __init__(self, dut: SystemInterface):
    self._dut = dut
    self._cached_flash_protect_flags: Optional[int] = None

  @overload
  def FpmcuCommand(self, command: str, *args: str,
                   encoding: str = 'utf-8') -> str:
    ...

  @overload
  def FpmcuCommand(self, command: str, *args: str, encoding: None) -> bytes:
    ...

  def FpmcuCommand(self, command: str, *args: str,
                   encoding: Optional[str] = 'utf-8') -> Union[bytes, str]:
    """Executes a host command on the FPMCU.

    Args:
      command: The name of the ectool command.

    Returns:
      The stdout.

    Raises:
      FpmcuCommandError: If the exit code is non-zero.
    """
    cmdline = ['ectool', _CROS_FP_ARG, command] + list(args)
    process = self._dut.Popen(cmdline, encoding=encoding,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    return_code = process.returncode

    if encoding is not None:
      # If encoding is set then stdout and stderr are strings but not bytes. We
      # can safely trim them.
      stdout = stdout.strip()
      stderr = stderr.strip()

    if return_code == 0:
      return stdout

    raise FpmcuCommandError(cmdline, stdout, stderr, return_code)

  def GetName(self) -> str:
    """Queries fingerprint MCU name.

    Returns:
      A string for FPMCU part number.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """
    # See `FpmcuDeviceTest.testGetName` for example output.
    fpmcu_output = self.FpmcuCommand('chipinfo')

    return _ExtractTokenFromFpmcuStdout(_RE_CHIPINFO_NAME, fpmcu_output)

  def GetFirmwareVersion(self) -> Tuple[str, str]:
    """Queries fingerprint MCU firmware version.

    Returns:
      A tuple (ro_ver, rw_ver) for RO and RW firmware versions.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """
    # See `FpmcuDeviceTest.testGetFirmwareVersion` for example output.
    fpmcu_output = self.FpmcuCommand('version')

    ro_version = _ExtractTokenFromFpmcuStdout(_RE_RO_VERSION, fpmcu_output)
    rw_version = _ExtractTokenFromFpmcuStdout(_RE_RW_VERSION, fpmcu_output)
    return ro_version, rw_version

  def ValidateFpinfoNoErrorFlags(self, fpinfo: Optional[str] = None) -> None:
    """Validates that no error flags are set in fpinfo stdout.

    Args:
      fpinfo: If given, parses error flags from it.

    Raises:
      FpmcuCommandError:
        When `fpinfo` is not set and underlying FPMCU command returns non-zero
        exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message, or when error
        flags are set.
    """
    if fpinfo is None:
      fpinfo = self.FpmcuCommand('fpinfo')

    error_flags = _ExtractTokenFromFpmcuStdout(_RE_FPINFO_ERROR_FLAGS,
                                               fpinfo).strip()
    if error_flags:
      raise FpmcuError(f'Sensor failure: {error_flags}')

  def GetFpSensorInfo(self) -> Tuple[str, str]:
    """Queries the fingerprint sensor identifiers.

    This method also checks that no error flags set.

    Returns:
      A tuple (vendor_id, sensor_id) for vendor ID and sensor ID.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message, or when error
        flags are set.
    """
    # See `FpmcuDeviceTest.testGetFpSensorInfoOnNoErrorFlagsSet` and
    # `FpmcuDeviceTest.testGetFpSensorInfoOnErrorFlagsSet` for example output.
    fpmcu_output = self.FpmcuCommand('fpinfo')

    vendor_id = _ExtractTokenFromFpmcuStdout(_RE_VENDOR_ID, fpmcu_output)
    sensor_id = _ExtractTokenFromFpmcuStdout(_RE_SENSOR_ID, fpmcu_output)
    self.ValidateFpinfoNoErrorFlags(fpmcu_output)
    return vendor_id, sensor_id

  def GetFlashProtectFlags(self) -> int:
    """Queries the flash protect flags.

    Returns: Flash protect flags.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """
    if self._cached_flash_protect_flags is not None:
      return self._cached_flash_protect_flags

    # See `FpmcuDeviceTest.testGetFlashProtectFlagsOnLowercasedHexOutput` for
    # example output.
    fpmcu_stdout = self.FpmcuCommand('flashprotect')
    flags = _ExtractFlagsFromFpmcuStdout(_RE_FLASH_PROTECT_FLAGS, fpmcu_stdout)
    self._cached_flash_protect_flags = flags
    return self._cached_flash_protect_flags

  def IsHWWPEnabled(self) -> bool:
    """Queries if hardware write protection is enabled.

    Returns: True if hardware write protection is enabled; otherwise False.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """

    flags = self.GetFlashProtectFlags()
    return bool(flags & FlashProtectFlags.EC_FLASH_PROTECT_GPIO_ASSERTED)

  def IsSWWPEnabled(self) -> bool:
    """Queries if software write protection is enabled.

    Returns: True if software write protection is enabled; otherwise False.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """

    flags = self.GetFlashProtectFlags()
    return bool(flags & FlashProtectFlags.EC_FLASH_PROTECT_RO_NOW)

  def IsSWWPEnabledOnBoot(self) -> bool:
    """Queries if software write protection will be enabled at the next boot.

    Returns:
      True if software write protection will be enabled at the next boot;
      otherwise False.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """

    flags = self.GetFlashProtectFlags()
    return bool(flags & FlashProtectFlags.EC_FLASH_PROTECT_RO_AT_BOOT)

  def IsSystemLocked(self) -> bool:
    """Queries if the system is locked.

    Returns: True if system is locked; otherwise False.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """
    # Validate if the `system_is_locked()` mentioned below in EC code returns
    # true.
    # go/cros-src/platform/ec/common/system.c;l=178;drc=4c716941

    # See `FpmcuDeviceTest.testIsSystemLockedOnLowercasedHexOutput` for example
    # output.
    fpmcu_stdout = self.FpmcuCommand('sysinfo')
    flags = _ExtractFlagsFromFpmcuStdout(_RE_SYSINFO_IMAGE_NAME, fpmcu_stdout)
    return bool(flags & SysinfoFlags.SYSTEM_IS_LOCKED)

  def Reboot(self) -> None:
    """Reboots the FPMCU.

    Raises:
      FpmcuError:
        When FPMCU fails to reboot.
    """
    logging.info('Rebooting FPMCU ...')

    try:
      self.FpmcuCommand('reboot_ec')
      # The above command must fail because FPMCU is shutdown and cannot give
      # any response. If the above command fail to fail, this is an error.
      raise FpmcuError(
          'Failed to reboot FPMCU. FPMCU gives response on reboot request.')
    except FpmcuCommandError:
      # Expected.
      pass

    # Once the FPMCU is shutdown the cached flash protect flags are no longer
    # valid, so clear it.
    self._cached_flash_protect_flags = None

    # Wait for a delay so that FPMCU has rebooted completely.
    time.sleep(2)
    logging.info('FPMCU rebooted.')

  def RequestToEnableSWWPOnBoot(self) -> None:
    """Sets flashprotect flags such that SWWP will be enabled on next boot."""
    logging.info('Enabling FPMCU software write protection ...')

    try:
      self.FpmcuCommand('flashprotect', 'enable')
    except FpmcuCommandError:
      # TODO(b/245224801): should this error be ignored?
      pass

    # Wait for a delay so that the previous FPMCU command make effect
    # completely.
    time.sleep(2)

    self._cached_flash_protect_flags = None

    logging.info(
        'FPMCU software write protection is enabled. Remember to reboot.')

  def GetImageSlot(self) -> ImageSlot:
    """Queries the image slot.

    Returns: Image slot.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero status code.
      FpmcuError:
        When underlying FPMCU command replies invalid image slot.
    """
    logging.info('Checking FPMCU image slot ...')

    # See `FpmcuDeviceTest.testGetImageSlotForRW` for example output.
    fpmcu_stdout = self.FpmcuCommand('version')

    # The image slot should be one of 'RO', 'RW', 'unknown', or '?'. Follow the
    # design from EC: go/cros-src/platform/ec/util/ectool.c;l=370;drc=f119e0eb
    image_slot = _ExtractTokenFromFpmcuStdout(_RE_VERSION_FW_COPY_NAME,
                                              fpmcu_stdout)

    logging.info('Got FPMCU image slot: %s', image_slot)
    try:
      return ImageSlot.FromEctoolOutput(image_slot)
    except KeyError as e:
      # Unexpected. None of candidate matches the image slot. This happens only
      # if ectool changes its implementation.
      raise FpmcuError(f'Unexpected FPMCU image slot: {image_slot}') from e

  def GetFpframe(self) -> bytes:
    """Reads the fpframe.

    Returns: The fpframe in bytes.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command fails to read the fpframe.
    """

    return self.FpmcuCommand('fpframe', 'raw', encoding=None)
