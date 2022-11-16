# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re

from cros.factory.utils.type_utils import Error


_RE_ME_PATTERN = r'^(?:\[DEBUG\]\s+)?ME:\s+(?P<key>.+)\s+:\s+(?P<value>.+)$'

_MANIFACTURING_MODE_RULES = {
    'Manufacturing Mode': 'NO',
    'FW Partition Table': 'OK',
}


class ManagementEngineError(Error):
  pass


def _VerifyHFSTS3(me_flags, main_fw):
  """Check the content of HFSTS3 register to see if ME is locked."""
  hfsts3_str = me_flags.get('HFSTS3')
  if hfsts3_str is None:
    raise ManagementEngineError('HFSTS3 is not found')

  try:
    hfsts3 = int(hfsts3_str, 0)
  except:
    raise ManagementEngineError(
        f'HFSTS3 is {hfsts3_str!r} and can not convert to an integer') from None
  if (hfsts3 & 0xF0) == 0x20:
    # For Consumer SKU, if ME is locked, it should contain only 0xFFs.
    data = main_fw.get_section('SI_ME').strip(b'\xff')
    if data:
      raise ManagementEngineError(
          'ME (ManagementEngine) firmware may be not locked.')
  elif (hfsts3 & 0xF0) == 0x50:
    # For Lite SKU, if ME is locked, it is still readable.
    pass
  else:
    raise ManagementEngineError('HFSTS3 indicates that this is an unknown SKU')


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


def _ReadCbmem(shell):
  """Read the coreboot boot logs from cbmem."""
  # TODO(phoebewang) Add an example output of a locked ME.
  cbmem_result = shell('cbmem -1')
  if not cbmem_result.success:
    raise ManagementEngineError('cbmem fails.')

  cbmem_stdout = cbmem_result.stdout
  logging.info('ME content from cbmem: %s', cbmem_stdout)

  return cbmem_stdout


def VerifyMELocked(main_fw, shell):
  """Verify if ME is locked by checking the output of cbmem."""
  if not main_fw.has_section('SI_ME'):
    logging.info('System does not have Management Engine.')
    return

  cbmem_stdout = _ReadCbmem(shell)
  me_flags = {}
  for match in re.finditer(_RE_ME_PATTERN, cbmem_stdout, re.MULTILINE):
    me_flags[match.group('key').strip()] = match.group('value')

  _VerifyHFSTS3(me_flags, main_fw)
  _VerifyManufacturingMode(me_flags)
  # TODO(hungte) In future we may add more checks using ifdtool. See
  # crosbug.com/p/30283 for more information.
