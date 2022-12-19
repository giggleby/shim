# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import logging
import re

from cros.factory.gooftool import crosfw
from cros.factory.utils.type_utils import Error


_RE_ME_PATTERN = r'^(?:\[DEBUG\]\s+)?ME:\s+(?P<key>.+)\s+:\s+(?P<value>.+)$'

_MANIFACTURING_MODE_RULES = {
    'Manufacturing Mode': 'NO',
    'FW Partition Table': 'OK',
}

_RE_FLMSTR_PATTERN = \
  r'FLMSTR(?P<idx>\d+):\s+(?P<value>0x[a-zA-Z0-9]+)\s+\(.+\)'

class ManagementEngineError(Error):
  pass


class SKU(str, enum.Enum):
  Consumer = 'Consumer'
  Lite = 'Lite'
  Unknown = 'Unknown'

  @property
  def flag(self):
    return {
        SKU.Consumer: 0x20,
        SKU.Lite: 0x50,
        SKU.Unknown: 0xff,
    }[self]

  @property
  def flmstr(self):
    return {
        SKU.Consumer: {
            1: 0x00200300,
            2: 0x00400500,
            3: 0x00000000,
            5: 0x00000000,
        },
        SKU.Lite: {
            1: 0x00200700,
            2: 0x00400500,
            3: 0x00000000,
            5: 0x00000000,
        }
    }[self]

def _GetSKUFromHFSTS3(me_flags):
  hfsts3_str = me_flags.get('HFSTS3')
  if hfsts3_str is None:
    raise ManagementEngineError('HFSTS3 is not found')

  try:
    hfsts3 = int(hfsts3_str, 0)
  except:
    raise ManagementEngineError(
        f'HFSTS3 is {hfsts3_str!r} and can not convert to an integer') from None
  if (hfsts3 & 0xF0) == SKU.Consumer.flag:
    return SKU.Consumer
  if (hfsts3 & 0xF0) == SKU.Lite.flag:
    return SKU.Lite
  raise ManagementEngineError('HFSTS3 indicates that this is an unknown SKU')


def _VerifySIMESection(sku, fw_image):
  if sku == SKU.Consumer:
    # For Consumer SKU, if ME is locked, it should contain only 0xFFs.
    data = fw_image.get_section(crosfw.IntelLayout.ME.value).strip(b'\xff')
    if data:
      raise ManagementEngineError(
          'ME (ManagementEngine) firmware may be not locked.')
  elif sku == SKU.Lite:
    # For Lite SKU, if ME is locked, it is still readable. Do nothing.
    pass

def _VerifyManufacturingMode(me_flags):
  errors = []
  for key, expected in _MANIFACTURING_MODE_RULES.items():
    actual = me_flags.get(key)
    if actual is None:
      errors.append(f'{key!r} is not found')
      continue
    if actual != expected:
      errors.append(f'{key!r} is {actual!r} and we expect {expected!r}')
  if errors:
    raise ManagementEngineError('\n'.join(errors))


def _ExecCmd(shell, cmd):
  """Execute a command and return its stdout."""
  result = shell(cmd)
  if not result.success:
    raise ManagementEngineError(f'`{cmd}` failed!\nstderr: {result.stderr}')

  return result.stdout


def _ReadCbmem(shell):
  """Read the coreboot boot logs from cbmem.

  Example output of a locked ME:
  ...
    [DEBUG]  ME: HFSTS1                      : 0x90000245
    [DEBUG]  ME: HFSTS2                      : 0x82100116
    [DEBUG]  ME: HFSTS3                      : 0x00000050
    [DEBUG]  ME: HFSTS4                      : 0x00004000
    [DEBUG]  ME: HFSTS5                      : 0x00000000
    [DEBUG]  ME: HFSTS6                      : 0x40600006
    [DEBUG]  ME: Manufacturing Mode          : NO
    [DEBUG]  ME: SPI Protection Mode Enabled : YES
    [DEBUG]  ME: FPFs Committed              : YES
    [DEBUG]  ME: Manufacturing Vars Locked   : YES
    [DEBUG]  ME: FW Partition Table          : OK
    [DEBUG]  ME: Bringup Loader Failure      : NO
    [DEBUG]  ME: Firmware Init Complete      : YES
  ...
  """
  cbmem_cmd = 'cbmem -1'
  cbmem_stdout = _ExecCmd(shell, cbmem_cmd)
  logging.info('ME content from cbmem: %s', cbmem_stdout)

  return cbmem_stdout


def _ParseDescriptor(descriptor):
  """Parse the descriptor to get the flash master values."""
  flmstr = {}
  logging.info('Parse flash master values...')
  for match in re.finditer(_RE_FLMSTR_PATTERN, descriptor, re.MULTILINE):
    idx_str = match.group('idx')
    value_str = match.group('value')
    logging.info('FLMSTR%s: %s', idx_str, value_str)
    idx = int(idx_str)
    value = int(value_str, 16)
    # Mask out the last 8 bits since they don't matter and could vary on
    # different platform.
    value &= 0xffffff00
    flmstr[idx] = value

  return flmstr


def _VerifyDescriptorLocked(sku, main_fw):
  """Verify that flash regions are protected by FLMSTR settings.

  Example output of a locked descriptor:
  ...
  FLMSTR1:   0x002007ff (Host CPU/BIOS)
    EC Region Write Access:            disabled
    Platform Data Region Write Access: disabled
    GbE Region Write Access:           disabled
    Intel ME Region Write Access:      disabled
    Host CPU/BIOS Region Write Access: enabled
  ...
  """
  descriptor = main_fw.DumpDescriptor()
  actual_flmstr = _ParseDescriptor(descriptor)
  if actual_flmstr != sku.flmstr:
    raise ManagementEngineError('Unexpected FLMSTR values! '
                                f'Expected: {sku.flmstr!r}, '
                                f'Actual: {actual_flmstr!r}')


def VerifyMELocked(main_fw, shell):
  """Verify if ME is locked by checking the output of cbmem."""
  fw_image = main_fw.GetFirmwareImage()
  if not fw_image.has_section(crosfw.IntelLayout.ME.value):
    logging.info('System does not have Management Engine.')
    return

  cbmem_stdout = _ReadCbmem(shell)
  me_flags = {}
  for match in re.finditer(_RE_ME_PATTERN, cbmem_stdout, re.MULTILINE):
    me_flags[match.group('key').strip()] = match.group('value')

  sku = _GetSKUFromHFSTS3(me_flags)
  logging.info('CSE SKU: %s', sku.value)
  _VerifySIMESection(sku, fw_image)
  _VerifyManufacturingMode(me_flags)
  _VerifyDescriptorLocked(sku, main_fw)
