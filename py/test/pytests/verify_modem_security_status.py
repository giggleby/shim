# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import logging
import re
import serial
import time
import unittest
import factory_common  # pylint: disable=unused-import
from cros.factory.test.utils import serial_utils
from cros.factory.device import device_utils
class VerifyModemSecStatus(unittest.TestCase):
  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._dut.CallOutput(['stop', 'modemmanager'])
    self._serial_dev = serial_utils.SerialDevice()
    self._serial_dev.Connect(port="/dev/ttyACM0")
    self._serial_dev.SetTimeout(1, 1)
  def tearDown(self):
    if self._serial_dev:
      self._serial_dev.Disconnect()
    self._dut.CallOutput(['start', 'modemmanager'])
  def runTest(self):
    # Check whether access_level is closed already first.
    self.Send("AT@sec:status_info()")
    res = self.Recv()
    if re.search('^access_level = 0', res, re.MULTILINE):
      return
    # If access_level is still open then try to close it.
    self.Send("AT@sec:code_clear(0)")
    self.Send("AT@sec:status_info()")
    res = self.Recv()
    match = re.search('^access_level = [0-9]', res, re.MULTILINE)
    if not match or match.group(0) != 'access_level = 0':
     # If we can't close the access_level then raise this failure.
     raise type_utils.TestFailure(
         'Tried to close the access_level but it is still under %s.'
         % (match.group(0) if match is not None else 'None'))
  def Send(self, msg, slp=0.1):
    self._serial_dev.Send(msg + '\r\n')
    logging.info('send msg: %s', msg)
    time.sleep(slp)
  def Recv(self):
    res = self._serial_dev.Receive(size=0)
    res = res.rstrip('\r\n')
    logging.info('recv msg: %s', res)
    return res
