# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Bluetooth utils.

Currently, it supports a partial command set of gatttool, i.e., getting the
battery level and the firmware revision string of the target bluetooth device.

This module is mostly inspired by rel_tester.py written by mylesgw@chromium.org
"""

import argparse
import binascii
import datetime
import logging
import re

from cros.factory.utils import process_utils

from cros.factory.external import pexpect


class BluetoothUtilsError(Exception):
  """An excpetion class for the bluetooth_utils module."""


class BtMgmt:
  """A wrapper of linux btmgmt tool."""

  def __init__(self, manufacturer_id=None):
    self._manufacturer_id = manufacturer_id
    self._hci_device = None
    self._host_mac = None
    self._GetInfo(self._manufacturer_id)

  def _GetInfo(self, manufacturer_id):
    """Gets the bluetooth hci device and MAC of the adapter with specified
    manufacturer id.

    If manufacturer_id is None and only one MAC is found, store the one found.
    Raise error when more then one MAC is found and no manufacturer_id is set.

    Examples of the output from "btmgmt info" could be as follows depending
    on the version of btmgmt.

        hci1:   addr 00:1A:7D:DA:71:05 version 6 manufacturer 10 class 0x080104
        ...

    or

        hci0:   Primary controller
                addr 00:1A:7D:DA:71:14 version 6 manufacturer 10 class 0x480104
        ...
    """
    patt = re.compile(
        r'.*\s+addr\s+(.+)\s+version.+manufacturer\s(\d+)\s+class.+')
    hci_device = None
    host_mac_list = []
    for line in process_utils.CheckOutput(['btmgmt', 'info']).splitlines():
      if line.startswith('hci'):
        hci_device = line.split(':')[0]
      # The manufacturer id may or may not be on the same line of
      # the hci device.
      result = patt.match(line)
      if result:
        mid = int(result.group(2))
        if mid == manufacturer_id:
          self._hci_device = hci_device
          self._host_mac = result.group(1)
          return
        host_mac_list.append((hci_device, result.group(1)))
    if len(host_mac_list) > 1:
      raise NotImplementedError('More then one MAC address while no'
                                'mamufacturer_id specified.')
    if len(host_mac_list) == 1:
      self._hci_device = host_mac_list[0][0]
      self._host_mac = host_mac_list[0][1]

  def GetMac(self):
    """Gets the MAC address of the bluetooth adapter."""
    return self._host_mac

  def GetHciDevice(self):
    """Gets the HCI device of the bluetooth adapter."""
    return self._hci_device

  def FindDevices(self, index=0, timeout_secs=None, log=True):
    if self._hci_device:
      index = int(self._hci_device.lstrip('hci'))

    patt = re.compile(r'hci\d+\sdev_found:\s(.+)\stype\s.+\srssi\s(\-\d+)\s.*')
    devices = {}
    find_cmd = ['btmgmt', '--index', str(index)]
    if timeout_secs is not None:
      find_cmd.extend(['--timeout', str(timeout_secs)])
    find_cmd.append('find')
    for line in process_utils.CheckOutput(find_cmd, log=log).splitlines():
      if line.startswith('hci'):
        result = patt.fullmatch(line)
        if not result:
          continue

        mac = result.group(1)
        rssi = int(result.group(2))
        if log:
          logging.info('Address: %s, RSSI: %d', mac, rssi)
        if mac not in devices:
          devices[mac] = {}
        devices[mac]['RSSI'] = rssi

      elif line.startswith('name'):
        name = line.lstrip('name ')
        devices[mac]['Name'] = name

    # The timeout just kill the interactive session but it may not stop
    # discovery. Use stop-find afterwards to guarantee discovery ends.
    process_utils.CheckOutput(
        ['btmgmt', '--index', str(index), 'stop-find'], log=log)

    return devices

  def PowerOn(self):
    """Power on the bluetooth adapter"""
    process_utils.CheckCall(['btmgmt', 'power', 'on'])


class GattTool:
  """A wrapper of linux gatttool.

  Note: only a limited set of uuids are supported so far, and will be augmented
  on a demand base.
  """

  UUID_BATTERY_LEVEL = '2a19'
  UUID_FIRMWARE_REVISION_STRING = '2a26'

  DEFAULT_LOG_FILE = '/var/log/gatt.log'
  DEFAULT_TIMEOUT = 20

  def __init__(self, target_mac, hci_device=None, logfile=DEFAULT_LOG_FILE,
               timeout=DEFAULT_TIMEOUT):
    # An hci_devices is something like hci0 or hci1.
    hci_option = ''
    if hci_device:
      if hci_device.startswith('hci'):
        hci_option = f'-i {hci_device}'
      else:
        msg = 'hci device "%s" should start with "hci", e.g., hci0 or hci1.'
        logging.warning(msg, hci_device)
    self._gatttool = pexpect.spawn(
        f'gatttool {hci_option} -b {target_mac.upper()} -t random --interactive'
    )
    self._gatttool.logfile = open(logfile, 'w', encoding='utf8')  # pylint: disable=consider-using-with
    if timeout is None:
      self._timeout = self.DEFAULT_TIMEOUT
    else:
      self._timeout = timeout

  def __del__(self):
    if not self._gatttool.closed:
      self._gatttool.sendline('exit')
      self._gatttool.logfile.close()
      self._gatttool.close()

  def _RaiseError(self, msg):
    """Raises an error."""
    self.Exit()
    raise BluetoothUtilsError(str(datetime.datetime.now()) + ': ' + msg)

  def ScanAndConnect(self):
    """Scans and connects to the target peer device."""
    try:
      result = self._gatttool.expect(r'\[LE\]>', timeout=self._timeout)
      if result != 0:
        self._RaiseError('scan error')
    except pexpect.TIMEOUT:
      self._RaiseError('scan timeout')

    self._gatttool.sendline('connect')

    try:
      result = self._gatttool.expect('Conn.*', timeout=self._timeout)
      if result != 0:
        self._RaiseError('connection error')
    except pexpect.TIMEOUT:
      self._RaiseError('connection timeout')

  def CharReadUUID(self, uuid, spec_name):  # pylint: disable=inconsistent-return-statements
    """Executes char-read-uuid and returns the value.

    Args:
      uuid: an uuid that defines the attribute type
      spec_name: the specification name to display in the log

    Returns:
      the value string
      Note that how to interpret the value string is up to the calling method.

    See details of the complete specification names at
    https://developer.bluetooth.org/gatt/characteristics/Pages/CharacteristicsHome.aspx
    """
    command = f'char-read-uuid {uuid}'
    self._gatttool.sendline(command)
    # Expect to receive a string like
    #   handle: xxxx   value: ........
    expect_pattern = r'handle:.*\s+value:\s+(.+)\s*\r\n'
    try:
      result = self._gatttool.expect(expect_pattern, timeout=self._timeout)
      if result != 0:
        self._RaiseError(f'{command} error')
      return self._gatttool.match.groups()[0]
    except pexpect.TIMEOUT:
      self._RaiseError(f'timeout waiting for {spec_name} report')

  def _Unhexlify(self, string):
    """Removes spaces and unhexlify the ascii string.

    Args:
      string: the ascii string to unhexlify

    Returns:
      An unhexlified string
    """
    return binascii.unhexlify(string.replace(' ', ''))

  def GetFirmwareRevisionString(self):
    """Gets the firmware revision string.

    The version fetched from UUID_FIRMWARE_REVISION_STRING command outputs like

      handle: 0x0010   value: 30 2e 31 35 30 37 31 35

    And the returned value is extracted from the 'value', interpreted as ASCII
    codes. For example, the value above is "0.150715".

    Returns:
      A string representing the firmware revision.
    """
    spec_name = 'firmware revision string'
    result = self.CharReadUUID(self.UUID_FIRMWARE_REVISION_STRING, spec_name)
    return self._Unhexlify(result)

  def GetBatteryLevel(self):
    """Gets the battery level.

    An example of the returned battery level, 99, looks like
        handle: 0x0015   value: 63

    Returns:
      An integer representing the battery percentage.
    """
    spec_name = 'battery level'
    result = self.CharReadUUID(self.UUID_BATTERY_LEVEL, spec_name)
    return int(result, 16)

  def Disconnect(self):
    """Send a disconnect command."""
    self._gatttool.sendline('disconnect')

  def Exit(self):
    """Exit and clean up."""
    self.__del__()

  @classmethod
  def GetDeviceInfo(cls, target_mac, spec_name, hci_device=None, timeout=None):
    """A helper method to get information conveniently from a specified
    bluetooth device.

    Args:
      target_mac: the MAC address of the target device
      spec_name: the specification name to display in the log
      hci_device: the hci device to get information from
    """
    gatttool = GattTool(target_mac, hci_device=hci_device, timeout=timeout)
    gatttool.ScanAndConnect()
    if spec_name == 'battery level':
      info = gatttool.GetBatteryLevel()
    elif spec_name == 'firmware revision string':
      info = gatttool.GetFirmwareRevisionString()
    gatttool.Exit()
    return info


def _ParseCommandLine():
  """Parses the command line options."""
  usage = ('Example:\n\tpython bluetooth_utils.py -a cd:e3:4a:47:1c:e4')
  parser = argparse.ArgumentParser(description=usage)
  parser.add_argument('-a', '--address', action='store', type=str,
                      required=True,
                      help='target address '
                           '(Can be found by running "hcitool lescan")')
  args = parser.parse_args()

  return args


def VerifyAltSetting():
  """
  Checks the Alt Setting is 6 for Realtek RTL8852CE.

  The Alt Setting for Realtek RTL8852CE should be 6 to provide a reliable and
  efficient USB data path for Bluetooth HFP applications. Here we assume the
  VID:PID is always '0bda:0852' for Realtek RTL8852CE.

  Raises:
    BluetoothUtilsError if the device is using Realtek RTL8852CE but the Alt
    Setting is not 6.
  """
  vid_pid_RTL8852CE = '0bda:0852'
  lsusb_output = process_utils.SpawnOutput(f'lsusb -d {vid_pid_RTL8852CE} -v',
                                           shell=True)
  if not lsusb_output or re.search(' *bAlternateSetting *6\n', lsusb_output):
    return
  current_setting = 'Unknown'
  expected_setting = '6'
  if all(
      re.search(f' *bAlternateSetting *{i}\n', lsusb_output) for i in range(6)):
    current_setting = 3
  raise BluetoothUtilsError(
      ('Wrong USB Alt Setting for Realtek RTL8852CE. Expected setting = '
       f'{expected_setting}. Current setting = {current_setting}'))

def main():
  """The main program to run the script."""
  args = _ParseCommandLine()
  print('battery level:',
        GattTool.GetDeviceInfo(args.address, 'battery level'))
  print('firmware revision string:',
        GattTool.GetDeviceInfo(args.address, 'firmware revision string'))


if __name__ == '__main__':
  main()
