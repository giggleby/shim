# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import logging
import re
import subprocess

from cros.factory.hwid_extractor import ap_firmware
from cros.factory.hwid_extractor import cr50
from cros.factory.hwid_extractor import rlz
from cros.factory.hwid_extractor import servod


# SuzyQ usb device ids.
CR50_USB = '18d1:5014'
TI50_USB = '18d1:504a'
GSC_LSUSB_CMD = ['lsusb', '-vd']
GSC_LSUSB_SERIAL_RE = r'iSerial +\d+ (\S+)\s'

RLZ_DATA = rlz.RLZData()


def _ScanCCDDevices():
  """Use `lsusb` to get iSerial attribute of CCD devices.

  Returns:
    Serial name of the first found CCD device, in uppercase.
  """
  logging.info('Scan serial names of CCD devices')
  output = ''
  for usb_device_id in [CR50_USB, TI50_USB]:
    try:
      output += subprocess.check_output(GSC_LSUSB_CMD + [usb_device_id],
                                        encoding='utf-8')
    except subprocess.CalledProcessError:
      pass

  if not output:
    return None
  serials = re.findall(GSC_LSUSB_SERIAL_RE, output)
  if not serials:
    # iSerial should be listed in the output. If not, the user may not have
    # permission to get iSerial.
    raise RuntimeError(
        'Cannot get CCD serial number. Maybe running with sudo ?')
  if len(serials) > 1:
    raise RuntimeError('Working with multiple devices is not supported.')
  logging.info('Serial name of CCD devices: %s', serials)
  return serials[0]


@contextlib.contextmanager
def _GetCr50FromServod(*args, **kargs):
  """Start Servod and return a Cr50 interface.

  Each time Servod stops, the ccd devices `/dev/ttyUSB*` won't show up unless
  users replug the SuzyQ cable. Run Servod and get the uart device through
  dut-control make things simpler.

  Returns:
    A Cr50 interface.
  """
  with servod.Servod(*args, **kargs) as dut_control:
    cr50_pty = dut_control.GetValue('cr50_uart_pty')
    # Disable the timestamp to make output of the console cleaner.
    dut_control.Run(['cr50_uart_timestamp:off'])
    yield cr50.Cr50(cr50_pty)


def Scan():
  """Scan and read the status of a device.

  Returns:
    A Dict contains the device status.
  Raises:
    RuntimeError if no device was found, or there are multiple devices connected
    to the host.
  """
  cr50_serial_name = _ScanCCDDevices()
  if not cr50_serial_name:
    raise RuntimeError('No device was found.')
  with _GetCr50FromServod(serial_name=cr50_serial_name) as dut_cr50:
    rlz_code = dut_cr50.GetRLZ()
    is_testlab_enabled = dut_cr50.GetTestlabState() == cr50.TestlabState.ENABLED
    if is_testlab_enabled:
      # Force CCD to be opened. This make sure that if testlab is enabled, the
      # CCD is always non-restricted.
      is_restricted = dut_cr50.ForceOpen()
    else:
      is_restricted = dut_cr50.IsRestricted()
    return {
        'cr50SerialName': cr50_serial_name,
        'rlz': rlz_code,
        'referenceBoard': RLZ_DATA.Get(rlz_code),
        'challenge': dut_cr50.GetChallenge() if is_restricted else None,
        'isRestricted': is_restricted,
        'isTestlabEnabled': is_testlab_enabled,
    }


def ExtractDeviceInfo(cr50_serial_name, board):
  """Extract info from device.

  Args:
    cr50_serial_name: The serial name of the cr50 usb device.
    board: The name of board of the device.
  Returns:
    gsc_dev_id, serial_number, hwid. The value may be None.
  """
  # TODO(b/294967029): figure out where this format
  # "0x{id_first_part} 0x{id_second_part}" comes from.
  # We are not sure if this is a convention from HWSEC team or not.
  gsc_dev_id_arr = cr50_serial_name.split('-')
  gsc_dev_id = f'0x{gsc_dev_id_arr[0]} 0x{gsc_dev_id_arr[1]}'
  with servod.Servod(serial_name=cr50_serial_name, board=board):
    hwid, serial_number = ap_firmware.ExtractHWIDAndSerialNumber()
    return gsc_dev_id, serial_number, hwid


def Unlock(cr50_serial_name, authcode):
  """Unlock the device.

  Args:
    cr50_serial_name: The serial name of the cr50 usb device.
    authcode: The authcode to unlock the device.
  Returns:
    True if unlock successfully.
  """
  with _GetCr50FromServod(serial_name=cr50_serial_name) as dut_cr50:
    return dut_cr50.Unlock(authcode)


def Lock(cr50_serial_name):
  """Lock the device.

  Args:
    cr50_serial_name: The serial name of the cr50 usb device.
  Returns:
    True if lock successfully.
  """
  with _GetCr50FromServod(serial_name=cr50_serial_name) as dut_cr50:
    return dut_cr50.Lock()


def EnableTestlab(cr50_serial_name):
  """Enable testlab.

  Args:
    cr50_serial_name: The serial name of the cr50 usb device.
  Returns:
    True if enable successfully.
  """
  with _GetCr50FromServod(serial_name=cr50_serial_name) as dut_cr50:
    return dut_cr50.EnableTestlab()


def DisableTestlab(cr50_serial_name):
  """Disable testlab.

  Args:
    cr50_serial_name: The serial name of the cr50 usb device.
  Returns:
    True if disable successfully.
  """
  with _GetCr50FromServod(serial_name=cr50_serial_name) as dut_cr50:
    return dut_cr50.DisableTestlab()
