# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum
import logging
import os
import re
import time

from cros.factory.gooftool.common import Shell
from cros.factory.gooftool import crosfw
from cros.factory.test.utils import fpmcu_utils
from cros.factory.utils import file_utils
from cros.factory.utils import sys_interface
from cros.factory.utils.type_utils import Error

_WP_SECTION = 'WP_RO'


class UnsupportedOperationError(Exception):
  pass


class WriteProtectTargetType(enum.Enum):
  AP = 'main'
  EC = 'ec'
  PD = 'pd'
  FPMCU = 'fpmcu'


def CreateWriteProtectTarget(target):
  if target == WriteProtectTargetType.AP:
    return APWriteProtectTarget()
  if target == WriteProtectTargetType.EC:
    return ECWriteProtectTarget()
  if target == WriteProtectTargetType.PD:
    return PDWriteProtectTarget()
  if target == WriteProtectTargetType.FPMCU:
    return _CreateFPMCUWriteProtectTarget()
  raise TypeError(f'Cannot create WriteProtectTarget for {target}.')


class WriteProtectTarget(abc.ABC):

  @abc.abstractmethod
  def SetProtectionStatus(self, enable):
    """Enables or disables the write protection.

    Args:
      enable: Boolean value, true for enable, false for disable.
    """
    raise NotImplementedError


class _FlashromBasedWriteProtectTarget(WriteProtectTarget):

  def __init__(self):
    self._flashrom = self._GetFlashrom()

  def SetProtectionStatus(self, enable):
    if enable:
      fw = self._GetReferenceFirmware()
      section_data = fw.GetFirmwareImage(
          sections=[_WP_SECTION]).get_section_area(_WP_SECTION)
      offset, size = section_data[0:2]
      self._flashrom.EnableWriteProtection(offset, size)
    else:
      self._flashrom.DisableWriteProtection()

  @abc.abstractmethod
  def _GetReferenceFirmware(self):
    """Gets the reference firmware for the target."""
    raise NotImplementedError

  @abc.abstractmethod
  def _GetFlashrom(self):
    """Gets the instance of cros.factory.gooftool.crosfw.Flashrom."""
    raise NotImplementedError


class APWriteProtectTarget(_FlashromBasedWriteProtectTarget):

  def _GetFlashrom(self):
    return crosfw.Flashrom(crosfw.TARGET_MAIN)

  def _GetReferenceFirmware(self):
    return crosfw.LoadMainFirmware()


class _ECBasedWriteProtectTarget(_FlashromBasedWriteProtectTarget):

  def __init__(self):
    super().__init__()
    self._fw = self._GetReferenceFirmware()

  def SetProtectionStatus(self, enable):
    self._CheckAvailability()
    super().SetProtectionStatus(enable)

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


class ECWriteProtectTarget(_ECBasedWriteProtectTarget):

  def _GetFlashrom(self):
    return crosfw.Flashrom(crosfw.TARGET_EC)

  def _GetReferenceFirmware(self):
    return crosfw.LoadEcFirmware()


class PDWriteProtectTarget(_ECBasedWriteProtectTarget):

  def _GetFlashrom(self):
    return crosfw.Flashrom(crosfw.TARGET_PD)

  def _GetReferenceFirmware(self):
    return crosfw.LoadPDFirmware()


class _FPMCUWriteProtectTarget(WriteProtectTarget):

  def SetProtectionStatus(self, enable):
    if enable:
      self._EnableWriteProtect()
    else:
      raise UnsupportedOperationError

  def _EnableWriteProtect(self):
    fpmcu = fpmcu_utils.FpmcuDevice(sys_interface.SystemInterface())

    # Reset the FPMCU state.
    self._RebootEC(fpmcu)

    # Check if SWWP is disabled but HWWP is enabled.
    self._CheckPattern(r'^Flash protect flags:\s*0x00000008 wp_gpio_asserted$',
                       fpmcu.FpmcuCommand('flashprotect'))
    if os.path.exists('/tmp/fp.raw'):
      os.remove('/tmp/fp.raw')
    fp_frame = fpmcu.FpmcuCommand('fpframe', 'raw', encoding=None)
    file_utils.WriteFile('/tmp/fp.raw', fp_frame)

    # Enable SWWP.
    try:
      fpmcu.FpmcuCommand('flashprotect', 'enable')
    except fpmcu_utils.FpmcuError:
      pass
    time.sleep(2)
    self._EnsureWriteProtectEnabledBeforeRebootFromPattern(fpmcu)
    self._RebootEC(fpmcu)

    # Make sure the flag is correct.
    self._EnsureWriteProtectEnabledFlagFromPattern(fpmcu)

    # Make sure the RW image is active.
    self._CheckPattern(r'^Firmware copy:\s*RW$', fpmcu.FpmcuCommand('version'))

    # Verify that the system is locked.
    if os.path.exists('/tmp/fp.raw'):
      os.remove('/tmp/fp.raw')
    if os.path.exists('/tmp/error_msg.txt'):
      os.remove('/tmp/error_msg.txt')
    stdout, stderr, return_code = fpmcu.FpmcuCommand('fpframe', 'raw',
                                                     full_info=True)
    file_utils.WriteFile('/tmp/fp.raw', stdout)
    file_utils.WriteFile('/tmp/error_msg.txt', stderr)

    if return_code == 0:
      raise Error('System is not locked.')
    self._CheckPattern('ACCESS_DENIED|Permission denied', stderr)

  @staticmethod
  def _CheckPattern(pattern, text):
    if not re.search(pattern, text, re.MULTILINE):
      raise Error(f'Pattern not found in text.\nPattern={pattern}\nText={text}')

  def _RebootEC(self, fpmcu):
    try:
      fpmcu.FpmcuCommand('reboot_ec')
    except fpmcu_utils.FpmcuError:
      pass
    time.sleep(2)

  @abc.abstractmethod
  def _EnsureWriteProtectEnabledBeforeRebootFromPattern(self, fpmcu):
    """Checks status before reboot the EC.

    The implementation classes calls |fpmcu.FpmcuCommand|, and checks whether
    the command output matches to some pattern.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def _EnsureWriteProtectEnabledFlagFromPattern(self, fpmcu):
    """Checks write protect flag status.

    The implementation classes calls |fpmcu.FpmcuCommand|, and chesk whether
    the command output matches to some pattern.
    """
    raise NotImplementedError


class _FPMCUType(enum.Enum):
  bloonchipper = 'bloonchipper'
  dartmonkey = 'dartmonkey'


def _CreateFPMCUWriteProtectTarget():
  board = Shell('cros_config /fingerprint board').stdout
  enum_member = _FPMCUType(board)
  # TODO(b/149590275): Update once they match
  if enum_member == _FPMCUType.bloonchipper:
    return BloonchipperWriteProtectTarget()
  # _FPMCUType only has two enum member, so if not bloonchipper, it must be
  # dartmonkey.
  return DartmonkeyWriteProtectTarget()


class BloonchipperWriteProtectTarget(_FPMCUWriteProtectTarget):

  def _EnsureWriteProtectEnabledBeforeRebootFromPattern(self, fpmcu):
    pattern = ('^Flash protect flags: 0x0000000b wp_gpio_asserted ro_at_boot '
               'ro_now$')
    self._CheckPattern(pattern, fpmcu.FpmcuCommand('flashprotect'))

  def _EnsureWriteProtectEnabledFlagFromPattern(self, fpmcu):
    pattern = ('^Flash protect flags: 0x0000040f wp_gpio_asserted ro_at_boot '
               'ro_now rollback_now all_now$')
    self._CheckPattern(pattern, fpmcu.FpmcuCommand('flashprotect'))


class DartmonkeyWriteProtectTarget(_FPMCUWriteProtectTarget):

  def _EnsureWriteProtectEnabledBeforeRebootFromPattern(self, fpmcu):
    pattern = ('^Flash protect flags: 0x00000009 wp_gpio_asserted ro_at_boot$')
    self._CheckPattern(pattern, fpmcu.FpmcuCommand('flashprotect'))

  def _EnsureWriteProtectEnabledFlagFromPattern(self, fpmcu):
    pattern = (
        r'^Flash protect flags:\s*0x0000000b wp_gpio_asserted ro_at_boot '
        'ro_now$')
    self._CheckPattern(pattern, fpmcu.FpmcuCommand('flashprotect'))
