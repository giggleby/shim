# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import enum
import filecmp
import logging
import tempfile

from cros.factory.external.chromeos_cli import flashrom
from cros.factory.external.chromeos_cli import shell


class IfdtoolError(Exception):
  """All exceptions when calling ifdtool."""


class IntelPlatform(str, enum.Enum):
  AlderLake = 'adl'
  ApolloLake = 'aplk'
  CannonLake = 'cnl'
  LewisburgPCH = 'lbg'
  Denverton = 'dnv'
  ElkhartLake = 'ehl'
  GeminiLake = 'glk'
  IceLake = 'icl'
  IFDv2Platform = 'ifd2'
  JasperLake = 'jsl'
  SkyLake = 'sklkbl'
  KabyLake = 'sklkbl'
  TigerLake = 'tgl'


class Ifdtool:
  """Wrapper for Intel's ifdtool."""

  def __init__(self, platform: IntelPlatform, dut=None):
    self._shell = shell.Shell(dut)
    self._platform = \
      IntelPlatform.IFDv2Platform.value if platform is None else platform.value

  def _InvokeCommand(self, param, ignore_status=False):
    command = ' '.join(['ifdtool', '-p', self._platform, param])

    result = self._shell(command)
    if not (ignore_status or result.success):
      raise IfdtoolError('Failed in command: {command}\n{result.stderr}}')
    return result

  def Dump(self, desc_path):
    """Dump the descriptor binary into human-readable format."""
    return self._InvokeCommand(f'-d {desc_path}').stdout

  def GenerateLockedDescriptor(self, unlocked_desc_path, prefix='locked_desc_'):
    """Generate a locked descriptor binary."""
    locked_desc_path = tempfile.NamedTemporaryFile(prefix=prefix).name  # pylint: disable=consider-using-with
    self._InvokeCommand(f'-lr -O {locked_desc_path} {unlocked_desc_path}')
    return locked_desc_path


class IntelLayout(str, enum.Enum):
  """Intel's firmware image layout.

  The firmware image layout is defined under
  `src/third_party/coreboot/src/mainboard/google/<intel_board>/chromeos.fmd`.
  """
  DESC = 'SI_DESC'
  ME = 'SI_ME'


class IntelMainFirmwareContent(flashrom.FirmwareContent):
  """Wrapper around FirmwareContent and ifdtool for manipulating descriptor."""

  @classmethod
  def Load(cls, platform=None):  # pylint: disable=arguments-renamed
    obj = super(IntelMainFirmwareContent, cls).Load(flashrom.TARGET_MAIN)
    obj.ifdtool = Ifdtool(platform)
    return obj

  def DumpDescriptor(self):
    desc_bin = self.GetFileName([IntelLayout.DESC.value])
    return self.ifdtool.Dump(desc_bin)

  def GenerateAndCheckLockedDescriptor(self):
    """Generate the locked descriptor and check if it is already locked.

    This function generates a locked descriptor using the current descriptor.
    It then compares the two descriptors to see if the descriptor is already
    locked.

    Returns:
      A tuple of (string, bool).
      string - Path to the locked descriptor binary.
      bool - The descriptor is already locked or not.
    """
    desc_bin = self.GetFileName([IntelLayout.DESC.value])
    locked_desc_bin = self.ifdtool.GenerateLockedDescriptor(desc_bin)
    is_locked = filecmp.cmp(desc_bin, locked_desc_bin, shallow=False)
    return locked_desc_bin, is_locked

  def ReadDescriptor(self):
    """Read the descriptor data."""
    return self.flashrom.Read(sections=[IntelLayout.DESC.value])

  def WriteDescriptor(self, *, data=None, filename=None):
    """Write the given descriptor data or file to the main firmware.

    For the new descriptor to take effect, caller needs to trigger a cold
    reboot.

    Args:
      data: Image data to write. None to write given file.
      filename: File name of image to write if data is None.
    """
    logging.info('Write the descriptor...')
    self.flashrom.Write(data=data, filename=filename,
                        sections=[IntelLayout.DESC.value])


def LoadIntelMainFirmware(platform=None):
  """Returns Intel's Main firmware."""
  return IntelMainFirmwareContent.Load(platform)
