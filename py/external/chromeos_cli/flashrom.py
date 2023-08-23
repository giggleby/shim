# pylint: disable=attribute-defined-outside-init
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""ChromeOS Firmware Utilities

This modules provides easy access to ChromeOS firmware.

To access the contents of a firmware image, use FirmwareImage().
To access the flash chipset containing firmware, use Flashrom().
To get the content of (cacheable) firmware, use LoadMainFirmware() or
  LoadEcFirmware().
"""

import re
import tempfile

from cros.factory.utils import fmap

from cros.factory.external.chromeos_cli import shell


# Names to select target bus.
TARGET_MAIN = 'main'
TARGET_EC = 'ec'

# All Chrome OS images are FMAP based.
FirmwareImage = fmap.FirmwareImage


class FlashromError(Exception):
  """All exceptions when calling flashrom."""


# TODO(jasonchuang) We should check if we can use futility.py instead.
class Flashrom:
  """Wrapper for calling system command flashrom(8)."""

  # flashrom(8) command line parameters
  _VALID_TARGETS = (TARGET_MAIN, TARGET_EC)
  _TARGET_MAP = {
      TARGET_MAIN: '-p internal',
      TARGET_EC: '-p ec',
  }
  _WRITE_FLAGS = '--noverify-all'
  _READ_FLAGS = ''

  def __init__(self, target=None, dut=None):
    self._target = target or TARGET_MAIN
    self._shell = shell.Shell(dut)

  def _InvokeCommand(self, param, ignore_status=False):
    command = ' '.join(['flashrom', self._TARGET_MAP[self._target], param])

    result = self._shell(command)
    if not (ignore_status or result.success):
      raise FlashromError(f'Failed in command: {command}\n{result.stderr}')
    return result

  def GetTarget(self):
    """Gets current target (bus) to access."""
    return self._target

  def SetTarget(self, target):
    """Sets current target (bus) to access."""
    assert target in self._VALID_TARGETS, f'Unknown target: {target}'
    self._target = target

  def GetSize(self):
    return int(self._InvokeCommand('--flash-size').stdout.splitlines()[-1], 0)

  def GetName(self):
    """Returns a key-value dict for chipset info, or None for any failure."""
    results = self._InvokeCommand('--flash-name', ignore_status=True).stdout
    match_list = re.findall(r'\b(\w+)="([^"]*)"', results)
    return dict(match_list) if match_list else None

  def Read(self, filename=None, sections=None):
    """Reads whole image from selected flash chipset.

    Args:
      filename: File name to receive image. None to use temporary file.
      sections: List of sections to read. None to read whole image.

    Returns:
      Image data read from flash chipset.
    """
    if filename is None:
      with tempfile.NamedTemporaryFile(prefix=f'fw_{self._target}_') as f:
        return self.Read(f.name)
    sections_param = [f'-i {name}' for name in sections or []]
    self._InvokeCommand(
        f"-r '{filename}' {' '.join(sections_param)} {self._READ_FLAGS}")
    with open(filename, 'rb') as file_handle:
      return file_handle.read()

  def Write(self, data=None, filename=None, sections=None):
    """Writes image into selected flash chipset.

    Args:
      data: Image data to write. None to write given file.
      filename: File name of image to write if data is None.
      sections: List of sections to write. None to write whole image.
    """
    assert ((data is None) ^
            (filename is None)), ('Either data or filename should be None.')
    if data is not None:
      with tempfile.NamedTemporaryFile(prefix=f'fw_{self._target}_') as f:
        f.write(data)
        f.flush()
        self.Write(None, f.name)
        return
    sections_param = [f'-i {name}' for name in sections or []]
    self._InvokeCommand(
        f"-w '{filename}' {' '.join(sections_param)} {self._WRITE_FLAGS}")


class FirmwareContent:
  """Wrapper around flashrom for a specific firmware target.

  This class keeps track of all the instances of itself that exist.
  The goal being that only one instance ever gets created for each
  target. This mapping of targets to instances is tracked by the
  _target_cache class data member.
  """

  # Cache of target:instance pairs.
  _target_cache = {}

  @classmethod
  def Load(cls, target):
    """Create class instance for target, using cached copy if available."""
    if target in cls._target_cache:
      return cls._target_cache[target]
    obj = cls()
    obj.target = target
    obj.flashrom = Flashrom(target)
    obj.cached_files = []
    cls._target_cache[target] = obj
    return obj

  def GetChipId(self):
    """Caching get of flashrom chip identifier.  None if no chip is present."""
    if not hasattr(self, 'chip_id'):
      info = self.flashrom.GetName()
      self.chip_id = ' '.join([info['vendor'], info['name']]) if info else None
    return self.chip_id

  def GetFileName(self, sections=None):
    """Filename containing firmware data.  None if no chip is present.

    Args:
      sections: Restrict the sections of firmware data to be stored in the file.

    Returns:
      Name of the file which contains the firmware data.
    """
    if self.GetChipId() is None:
      return None

    sections = set(sections) if sections else None

    for (fileref, sections_in_file) in self.cached_files:
      if sections_in_file is None or (sections is not None and
                                      sections.issubset(sections_in_file)):
        return fileref.name

    fileref = tempfile.NamedTemporaryFile(prefix=f'fw_{self.target}_')  # pylint: disable=consider-using-with
    self.flashrom.Read(filename=fileref.name, sections=sections)
    self.cached_files.append((fileref, sections))
    return fileref.name

  def Write(self, filename):
    """Call flashrom write for specific sections."""
    for (fileref, sections_in_file) in self.cached_files:
      if fileref.name == filename:
        self.flashrom.Write(filename=filename, sections=sections_in_file)
        return
    raise ValueError(f'{filename!r} is not found in the cached files')

  def GetFirmwareImage(self, sections=None):
    """Returns a fmap.FirmwareImage instance.

    Args:
      sections: Restrict the sections of firmware data to be stored in the file.

    Returns:
      An instance of FormwareImage.
    """
    with open(self.GetFileName(sections=sections), 'rb') as image:
      return fmap.FirmwareImage(image.read())


def LoadEcFirmware():
  """Returns flashrom data from Embedded Controller chipset."""
  return FirmwareContent.Load(TARGET_EC)


def LoadMainFirmware():
  """Returns flashrom data from main firmware (also known as BIOS)."""
  return FirmwareContent.Load(TARGET_MAIN)
