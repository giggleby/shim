# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
# This factory test will probe the basic information of a cellular modem.
#
# For the iccid test, please note this test requires a SIM card,
# a test SIM is fine. The SIM does NOT need to have an account
# provisioned.

# Following parameters are provided via dargs:
# 'imei_re': The regular expression of expected IMEI, first group of the
#            regular expression will be extracted. None value to skip this
#            item.
# 'iccid_re': The regular expression of expected ICCID, first group of the
#             regular expression will be extracted. None value to skip this
#             item.
# 'modem_path': Path to the modem, for ex: /dev/ttyUSB0. Setting this implies
#               use AT command directly with the modem. Otherwise, flimflam
#               will handle the extraction.
# 'pin_command': Additional PIN related command to execute before extracts
#                the ICCID.
#

import re
import serial as pyserial
import unittest

from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test import utils
from cros.factory.test.factory_task import FactoryTask, FactoryTaskManager
from cros.factory.event_log import EventLog

_TEST_TITLE = test_ui.MakeLabel('SIM / IMEI / MEID Extraction',
                                u'數據機資訊提取')
DEVICE_NORMAL_RESPONSE = 'OK'


def CheckOutput(event_log, *args, **kwargs):
  """A wrapper for CheckOutput to log detail information of command execution.
     Any exception will be logged and return the exception in string format.
  """
  try:
    exception_str = ''
    output = utils.CheckOutput(*args, **kwargs)
  except Exception as e:
    output = exception_str = 'Exception in detail %s' % e
  finally:
    event_log.Log('command_detail',
                  command_args=args,
                  command_kwargs=kwargs,
                  command_return=output)
  return output


class Error(Exception):
  """Generic fatal error."""
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


class IMEITask(FactoryTask):
  def __init__(self, test): # pylint: disable=W0231
    self.test = test

  def Run(self):
    if not self.test.modem_path:
      # TODO(itspeter): Parse flimflam to get the IMEI.
      modem_info = CheckOutput(self.test.event_log, ['mmcli', '-m','0'])
      imei = re.search(self.test.imei_re, modem_info)
      # Check the imei format.
      if not imei:
        raise Error('Expected %r but got %r' % (self.test.imei_re, modem_info))
      else:
        imei = imei.group(1)
    else:
      # Directly issue commands to the modem.
      modem = _Serial(self.test.modem_path)
      # Send an AT command and expect 'OK'
      modem.send_command('AT')
      modem.check_response(DEVICE_NORMAL_RESPONSE)
      modem.send_command('AT+CGSN')
      imei = modem.check_response(self.test.imei_re).group(1)

    self.test.event_log.Log('imei', imei=imei)
    factory.log('IMEI: %s' % imei)
    self.Stop()


class ICCIDTask(FactoryTask):
  def __init__(self, test): # pylint: disable=W0231
    self.test = test

  def Run(self):
    if not self.test.modem_path:
      # TODO(itspeter): Parse flimflam to get the ICCID.
      if self.test.pin_command: # Additional command to manipulate sim.
        pin_ret = CheckOutput(
            self.test.event_log,
            ['mmcli', '-i', '0'] + self.test.pin_command)
        factory.log('pin command returned:%s' % pin_ret)

      sim_info = CheckOutput(self.test.event_log, ['mmcli', '-i', '0'])
      iccid = re.search(self.test.iccid_re, sim_info)
      # Check the iccid format.
      if not iccid:
        raise Error('Expected %r but got %r' % (self.test.iccid_re, sim_info))
      else:
        iccid = iccid.group(1)
    else:
      # Directly issue commands to the modem.
      modem = _Serial(self.test.modem_path)
      # Send an AT command and expect 'OK'
      modem.send_command('AT')
      modem.check_response(DEVICE_NORMAL_RESPONSE)
      modem.send_command('AT+ICCID?')
      iccid = modem.check_response(self.test.iccid_re).group(1)
    self.test.event_log.Log('iccid', iccid=iccid)
    factory.log('ICCID: %s' % iccid)
    self.Stop()


class StartTest(unittest.TestCase):
  def __init__(self, *args, **kwargs):
    super(StartTest, self).__init__(*args, **kwargs)
    self.task_list = []
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS('.start-font-size {font-size: 2em;}')
    self.template.SetTitle(_TEST_TITLE)
    self.event_log = EventLog.ForAutoTest()

  def runTest(self):
    # Allow attributes to be defined outside __init__
    # pylint: disable=W0201
    args = self.test_info.args
    self.modem_path = args.get('modem_path', None)
    self.imei_re = args.get('imei_re', None)
    self.iccid_re = args.get('iccid_re', None)
    self.pin_command = args.get('pin_command', None)
    self.meid_re = args.get('meid_re', None)
    self.prompt = args.get('prompt', None)

    if self.prompt:
      # TODO(itspeter): add a prompt screen.
      raise NotImplementedError

    if self.imei_re:
      self.task_list.append(IMEITask(self))

    if self.iccid_re:
      self.task_list.append(ICCIDTask(self))

    if self.meid_re:
      # TODO(itspeter): Implment this extraction for CDMA.
      raise NotImplementedError

    FactoryTaskManager(self.ui, self.task_list).Run()
