# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum
import logging
import os
import tempfile

from cros.factory.gooftool import crosfw
from cros.factory.test.utils import fpmcu_utils
from cros.factory.utils import file_utils
from cros.factory.utils import sys_interface
from cros.factory.utils.type_utils import Error


_WP_SECTION = 'WP_RO'


class UnsupportedOperationError(Error):
  """Exception for methods that are not supported."""


class WriteProtectError(Error):
  """Failed to enable write protection."""


class WriteProtectTargetType(enum.Enum):
  AP = 'main'
  EC = 'ec'
  FPMCU = 'fpmcu'


def CreateWriteProtectTarget(
    target: WriteProtectTargetType) -> 'WriteProtectTarget':
  if target == WriteProtectTargetType.AP:
    return _APWriteProtectTarget()
  if target == WriteProtectTargetType.EC:
    return _ECWriteProtectTarget()
  if target == WriteProtectTargetType.FPMCU:
    return _FPMCUWriteProtectTarget()
  raise TypeError(f'Cannot create WriteProtectTarget for {target}.')


class WriteProtectTarget(abc.ABC):

  @abc.abstractmethod
  def SetProtectionStatus(self, enable, skip_enable_check=False):
    """Enables or disables the write protection.

    Args:
      enable: Boolean value, true for enable, false for disable.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def GetStatus(self):
    """Gets the information of the write protection.

    Returns:
      A dictionary containing the status of write protection. The format of the
      dictionary:
        {
          "enabled": Boolean value,
          "offset": non-negative integer,
          "size": non-negative integer,
        }
    """
    raise NotImplementedError


class _FlashromBasedWriteProtectTarget(WriteProtectTarget):

  def __init__(self):
    self._flashrom = self._GetFlashrom()

  def SetProtectionStatus(self, enable, skip_enable_check=False):
    if enable:
      fw = self._GetReferenceFirmware()
      section_data = fw.GetFirmwareImage(
          sections=[_WP_SECTION]).get_section_area(_WP_SECTION)
      offset, size = section_data[0:2]
      self._flashrom.EnableWriteProtection(offset, size,
                                           skip_check=skip_enable_check)
    else:
      self._flashrom.DisableWriteProtection()

  def GetStatus(self):
    return self._flashrom.GetWriteProtectionStatus()._asdict()

  @abc.abstractmethod
  def _GetReferenceFirmware(self):
    """Gets the reference firmware for the target."""
    raise NotImplementedError

  @abc.abstractmethod
  def _GetFlashrom(self):
    """Gets the instance of cros.factory.gooftool.crosfw.Flashrom."""
    raise NotImplementedError


class _APWriteProtectTarget(_FlashromBasedWriteProtectTarget):

  def _GetFlashrom(self):
    return crosfw.Flashrom(crosfw.TARGET_MAIN)

  def _GetReferenceFirmware(self):
    return crosfw.LoadMainFirmware()


class _ECBasedWriteProtectTarget(_FlashromBasedWriteProtectTarget):

  def __init__(self):
    super().__init__()
    self._fw = self._GetReferenceFirmware()

  def SetProtectionStatus(self, enable, skip_enable_check=False):
    self._CheckAvailability()
    super().SetProtectionStatus(enable, skip_enable_check)

  def GetStatus(self):
    self._CheckAvailability()
    return super().GetStatus()

  def _GetReferenceFirmware(self):
    return self._fw

  def _CheckAvailability(self):
    if self._fw.GetChipId() is None:
      # Some EC (mostly PD) does not support "RO_NOW". Instead they will only
      # set "RO_AT_BOOT" when you request to enable RO (These platforms
      # consider --wp-range with right range identical to --wp-enable), and
      # requires a 'ectool reboot_ec RO at-shutdown; reboot' to let the RO
      # take effect. After reboot, "flashrom -p host --wp-status" will return
      # protected range. If you don't reboot, returned range will be (0, 0),
      # and running command "ectool flashprotect" will not have RO_NOW.
      # generic_common.test_list.json provides "EnableECWriteProtect" test
      # group which can be run individually before finalization. Try that out
      # if you're having trouble enabling RO_NOW flag.
      logging.warning('%s not write protected (seems there is no %s flash).',
                      self._fw.target.upper(), self._fw.target.upper())
      raise UnsupportedOperationError


class _ECWriteProtectTarget(_ECBasedWriteProtectTarget):

  def _GetFlashrom(self):
    return crosfw.Flashrom(crosfw.TARGET_EC)

  def _GetReferenceFirmware(self):
    return crosfw.LoadEcFirmware()


class _FPMCUWriteProtectTarget(WriteProtectTarget):

  FILE_FPFRAME = 'fp.raw'
  FILE_FPFRAME_ERR_MSG = 'error_msg.txt'

  def __init__(self):
    self._fpmcu = fpmcu_utils.FpmcuDevice(sys_interface.SystemInterface())

  def SetProtectionStatus(self, enable, skip_enable_check=False):
    if enable:
      self._EnableWriteProtect()
    else:
      raise UnsupportedOperationError

  def GetStatus(self):
    raise UnsupportedOperationError

  def _EnableWriteProtect(self):
    """Enables the write protection of the FPMCU.

    The write protection, or more specifically, SWWP, is enabled by the
    following steps:

    1. Reboot the FPMCU. We need to make sure the FPMCU state matches the
       initial state.
    2. Do prerequisite checking:
       - HWWP is enabled.
       - SWWP is disabled.
    3. Request to enable SWWP and reboot FPMCU so that SWWP makes effect.
    4. Validate the final FPMCU state:
       - HWWP and SWWP are both enabled.
       - Image in use is 'RW'.
       - System is locked.

    Raises:
      WriteProtectError:
        when fail to enable write protection.
    """

    def _Assert(expected: bool, assert_message: str):
      if expected:
        logging.info('Check %r: OK', assert_message)
      else:
        raise WriteProtectError(f'Check {assert_message!r}: FAILED')

    # Before the enablement, we create a temp dir for saving fpframe and, if
    # failed, error messages.
    temp_dir = tempfile.mkdtemp(prefix='write_protect_fpmcu-', )

    # Reboot the FPMCU. We need to make sure the FPMCU state matches the initial
    # state.
    try:
      self._fpmcu.Reboot()
    except fpmcu_utils.FpmcuError as e:
      raise WriteProtectError(f'Failed to reboot FPMCU: {e.message}') from e

    # Do prerequisite checking.
    _Assert(self._fpmcu.IsHWWPEnabled(), 'FPMCU HWWP is enabled')
    _Assert(not self._fpmcu.IsSWWPEnabled(), 'FPMCU SWWP is disabled')

    # Log fpframe. This provides useful information for debugging if fail to
    # enable the write protection in the further steps.
    self._SaveFpframe(temp_dir)

    # Request to enable SWWP and reboot FPMCU so that SWWP makes effect. But
    # before rebooting, check if flags are updated to the expected state.
    try:
      self._fpmcu.RequestToEnableSWWPOnBoot()
      _Assert(self._fpmcu.IsSWWPEnabledOnBoot(),
              'FPMCU SWWP is enabled on boot')
      self._fpmcu.Reboot()
    except fpmcu_utils.FpmcuError as e:
      raise WriteProtectError(f'Failed to reboot FPMCU: {e.message}') from e

    # Validate the final FPMCU state.
    _Assert(self._fpmcu.IsSWWPEnabled(), 'FPMCU SWWP is enabled')
    _Assert(self._fpmcu.IsHWWPEnabled(), 'FPMCU HWWP is enabled')
    _Assert(self._fpmcu.GetImageSlot() == fpmcu_utils.ImageSlot.RW,
            'FPMCU RW image is active')
    _Assert(self._fpmcu.IsSystemLocked(), 'FPMCU system is locked')

  def _SaveFpframe(self, dest: str) -> None:
    """Saves fpframe under given destination directory, or logs error messages
    if failing to get fpframe.

    Args:
      dest: path to the directory where fpframe or error messages should be
          saved.
    """

    try:
      fpframe = self._fpmcu.GetFpframe()
      path_fpframe = os.path.join(dest, self.FILE_FPFRAME)
      file_utils.WriteFile(path_fpframe, fpframe, encoding=None)
      logging.info('Saved fpframe log: %s', path_fpframe)
    except fpmcu_utils.FpmcuCommandError as e:
      err_msg = e.stderr
      path_fpframe_err_msg = os.path.join(dest, self.FILE_FPFRAME_ERR_MSG)
      file_utils.WriteFile(path_fpframe_err_msg, err_msg)
      logging.info('Saved fpframe err: %s', path_fpframe_err_msg)
      raise WriteProtectError(f'Failed to save fpframe: {err_msg}') from e
