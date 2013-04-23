# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sends a command to the fixture and expects its response.

We have some test fixture which communicates with the DUT via serial port.
It provides a simple interface to send a command to the fixture and/or
verify its response.

For example, DUT can use it to send a echo command and expect to receive a
echo response from the fixture.

dargs:
  serial_param: A parameter tuple of the target serial port:
      (port, baudrate, bytesize, parity, stopbits, timeout_secs).
      timeout_secs is used for both read and write timeout.
  fail_message: The first sentence to show when failing to communicate with
      the fixture.
  send_recv: A tuple (send, recv). send is a char for the DUT to send to
      the fixture. And recv is the expected one-char response from the fixture.
      If recv is None, the DUT expects any one-char response.
  send_only: bool. True to just send a char to fixture. Default false.
"""
import serial
import unittest

from cros.factory.test.args import Arg
from cros.factory.utils import serial_utils


class SerialEchoTest(unittest.TestCase):
  ARGS = [
    Arg('serial_param', tuple,
        'The parameter list for a serial connection. Refer serial_utils.'),
    Arg('fail_message', str,
        'The first sentence to show when failing to communicate with fixture.',
        default='Failed to communicate with fixture.'),
    Arg('send_recv', tuple,
        'A tuple (send, recv). send is a char for the DUT to send to a fixture '
        'MCU. And recv is the expected one-char response from the fixture. '
        'If recv is None, the DUT just consumes a one-char response regardless '
        'what the value is.'),
    Arg('send_only', bool,
        'True to just send a char to fixture. Default false.', default=False),
  ]

  def setUp(self):
    def _ValidateSendRecv(sr):
      return (len(sr) == 2 and
              (isinstance(sr[0], str) and len(sr[0]) == 1) and
              (sr[1] is None or
               (isinstance(sr[1], str) and len(sr[1]) == 1)))

    self._serial = None
    self._send = None
    self._recv = None

    if not _ValidateSendRecv(self.args.send_recv):
      self.fail('%s Invalid dargs send_recv: %s' %
                (self.args.fail_message, str(self.args.send_recv)))
    self._send, self._recv = self.args.send_recv

    try:
      self._serial = serial_utils.OpenSerial(self.args.serial_param)
    except serial.SerialException as e:
      self.fail('%s Failed to open connection: %s' % (self.args.fail_message,
                                                      str(e)))

  def tearDown(self):
    if self._serial:
      self._serial.close()

  def testEcho(self):
    self.assertTrue(self._serial is not None, 'Invalid serial connection.')
    try:
      self.assertEqual(1, self._serial.write(self._send),
                       self.args.fail_message + ' Failed to send command.')
    except serial.SerialTimeoutException:
      self.fail(self.args.fail_message + ' Timeout sending a command.')

    if self.args.send_only:
      return

    try:
      response = self._serial.read(1)
      if self._recv is not None:
        self.assertEqual(
            self._recv, response,
            '%s Response mismatch; expect: 0x%X, actual: 0x%X.' % (
                self.args.fail_message, ord(self._recv), ord(response)))
    except serial.SerialTimeoutException:
      self.fail(self.args.fail_message + ' Timeout receiving a response.')
