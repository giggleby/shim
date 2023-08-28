# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re
import subprocess

from cros.factory.utils import file_utils


FUTILITY_BIN = '/usr/bin/futility'
VPD_BIN = '/usr/sbin/vpd'
CMD_TIMEOUT_SECOND = 20

HWID_RE = re.compile(r'hardware_id: ([A-Z0-9- ]+)')
SERIAL_NUMBER_RE = re.compile(r'"serial_number"="([A-Za-z0-9]+)"')


def _GetHWID(firmware_binary_file):
  """Get HWID from ap firmware binary."""
  futility_cmd = [FUTILITY_BIN, 'gbb', firmware_binary_file]
  output = subprocess.check_output(futility_cmd, encoding='utf-8',
                                   stderr=subprocess.PIPE,
                                   timeout=CMD_TIMEOUT_SECOND)
  logging.debug('futility output:\n%s', output)
  output.split(':')
  m = HWID_RE.fullmatch(output.strip())
  return m and m.group(1)


def _GetSerialNumber(firmware_binary_file):
  """Get serial number from ap firmware binary."""
  vpd_cmd = [VPD_BIN, '-l', '-f', firmware_binary_file]
  output = subprocess.check_output(vpd_cmd, encoding='utf-8',
                                   stderr=subprocess.PIPE,
                                   timeout=CMD_TIMEOUT_SECOND)
  logging.debug('vpd output:\n%s', output)
  for line in output.splitlines():
    m = SERIAL_NUMBER_RE.fullmatch(line.strip())
    if m:
      return m.group(1)
  return None


def ExtractHWIDAndSerialNumber():
  """Extract HWID and serial no. from DUT.

  Read the ap firmware binary from DUT and extract the info from it. Only the
  necessary blocks are read to reduce the reading time.

  Returns:
    hwid, serial_number. The value may be None.
  """
  with file_utils.UnopenedTemporaryFile() as tmp_file:
    futility_cmd = [
        FUTILITY_BIN, 'read', '--servo', '-r', 'FMAP,RO_VPD,GBB', tmp_file
    ]
    output = subprocess.check_output(futility_cmd, encoding='utf-8',
                                     stderr=subprocess.PIPE,
                                     timeout=CMD_TIMEOUT_SECOND)
    logging.debug('futility read output:\n%s', output)
    hwid = _GetHWID(tmp_file)
    serial_number = _GetSerialNumber(tmp_file)
    logging.info('Extract result: HWID: "%s", serial number: "%s"', hwid,
                 serial_number)

  return hwid, serial_number
