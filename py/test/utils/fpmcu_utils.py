# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Fingerprint MCU utilities"""

import enum
import logging
import re
import subprocess
import time
from typing import Dict, List, Optional, Union, overload

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


class ImageName(enum.Enum):
  RO = 'RO'
  RW = 'RW'
  UNKNOWN = 'unknown'

  @classmethod
  def FromEctoolOutput(cls, image_name: str) -> 'ImageName':
    image_name_mapping: Dict[str, ImageName] = dict(
        {e.value: e
         for e in ImageName}, **{'?': ImageName.UNKNOWN})
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


class FpmcuDevice:
  # Select the Fingerprint MCU cros_ec device
  CROS_FP_ARG = "--name=cros_fp"
  # Regular expression for parsing ectool output.
  RO_VERSION_RE = re.compile(r'^RO version:\s*(\S+)\s*$', re.MULTILINE)
  RW_VERSION_RE = re.compile(r'^RW version:\s*(\S+)\s*$', re.MULTILINE)
  CHIPINFO_NAME_RE = re.compile(r'name:\s*(\S+)\s*$', re.MULTILINE)
  FPINFO_MODEL_RE = re.compile(
      r'^Fingerprint sensor:\s+vendor.+model\s+(\S+)\s+version', re.MULTILINE)
  FPINFO_VENDOR_RE = re.compile(
      r'^Fingerprint sensor:\s+vendor\s+(\S+)\s+product', re.MULTILINE)
  FPINFO_ERRORS_RE = re.compile(r'^Error flags:\s*(\S*)$', re.MULTILINE)

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

  def FpmcuCommand(self, command, *args, encoding='utf-8'):
    """Executes a host command on the FPMCU.

    Args:
      command: The name of the ectool command.

    Returns:
      The stdout.

    Raises:
      FpmcuCommandError: If the exit code is non-zero.
    """
    cmdline = ['ectool', self.CROS_FP_ARG, command] + list(args)
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

  def GetFpmcuName(self):
    """Queries fingerprint MCU name.

    Returns:
      A string for FPMCU part number.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """
    fpmcu_chipinfo = self.FpmcuCommand("chipinfo")
    match_name = self.CHIPINFO_NAME_RE.search(fpmcu_chipinfo)

    if match_name is None:
      raise FpmcuError(f'Unable to retrieve FPMCU chipinfo ({fpmcu_chipinfo})')

    return match_name.group(1)

  def GetFpmcuFirmwareVersion(self):
    """Queries fingerprint MCU firmware version.

    Returns:
      A tuple (ro_ver, rw_ver) for RO and RW firmware versions.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
    """
    fw_version = self.FpmcuCommand("version")
    match_ro = self.RO_VERSION_RE.search(fw_version)
    match_rw = self.RW_VERSION_RE.search(fw_version)
    if match_ro is not None:
      match_ro = match_ro.group(1)
    if match_rw is not None:
      match_rw = match_rw.group(1)
    return match_ro, match_rw

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

    # TODO(wdzeng): Reuse utility `_ExtractTokenFromFpmcuStdout` functions.
    match_errors = self.FPINFO_ERRORS_RE.search(fpinfo)
    if match_errors is None:
      raise FpmcuError('Sensor error flags not found.')

    error_flags = match_errors.group(1)
    if error_flags != '':
      raise FpmcuError(f'Sensor failure: {error_flags}')

  def GetFpSensorInfo(self):
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
    info = self.FpmcuCommand('fpinfo')
    match_vendor = self.FPINFO_VENDOR_RE.search(info)
    match_model = self.FPINFO_MODEL_RE.search(info)

    if match_vendor is None or match_model is None:
      raise FpmcuError(f'Unable to retrieve Sensor info ({info})')
    logging.info('ectool fpinfo:\n%s\n', info)

    self.ValidateFpinfoNoErrorFlags(info)

    return (match_vendor.group(1), match_model.group(1))

  def GetFlashProtectFlags(self) -> int:
    """Queries the flash protect flags.

    Returns: Flash protect flags.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero exit code.
      FpmcuError:
        When underlying FPMCU command replies unexpected message.
    """

    # Execute `ectool --name=cros_fp flashprotect` and observe the stdout. It
    # should be like:
    #
    # ```
    # Flash protect flags: 0x0000040f wp_gpio_asserted ro_at_boot ro_now ...
    # Valid flags:         0x0000083f wp_gpio_asserted ro_at_boot ro_now ...
    # Writable flags:      0x00000000
    # ```
    #
    # We need the flags for `Flash protect flags`. In the above case, it is
    # 0x0000040f.

    if self._cached_flash_protect_flags is not None:
      return self._cached_flash_protect_flags

    fpmcu_stdout = self.FpmcuCommand('flashprotect')
    flags = _ExtractFlagsFromFpmcuStdout(
        r'^Flash protect flags:\s+(0x[0-9a-f]+)', fpmcu_stdout)
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

    # Execute `ectool --name=cros_fp sysinfo` and check if `SYSTEM_IS_LOCKED`
    # flag appears. The stdout is like:
    #
    # ```
    # Reset flags: 0x00000c02
    # Flags: 0x0000000d
    # Firmware copy: 2
    # ```

    fpmcu_stdout = self.FpmcuCommand('sysinfo')
    flags = _ExtractFlagsFromFpmcuStdout(r'^Flags:\s+(0x[0-9a-f]+)',
                                         fpmcu_stdout)
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

  def GetImageName(self) -> ImageName:
    """Queries the image name.

    Returns: Image name.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command returns non-zero status code.
      FpmcuError:
        When underlying FPMCU command replies invalid image name.
    """

    # The image name must be one of 'unknown', 'RO', or 'RW'. Follow the design
    # from EC:
    # go/cros-src/platform/ec/util/ectool.c;l=370;drc=f119e0eb

    # The value of "Firmware copy" must be either an image name mentioned above,
    # or a question mark '?'. The format is `Firmware copy: <value>`. Follow the
    # design from EC:
    # go/cros-src/platform/ec/util/ectool.c;l=1179;drc=f119e0eb

    logging.info('Checking FPMCU image name ...')

    fpmcu_stdout = self.FpmcuCommand('version')

    # The image name should be one of 'RO', 'RW', 'unknown', or '?'.
    image_name = _ExtractTokenFromFpmcuStdout(r'^Firmware copy:\s+(\S+)$',
                                              fpmcu_stdout)

    logging.info('Got FPMCU image name: %s', image_name)
    try:
      return ImageName.FromEctoolOutput(image_name)
    except KeyError as e:
      # Unexpected. None of candidate matches the image name. This happens only
      # if ectool changes its implementation.
      raise FpmcuError(f'Unexpected FPMCU image name: {image_name}') from e

  def GetFpframe(self) -> bytes:
    """Reads the fpframe.

    Returns: The fpframe in bytes.

    Raises:
      FpmcuCommandError:
        When underlying FPMCU command fails to read the fpframe.
    """

    return self.FpmcuCommand('fpframe', 'raw', encoding=None)
