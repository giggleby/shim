# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from serial import SerialException, SerialTimeoutException
import time

import factory_common  # pylint: disable=W0611
from cros.factory.test.fixture.bft_fixture import (BFTFixture,
                                                   BFTFixtureException)
from cros.factory.utils.serial_utils import OpenSerial, FindTtyByDriver


def _CommandStr(command):
  """Formats one-byte command with 0xFF format.

  Returns:
    One-byte command in 0x%02X format. For non one-byte-str input,
    returns 'invalid command' instead.
  """
  if isinstance(command, str) and len(command) == 1:
    return '0x%02X' % ord(command)
  return 'invalid command %r' % command


class SpringBFTFixture(BFTFixture):
  """Provides interfaces to interact with BFT fixture for Spring board."""

  # Define Spring BFT fixture's support devices' command.
  # device: (engage_command, disengage_command)
  # None means unsupported.
  Device = BFTFixture.Device
  DEVICE_COMMAND = {
    Device.AC_ADAPTER       : (chr(0xC8), chr(0xD0)),
    Device.AUDIO_JACK       : (chr(0xCC), chr(0xCD)),
    Device.EXT_DISPLAY      : (chr(0xCB), chr(0xD0)),
    Device.LID_MAGNET       : (chr(0xC2), chr(0xC3)),
    Device.USB_0            : (chr(0xCA), chr(0xD0)),
    Device.USB_1            : (None, None),
    Device.USB_2            : (None, None)}

  # (command, response) pairs for fixture to check LED colors.
  LEDColor = BFTFixture.LEDColor
  LED_CHECK_COMMAND = {
    LEDColor.RED   : (chr(0xC4), chr(0xB4)),
    LEDColor.GREEN : (chr(0xC5), chr(0xB5)),
    LEDColor.AMBER : (chr(0xC6), chr(0xB6)),
    LEDColor.OFF   : (chr(0xD4), chr(0xFC))}

  DEFAULT_RESPONSE = chr(0xFA)
  ENGAGE_BARCODE_SCANNER = chr(0xC7)
  ENGAGE_KEYBOARD_SCANNER = chr(0xC1)

  # Defaut value of self._serial.
  _serial = None

  def Init(self, **serial_params):
    """Sets up RS-232 connection.

    Args:
      **serial_params: Parameters of pySerial's Serial().
          'port' should be specified. If port cannot be predetermined,
          you can specify 'driver' and it'll use FindTtyByDriver() to
          locate the first /dev/ttyUSB* which uses the driver.
    """
    if 'driver' in serial_params:
      serial_params['port'] = FindTtyByDriver(serial_params['driver'])
      if not serial_params['port']:
        raise BFTFixtureException('Cannot find TTY with driver %s' %
                                  serial_params['driver'])
      # After lookup, remove 'driver' from serial_params as OpenSerial
      # doesn't accept 'driver' param.
      del serial_params['driver']
    try:
      self._serial = OpenSerial(**serial_params)
    except SerialException as e:
      raise BFTFixtureException('Cannot connect to BFT fixture: %s' % e)

  def Disconnect(self):
    if self._serial:
      self._serial.close()

  def _Send(self, command, fail_message):
    """Sends a one-char command to BFT fixture.

    Args:
      command: a one-char string.
      fail_message: error message to prepend to BFTFixtureException.
    """
    if not self._serial:
      raise BFTFixtureException('BFT connection is not established yet.')

    try:
      write_len = self._serial.write(command)
    except SerialTimeoutException as e:
      raise BFTFixtureException('%sSend command %s timeout: %s' %
                                (fail_message, _CommandStr(command), e))

    if write_len != 1:
      raise BFTFixtureException('%sSend command %s failed.' %
                                (fail_message, _CommandStr(command)))
    logging.info('Successfully sent %s', _CommandStr(command))

  def _Recv(self, fail_message):
    """Receives a response from BFT fixture.

    Args:
      fail_message: error message to prepend to BFTFixtureException.
    Returns:
      The response string.
    """
    try:
      recv = self._serial.read()
      logging.info('Successfully received %s', _CommandStr(recv))
      return recv
    except SerialTimeoutException as e:
      raise BFTFixtureException('%sReceive timeout: %s' % (fail_message, e))

  def _SendRecv(self, command, expect, fail_message):
    """Sends a command and expects a response.

    Args:
      command: a one-char string to send to BFT fixture.
      expect: a one-char string for expecting the reply. Default 0xFA.
      fail_message: error message to prepend to BFTFixtureException.
    """
    self._Send(command, fail_message)

    actual = self._Recv(fail_message)
    if actual != expect:
      raise BFTFixtureException(
        '%sExpect:%s, actual:%s.' %
        (fail_message, _CommandStr(expect), _CommandStr(actual)))

  def _SendRecvDefault(self, command, fail_message):
    """Like _SendRecv, but expecting 0xFA response."""
    self._SendRecv(command, self.DEFAULT_RESPONSE, fail_message)

  def SetDeviceEngaged(self, device, engage):
    """Engages/disengages a device.

    Issues a command to BFT fixture to engage/disenage a device.
    The device can be either a peripheral device of the board or a
    device of the fixture.

    Args:
      device: device defined in BFTFixture.Device
      engage: True to engage; False to disengage.
    """
    action_str = '%s device %s' % ('engage' if engage else 'disengage',
                                   device)
    logging.info(action_str)

    command = None
    if device in self.DEVICE_COMMAND:
      command = self.DEVICE_COMMAND[device][0 if engage else 1]
    if not command:
      raise BFTFixtureException('Unsupported action: ' + action_str)

    # TODO(deanliao): hack, remove later
    if command == chr(0xC8):
      logging.info('HACK, disconnect before connect charger and sleep '
                   'for one second.')
      self._SendRecvDefault(chr(0xD0), 'Failed to %s. ' % action_str)
      time.sleep(1)
    # end hack
    self._SendRecvDefault(command, 'Failed to %s. ' % action_str)

  def Ping(self):
    self._SendRecv(chr(0xE0), chr(0xE1), 'Failed to ping the fixture. ')

  def CheckPowerRail(self):
    self._SendRecv(chr(0xD2), chr(0xE2),
                   'Failed to check DUT\'s power rail voltage. ')

  def GetFixtureId(self):
    FAIL_MESSAGE = 'Failed to get fixture ID. '
    self._Send(chr(0xE2), FAIL_MESSAGE)
    recv = self._Recv(FAIL_MESSAGE)
    if not recv:
      raise BFTFixtureException(FAIL_MESSAGE)
    return ord(recv[0])

  def ScanBarcode(self):
    self._SendRecvDefault(self.ENGAGE_BARCODE_SCANNER,
                          'Failed to scan barcode. ')

  def SimulateKeystrokes(self):
    self._SendRecvDefault(self.ENGAGE_KEYBOARD_SCANNER,
                          'Failed to simulate keystrokes. ')

  def IsLEDColor(self, color):
    if color not in self.LED_CHECK_COMMAND:
      raise BFTFixtureException('Invalid color: %s', color)

    (command, response) = self.LED_CHECK_COMMAND[color]
    self._Send(command, 'Fail to check %s LED. ' % color)
    return self._Recv('Fail to check %s LED. ' % color) == response
