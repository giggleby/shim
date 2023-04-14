# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A wrapper for getting/setting CBI values.

This module provides functions to set and get CBI values using data names
(e.g. OEM_ID) instead of data tags (e.g. 1).
"""

import collections
import enum
import logging
import re
import subprocess


class CbiException(Exception):
  """CBI exception class."""


# Usage: ectool cbi get <tag> [get_flag]
# Usage: ectool cbi set <tag> <value/string> <size> [set_flag]
#   <tag> is one of:
#     0: BOARD_VERSION
#     1: OEM_ID
#     2: SKU_ID
#     3: DRAM_PART_NUM
#     4: OEM_NAME
#     5: MODEL_ID
#     6: FW_CONFIG
#     7: PCB_SUPPLIER
#   <value/string> is an integer or a string to be set.
#   <size> is the size of the data in byte. It should be zero for
#     string types.


class CbiDataName(str, enum.Enum):
  BOARD_VERSION = 'BOARD_VERSION'
  OEM_ID = 'OEM_ID'
  SKU_ID = 'SKU_ID'
  DRAM_PART_NUM = 'DRAM_PART_NUM'
  OEM_NAME = 'OEM_NAME'
  MODEL_ID = 'MODEL_ID'
  FW_CONFIG = 'FW_CONFIG'
  PCB_SUPPLIER = 'PCB_SUPPLIER'

  def __str__(self):
    return self.name


class CbiEepromWpStatus(str, enum.Enum):
  Locked = 'Locked'
  Unlocked = 'Unlocked'
  Absent = 'Absent'

  def __str__(self):
    return self.name


CbiDataAttr = collections.namedtuple('DataAttr', ['tag', 'type', 'size'])
CbiDataDict = {
    CbiDataName.BOARD_VERSION: CbiDataAttr(0, int, 1),
    CbiDataName.OEM_ID: CbiDataAttr(1, int, 1),
    CbiDataName.SKU_ID: CbiDataAttr(2, int, 4),
    CbiDataName.DRAM_PART_NUM: CbiDataAttr(3, str, 0),
    CbiDataName.OEM_NAME: CbiDataAttr(4, str, 0),
    CbiDataName.MODEL_ID: CbiDataAttr(5, int, 1),
    CbiDataName.FW_CONFIG: CbiDataAttr(6, int, 4),
    CbiDataName.PCB_SUPPLIER: CbiDataAttr(7, int, 1)
}
# The error messages of ectool change from time to time.
AllowedWpErrorMessages = [
    'Write-protect is enabled or EC explicitly '
    'refused to change the requested field.', 'errno 13 (Permission denied)'
]


def GetCbiData(dut, data_name):
  if data_name not in CbiDataName.__members__:
    raise CbiException(f'{data_name} is not a valid CBI data name.')
  data_attr = CbiDataDict[data_name]

  get_flag = 1  # Invalidate cache
  cbi_output = dut.CallOutput(
      ['ectool', 'cbi', 'get',
       str(data_attr.tag),
       str(get_flag)])
  if cbi_output:
    # If the CBI field to be probed is set, the output from
    # 'ectool cbi get' is 'As uint: %u (0x%x)\n' % (val, val)
    if data_attr.type == int:
      match = re.search(r'As uint: ([0-9]+) \(0x[0-9a-fA-F]+\)',
                        cbi_output)
      if match:
        return int(match.group(1))
      raise CbiException('Is the format of the output from "ectool cbi get" '
                         'changed?')
    return cbi_output.strip()
  logging.warning('CBI field %s is not found in EEPROM.', data_name)
  return None


def SetCbiData(dut, data_name, value):
  if data_name not in CbiDataName.__members__:
    raise CbiException(f'{data_name} is not a valid CBI data name.')
  data_attr = CbiDataDict[data_name]
  if not isinstance(value, data_attr.type):
    raise CbiException(f'value {value!r} should have type {data_attr.type!r}.')

  command = ['ectool', 'cbi', 'set', str(data_attr.tag), str(value),
             str(data_attr.size)]
  process = dut.Popen(
      command=command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  stdout, stderr = process.communicate()
  logging.info('%s: stdout: %s\n', command, stdout)
  if process.returncode != 0:
    raise CbiException(
        f'Failed to set data_name={data_name} to EEPROM. returncode='
        f'{int(process.returncode)}, stdout={stdout}, stderr={stderr}')


def CheckCbiEepromPresent(dut):
  """Check that the CBI EEPROM chip is present.

  Args:
    dut: The SystemInterface of the device.

  Returns:
    True if the CBI EEPROM chip is present otherwise False.
  """
  CBI_EEPROM_EC_CHIP_TYPE = 0
  CBI_EEPROM_EC_CHIP_INDEX = 0
  command = [
      'ectool', 'locatechip',
      str(CBI_EEPROM_EC_CHIP_TYPE),
      str(CBI_EEPROM_EC_CHIP_INDEX)
  ]
  process = dut.Popen(command=command, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE)
  stdout, stderr = process.communicate()
  logging.debug('command=%r, returncode=%d, stdout=%r, stderr=%r', command,
                process.returncode, stdout, stderr)
  return process.returncode == 0


def VerifyCbiEepromWpStatus(dut, cbi_eeprom_wp_status):
  """Verify CBI EEPROM status.

  If cbi_eeprom_wp_status is Absent, CBI EEPROM must be absent. If
  cbi_eeprom_wp_status is Locked, write protection must be on. Otherwise, write
  protection must be off.

  Args:
    dut: The SystemInterface of the device.
    cbi_eeprom_wp_status: The expected status, must be one of CbiEepromWpStatus.
    ec_bypass_cbi_eeprom_wp_check: EC will bypass the write protect check if
    this is on.

  Raises:
    CbiException if the status is not expected, GetCbiData fails when CBI is
    expected to be present, or SetCbiData fails when CBI is expected to be
    unlocked.
  """
  detect_presence = CheckCbiEepromPresent(dut)
  expected_presence = cbi_eeprom_wp_status != CbiEepromWpStatus.Absent
  if detect_presence != expected_presence:
    raise CbiException(
        f'CheckCbiEepromPresent returns {detect_presence!r} but is expected to '
        f'be {expected_presence!r}.')
  if not detect_presence:
    return

  def _GetSKUId():
    result = GetCbiData(dut, CbiDataName.SKU_ID)
    if result is None:
      raise CbiException('GetCbiData fails.')
    return result

  def _SetSKUId(value):
    try:
      SetCbiData(dut, CbiDataName.SKU_ID, value)
    except CbiException as e:
      return False, str(e)
    else:
      return True, None

  sku_id = _GetSKUId()
  # The allowed range of sku id is [0, 0x7FFFFFFF].
  test_sku_id = (sku_id + 1) % 0x80000000

  write_success, messages = _SetSKUId(test_sku_id)
  sku_id_afterward = _GetSKUId()
  detect_write_protect = sku_id == sku_id_afterward
  expected_write_protect = cbi_eeprom_wp_status == CbiEepromWpStatus.Locked
  errors = []
  if expected_write_protect:
    if write_success:
      errors.append('_SetSKUId should return False but get True.')
    elif all(error_message not in messages
             for error_message in AllowedWpErrorMessages):
      errors.append(f'Output of _SetSKUId should contain one of '
                    f'{AllowedWpErrorMessages!r} but get {messages!r}')
  else:
    if not write_success:
      errors.append('_SetSKUId should return True but get False.')

  if detect_write_protect:
    if not expected_write_protect:
      errors.append('_SetSKUId should write the CBI EEPROM but it does not.')
  else:
    if expected_write_protect:
      errors.append('_SetSKUId should not write the CBI EEPROM but it does.')
    write_success, unused_messages = _SetSKUId(sku_id)
    if not write_success:
      errors.append('_SetSKUId fails.')
  if errors:
    errors.append(f"write protection switch of CBI EEPROM is"
                  f"{' not' if expected_write_protect else ''} enabled.")
    raise CbiException(' '.join(errors))
