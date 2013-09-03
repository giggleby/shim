# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
# This factory test will set modem to LTE only mode to prevent abnormal
# behavior.

import re
import serial as pyserial
import unittest

from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg
from cros.factory.event_log import EventLog
from cros.factory.utils.process_utils import Spawn

_TEST_TITLE = test_ui.MakeLabel('Set modem to LTE only mode.',
                                u'数据机模式设定')
DEVICE_NORMAL_RESPONSE = 'OK'
DEVICE_LTE_MODE_RESPONSE = 'LTE ONLY'


class Error(Exception):
  '''Generic fatal error.
  '''
  pass


class _Serial(object):
  '''Simple wrapper for pySerial.
  '''
  def __init__(self, dev_path):
    # Directly issue commands to the modem.
    self.serial = pyserial.Serial(dev_path, timeout=2)
    self.serial.read(self.serial.inWaiting())  # Empty the buffer.

  def read_response(self):
    '''Reads response from the modem until a timeout.'''
    line = self.serial.readline()
    factory.log('modem[ %r' % line)
    return line.rstrip('\r\n')

  def send_command(self, command):
    '''Sends a command to the modem and discards the echo.'''
    self.serial.write(command + '\r')
    factory.log('modem] %r' % command)
    self.read_response()

  def check_response(self, expected_re):
    '''Checks response with a regular expression returns a SRE_Match object.'''
    response = self.read_response()
    re_ret = re.search(expected_re, response)
    if not re_ret:
      raise Error('Expected %r but got %r' % (expected_re, response))
    return re_ret


class CelluarModeTest(unittest.TestCase):
  ARGS = [
    Arg('modem_path', str,
        'Path to the modem, for example: /dev/ttyUSB0.',
        default='/dev/ttyUSB0', optional=True)
  ]

  def __init__(self, *args, **kwargs):
    super(CelluarModeTest, self).__init__(*args, **kwargs)
    self.task_list = []
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS('.start-font-size {font-size: 2em;}')
    self.template.SetTitle(_TEST_TITLE)
    self.event_log = EventLog.ForAutoTest()

  def SetLTEMode(self):
    '''Set modem to LTE mode.'''
    # Stop modem manager first.
    Spawn(['stop', 'modemmanager'],
          call=True, ignore_stderr=True, log=True)
    # Directly issue commands to the modem.
    modem = _Serial(self.args.modem_path)
    # Send an AT command and expect 'OK'
    modem.send_command('AT$NWPREFMODE=30')
    modem.check_response(DEVICE_NORMAL_RESPONSE)
    modem.send_command('AT$NWPREFMODE?')
    modem.check_response(DEVICE_LTE_MODE_RESPONSE)
    modem.send_command('AT+CFUN=6')
    modem.check_response(DEVICE_NORMAL_RESPONSE)

  def runTest(self):
    self.SetLTEMode()
