# -*- coding: utf-8 -*-
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Initializing touchscreen mask for power on palm.

This test is intended to be run during fatp without a fixture or operator.
The test will request the weida's controller to scan the panel defects and save
the mask data in flash for doing further palm testing.

Sample test_list entry::

    OperatorTest(
        id='TouchscreenInitMask',
        label_zh=u'触屏初始化',
        run_if=self.HasTouchscreen,
        pytest_name='wdt_touchscreen_init',
        dargs={'i2c_bus_id': '%d-002c' % self.touchscreen_i2c_bus})

"""

from __future__ import print_function  # to support print

import logging
import os
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg
from cros.factory.test.factory_task import FactoryTask, FactoryTaskManager
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils.sys_utils import GetI2CBus

_DEFAULT_I2C_BUS_ID = '2-002c'

_I2C_DEVICES_PATH = '/sys/bus/i2c/devices'

_FACTORY_PATH = '/usr/local/factory'

_LABEL_NOT_FOUND = test_ui.MakeLabel('ERROR: Touchscreen Not Found',
    u'没有找到触屏', 'test-fail')
_LABEL_TESTING_MASK = test_ui.MakeLabel('Initializing, No touch',
    u'初始中 勿觸摸', 'test-info')
_LABEL_PASS = test_ui.MakeLabel('PASS', u'成功', 'test-pass')
_LABEL_FAIL = test_ui.MakeLabel('FAIL', u'失败', 'test-fail')
_MESSAGE_DELAY_SECS = 1

_BR = '<br/>'

_CSS = """
  .test-info {font-size: 2em;}
  .test-pass {font-size: 2em; color:green;}
  .test-fail {font-size: 2em; color:red;}
"""

class WDT87xxTouchControllerInit(object):
  """Utility class for the WDT87xx touch controller.

  Args:
    i2c_bus_id: String. I2C device identifier. e.g.: '2-002c'
  """

  def __init__(self, i2c_bus_id):
    i2c_device_path = os.path.join(_I2C_DEVICES_PATH, i2c_bus_id)
    self._sysfs_fw_path = os.path.join(i2c_device_path, 'fw_version')
    self._utility_cmd = os.path.join(_FACTORY_PATH, 'board', 'touch_wdt',
                                     'wdt_ct_linux')
    logging.info('cmd %s', self._utility_cmd)

  def IsPresent(self):
    """Checks that the touch controller is present.

    Returns:
      True if the controller is present.
    """
    return os.path.exists(self._sysfs_fw_path)

  def ResetController(self):
    """Reset the controller."""
    logging.info('Reset the controller')
    Spawn([self._utility_cmd, '-i', '2', '-r'], call=True)

  def CheckMask(self):
    """Execute the command to check the mask of the controller.

    Retruns:
      True if the mask is existed.
    """
    logging.info('Check mask')

    with file_utils.UnopenedTemporaryFile() as temp:
      Spawn(self._utility_cmd + ' -i 2 -m 2 > ' + temp, call=True, shell=True)

      with open(temp) as f:
        # skip tool information lines, like below:
        #   Weida Hitech Command Tool V0.9.13
        #   Found the wdt87xx i2c-dev: /dev/i2c-2
        #   TouchPanelTest : Check Mask
        for _line_idx in xrange(3):
          f.readline()

        # get the result
        result_str = f.readline()
        logging.info('str %s', result_str)

        return 'existed' in result_str

  def SetMask(self):
    """Request the controller to set mask."""
    logging.info('Set mask')
    Spawn([self._utility_cmd, '-i', '2', '-m', '0'], call=True)

  def InitMask(self):
    """Request the controller to set mask and reset itself. Then check if the
       the mask is existed.

    Return:
      Ture if the mask is existed.
    """
    self.SetMask()
    self.ResetController()
    return self.CheckMask()

class CheckMaskTask(FactoryTask):
  """Check if there is mask data."""

  def __init__(self, test):
    super(CheckMaskTask, self).__init__()
    self._template = test._template
    self._touch_controller = test._touch_controller
    self._data_name = "CheckMask"
    self._ui_label = _LABEL_TESTING_MASK

  def initMaskData(self):
    """Check the mask data from touch controller.

    Returns:
      True if there is the mask data.
    """
    return self._touch_controller.InitMask()

  def Run(self):
    self._template.SetState(self._ui_label, append=True)
    time.sleep(_MESSAGE_DELAY_SECS)
    if self.initMaskData():
      self._template.SetState(' ' + _LABEL_PASS + _BR, append=True)
      self.Pass()
    else:
      self._template.SetState(' ' + _LABEL_FAIL + _BR, append=True)
      self.Fail('Mask check on %s failed.' % self._data_name, later=True)

class CheckTouchController(FactoryTask):
  """Verifies that the touch controler interface exists."""

  def __init__(self, test):
    super(CheckTouchController, self).__init__()
    self._template = test._template
    self._touch_controller = test._touch_controller

  def Run(self):
    if self._touch_controller.IsPresent():
      self.Pass()
    else:
      self._template.SetState(_LABEL_NOT_FOUND)
      time.sleep(_MESSAGE_DELAY_SECS)
      self.Fail('Touch controller not found.')

class WaitTask(FactoryTask):
  """Waits for a specified number of seconds.

  Args:
    delay: Number of seconds to wait.
  """

  def __init__(self, delay):
    super(WaitTask, self).__init__()
    self._delay = delay

  def Run(self):
    time.sleep(self._delay)
    self.Pass()

class TouchscreenInitMask(unittest.TestCase):

  ARGS = [
    Arg('i2c_bus_id', str, 'i2c bus address of controller',
        default=_DEFAULT_I2C_BUS_ID, optional=True),
  ]

  def setUp(self):
    name_list = ['WDT87xx']
    bus = GetI2CBus(name_list)
    if type(bus) is int:
      self.args.i2c_bus_id = str(bus) + '-002c'
      logging.info('Found WDT I2C Devie: %s', self.args.i2c_bus_id)

    self._ui = test_ui.UI()
    self._template = ui_templates.OneSection(self._ui)
    self._touch_controller = WDT87xxTouchControllerInit(self.args.i2c_bus_id)
    self._ui.AppendCSS(_CSS)
    self._task_manager = None

  def runTest(self):
    task_list = [
        CheckTouchController(self),
        CheckMaskTask(self),
        WaitTask(_MESSAGE_DELAY_SECS)
    ]
    self._task_manager = FactoryTaskManager(self._ui, task_list)
    self._task_manager.Run()
