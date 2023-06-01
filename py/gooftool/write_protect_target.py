# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum
import logging
import os
import tempfile

from cros.factory.gooftool import common
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
  AP = 'ap'
  EC = 'ec'
  FPMCU = 'fpmcu'


def CreateWriteProtectTarget(
    target: WriteProtectTargetType) -> 'IWriteProtectTarget':
  if target == WriteProtectTargetType.AP:
    return _APWriteProtectTarget()
  if target == WriteProtectTargetType.EC:
    return _ECWriteProtectTarget()
  if target == WriteProtectTargetType.FPMCU:
    return _FPMCUWriteProtectTarget()
  raise TypeError(f'Cannot create IWriteProtectTarget for {target}.')


class IWriteProtectTarget(abc.ABC):

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
      Boolean value: true if WP is enabled, false if WP is disabled.
    """
    raise NotImplementedError


class _APWriteProtectTarget(IWriteProtectTarget):

  def _InvokeCommand(self, param, ignore_status=False):
    command = ' '.join(['futility flash', param])
    result = common.Shell(command)
    if not (ignore_status or result.success):
      raise WriteProtectError(f'Failed in command: {command}\n{result.stderr}')
    return result

  def SetProtectionStatus(self, enable, skip_enable_check=False):
    self._InvokeCommand('--wp-enable' if enable else '--wp-disable')

    # Verify new WP state
    if self.GetStatus() != enable:
      raise WriteProtectError(
          'AP Software write protection could not be changed')

    if enable and not skip_enable_check:
      # Try to verify write protection by attempting to disable it.
      self._InvokeCommand('--wp-disable', ignore_status=True)
      if not self.GetStatus():
        raise WriteProtectError(
            'AP Software write protection can be disabled. Please make '
            'sure hardware write protection is enabled.')

  def GetStatus(self):
    result = self._InvokeCommand('--wp-status --ignore-hw').stdout.strip()

    if result == 'WP status: enabled':
      return True
    if result == 'WP status: disabled':
      return False
    raise WriteProtectError(f'Unexpected WP status: {result}')


class _ECWriteProtectTarget(IWriteProtectTarget):

  def _InvokeCommand(self, param, ignore_status=False):
    command = ' '.join(['ectool flashprotect', param])
    result = common.Shell(command)
    if not (ignore_status or result.success):
      raise WriteProtectError(f'Failed in command: {command}\n{result.stderr}')
    return result

  def SetProtectionStatus(self, enable, skip_enable_check=False):
    self._InvokeCommand('enable now' if enable else 'disable')

    # Verify new WP state
    if self.GetStatus() != enable:
      raise WriteProtectError(
          'EC Software write protection could not be changed')

    if enable and not skip_enable_check:
      # Try to verify write protection by attempting to disable it.
      self._InvokeCommand('disable', ignore_status=True)
      if not self.GetStatus():
        raise WriteProtectError(
            'EC Software write protection can be disabled. Please make '
            'sure hardware write protection is enabled.')

  def GetStatus(self):
    result = self._InvokeCommand('')
    lines = result.split('\n')

    # First line should be active flags
    if len(lines) < 1 or 'Flash protect flags' not in lines[0]:
      raise WriteProtectError(f'Unexpected ectool output: {result}')

    return 'ro_at_boot' in lines[0]


class _FPMCUWriteProtectTarget(IWriteProtectTarget):

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
