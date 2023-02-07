# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A wrapper for talking with a tty modem."""

import logging
from typing import List

import serial

from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


_COMMAND_RETRY_TIMES = 5

SUCCESSS_RESPONSE_TOKEN = 'OK'
ERROR_RESPONSE_TOKEN = 'ERROR'


class Modem:

  def __init__(self, port, timeout=2,
               cancel_echo=False, disable_operation=False):
    """Initiates a modem serial port communication.

    Args:
      port: the relative port path starts from '/dev/'
      timeout: timeout seconds that passed to pyserial
      cancel_echo: AT command to suppress the echo
      disable_operation: Put modem into a non-operation mode so it will
          not throw unexpected messages.
    """
    self.ser = serial.Serial(f'/dev/{port}', timeout=timeout)

    if cancel_echo:
      self.SendCommandWithCheck('ATE0')

    if disable_operation:
      self.SendCommandWithCheck('AT+CFUN=0')

    # Send an AT command and expect 'OK'
    self.SendCommandWithCheck('AT')

  def ReadLine(self) -> str:
    """Reads a line from the modem.

    Raises:
      MaxRetryError: If the serial didn't return a not `None` object
        after `_COMMAND_RETRY_TIMES` times
    """

    @sync_utils.RetryDecorator(max_attempt_count=_COMMAND_RETRY_TIMES,
                               timeout_sec=float('inf'),
                               target_condition=lambda x: x)
    def _SerialRead() -> str:
      return self.ser.readline()

    try:
      response = _SerialRead()
    except type_utils.MaxRetryError:
      logging.error('modem cannot get non-empty response')
      raise

    response = response.rstrip('\r\n')
    logging.info('modem[%s]', response)

    return response

  def SendLine(self, line):
    """Sends a line to the modem."""
    logging.info('modem] %r', line)
    self.ser.write(line + '\r')

  def SendCommand(self, command):
    """Sends a line to the modem and discards the echo."""
    self.SendLine(command)
    self.ReadLine()

  def SendCommandWithCheck(
      self, command: str, retry_times: int = _COMMAND_RETRY_TIMES) -> List[str]:
    """Sends a command to the modem.

    SendCommand function allow retry when response is not OK.

    Returns:
      response: A list contains all success responses from modem.

    Raises:
      MaxRetryError: If the command cannot get non-empty response after
        `_COMMAND_RETRY_TIMES`.
    """

    @sync_utils.RetryDecorator(max_attempt_count=retry_times,
                               timeout_sec=float('inf'),
                               target_condition=lambda x: x)
    def _SendCommand() -> List[str]:
      self.SendLine(command)
      response = self._GetFullResponse()
      if response[-1] == SUCCESSS_RESPONSE_TOKEN:
        return response
      return []

    return _SendCommand()

  def _GetFullResponse(self) -> List[str]:
    """Gets response from modem.

    A formal response should be OK or ERROR at the end of response.

    Returns:
      response: A list of str contains all response from modem.

    Raises:
      MaxRetryError: If the underlying `ReadLine()` cannot get non-empty
        response after `_COMMAND_RETRY_TIMES`.
    """
    response = []
    while True:
      line = self.ReadLine()
      response.append(line)
      # TODO (henryhsu): The response may have "+CME ERROR: <errno>".
      # If we will use ME command in the future, we will need handle this
      # error type.
      if line in {SUCCESSS_RESPONSE_TOKEN, ERROR_RESPONSE_TOKEN}:
        return response

  def ExpectLine(self, expected_line):
    """Expects a line from the modem."""
    line = self.ReadLine()
    if line != expected_line:
      raise type_utils.Error(f'Expected {expected_line!r} but got {line!r}')
