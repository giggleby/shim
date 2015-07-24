# -*- coding: utf-8 -*-
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test for checking touchscreen uniformity.

This test is intended to be run during run-in without a fixture or operator.
The test reads raw reference (baseline) data. Each value must fall within a
specified max and min range. Delta values (the baseline - current reading)
are also checked.

Sample test_list entry::

  OperatorTest(
    id='TouchscreenUniformity',
    label_zh=u'触屏均一性测试',
    run_if='device_data.component.has_touchscreen',
    pytest_name='touchscreen_uniformity',
    dargs={'deltas_max_val': 400,
           'deltas_min_val': 0,
           'refs_max_val': 45000,
           'refs_min_val': 10000,
           'i2c_bus_id': '2-002c'})

The args thresholds in need to be experimentally determined by checking
a set of machines. The test logs the actual max and min values found.
"""

from __future__ import print_function  # to support print

import logging
import os
import time
import unittest
import numpy

import factory_common  # pylint: disable=W0611
from cros.factory.event_log import Log
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg
from cros.factory.test.factory_task import FactoryTask, FactoryTaskManager

_CALIBRATION_DELAY_SECS = 0.1
_DEFAULT_REFS_MAX = 45000
_DEFAULT_REFS_MIN = 10000
_DEFAULT_DELTAS_MAX = 400
_DEFAULT_DELTAS_MIN = 0
_DEFAULT_I2C_BUS_ID = '2-002c'

_I2C_DEVICES_PATH = '/sys/bus/i2c/devices'

_LABEL_NOT_FOUND = test_ui.MakeLabel('ERROR: Touchscreen Not Found',
    u'没有找到触屏', 'test-fail')
_LABEL_TESTING_REFERENCES = test_ui.MakeLabel('Testing References',
    u'参考值测试中', 'test-info')
_LABEL_TESTING_DELTAS = test_ui.MakeLabel('Testing Deltas',
    u'差量测试中', 'test-info')
_LABEL_PASS = test_ui.MakeLabel('PASS', u'成功', 'test-pass')
_LABEL_FAIL = test_ui.MakeLabel('FAIL', u'失败', 'test-fail')
_MESSAGE_DELAY_SECS = 1

_BR = '<br/>'

_CSS = """
  .test-info {font-size: 2em;}
  .test-pass {font-size: 2em; color:green;}
  .test-fail {font-size: 2em; color:red;}
"""

class WDT87xxTouchController(object):
  """Utility class for the WDT87xx touch controller.

  Args:
    i2c_bus_id: String. I2C device identifier. Ex: '2-002c'
  """

  def __init__(self, i2c_bus_id, matrix_size):
    i2c_device_path = os.path.join(_I2C_DEVICES_PATH, i2c_bus_id)
    self.object_path = os.path.join(i2c_device_path, 'fw_version')
    self.rows = None
    self.cols = None
    self.rows_enabled = None
    self.cols_enabled = None
    if matrix_size is not None:
      self.rows_enabled, self.cols_enabled = matrix_size

  def IsPresent(self):
    """Checks that the touch controller is present.

    Returns:
      True if the controller is present.
    """
    return os.path.exists(self.object_path)

  def _ReadRaw(self, filename):
    """Reads rows * cols touchscreen sensor raw data.

    Args:
      filename: Name of the raw data file to open from within the
                kernel debug directory.
    Retruns:
      Raw data as a [row][col] array of ints.
    """
    raw_data = []

    file_path = ''
    exec_cmd = '/usr/local/factory/board/touch_wdt/wdt_ct_linux'
    if filename == 'refs':
      file_path = '/tmp/ref_raw.dat'
      exec_cmd += ' -i 2 -a 2 > ' + file_path
    elif filename == 'deltas':
      file_path = '/tmp/proc_raw.dat'
      exec_cmd += ' -i 2 -a 1 > ' + file_path
    else:
      return raw_data

    os.system(exec_cmd)

    logging.info('exec_cmd %s', exec_cmd)

    f = open(file_path)

    # skip lines useless
    for _line_idx in range(0, 5, 1):
      f.readline()

    # get the parameters
    params_str = f.readline()
    params_str = params_str.replace("\n", "")
    params_str = params_str.replace(",", "")
    params_tok = params_str.split(" ")
    param_width = params_tok[0].split("=")
    param_height = params_tok[1].split("=")
    param_x0 = params_tok[2].split("=")
    param_x1 = params_tok[3].split("=")
    param_y0 = params_tok[4].split("=")
    param_y1 = params_tok[5].split("=")

    # max row/col number
    self.rows = int(param_width[1])
    self.cols = int(param_height[1])
    # row/col used
    self.rows_enabled = int(param_x1[1])-int(param_x0[1])+1
    self.cols_enabled = int(param_y1[1])-int(param_y0[1])+1

    logging.info('Width %d Height %d X1 %d Y1 %d',
      self.rows, self.cols, self.rows_enabled, self.cols_enabled)

    line = f.readline()
    for unused_row in range(0, self.cols_enabled, 1):
      row_data = []
      line = f.readline()
      line = line.replace("\n", "")
      line_tok = line.split(",")
      for col_pos in range(0, self.rows_enabled, 1):
        val = long(line_tok[col_pos])
        row_data.append(val)

        raw_data.append(row_data)

    return raw_data

  def ReadDeltas(self):
    """Read raw delta information from the controller

    Return:
      A [row][col] list of raw data values.
    """
    logging.info('Reading deltas')
    return self._ReadRaw('deltas')

  def ReadRefs(self):
    """Reads raw reference (baseline) information from the controller.

    Return:
      A [row][col] list of raw data values.
    """
    logging.info('Reading refs')
    return self._ReadRaw('refs')

class CheckRawDataTask(FactoryTask):
  """Checks raw controler data is in an expected range.

  Args:
    test: The factory test calling this task.
    data_name: String. A short name of the data type being checked. The name
               must match the sysfs entries under the I2C device path.
    ui_label: String. Formatted HTML to append to the test UI.
    FetchData: The function to call to retrieve the test data to check.
    min_val: Int. The lower bound to check the raw data against.
    max_val: Int. The upper bound to check the raw data against.
  """

  def __init__(self, test, data_name, ui_label, FetchData, min_val, max_val):
    super(CheckRawDataTask, self).__init__()
    self.template = test.template
    self.data_name = data_name
    self.ui_label = ui_label
    self.FetchData = FetchData
    self.min_val = min_val
    self.max_val = max_val

  def checkRawData(self):
    """Checks that data from self.FetchData is within bounds.

    Returns:
      True if the data is in bounds.
    """
    logging.info('Checking %s values are between %d and %d',
                 self.data_name, self.min_val, self.max_val)
    check_passed = True
    data = self.FetchData()
    for row_index in range(len(data)):
      for col_index in range(len(data[row_index])):
        val = data[row_index][col_index]
        if (val < self.min_val or val > self.max_val):
          logging.info(
              'Raw data out of range: row=%d, col=%s, val=%d',
              row_index, col_index, val)
          check_passed = False

    merged_data = sum(data, [])
    actual_min_val = min(merged_data)
    actual_max_val = max(merged_data)
    standard_deviation = float(numpy.std(merged_data))
    logging.info('Lowest value: %d', actual_min_val)
    logging.info('Highest value: %d', actual_max_val)
    logging.info('Standard deviation %f', standard_deviation)
    Log('touchscreen_%s_stats' % self.data_name,
        **{
           'allowed_min_val': self.min_val,
           'allowed_max_val': self.max_val,
           'acutal_min_val': actual_min_val,
           'acutal_max_val': actual_max_val,
           'standard_deviation': standard_deviation,
           'test_passed': check_passed,
          }
    )

    return check_passed

  def Run(self):
    self.template.SetState(self.ui_label, append=True)
    if self.checkRawData():
      self.template.SetState(' ' + _LABEL_PASS + _BR, append=True)
      self.Pass()
    else:
      self.template.SetState(' ' + _LABEL_FAIL + _BR, append=True)
      self.Fail('Uniformity check on %s failed.' % self.data_name, later=True)


class CheckReferencesTask(CheckRawDataTask):
  """Checks refernece data is in an expected range."""

  def __init__(self, test):
    super(CheckReferencesTask, self).__init__(test, 'refs',
        _LABEL_TESTING_REFERENCES, test.touch_controller.ReadRefs,
        test.args.refs_min_val, test.args.refs_max_val)


class CheckDeltasTask(CheckRawDataTask):
  """Checks delta data is in an expected range."""

  def __init__(self, test):
    super(CheckDeltasTask, self).__init__(test, 'deltas',
        _LABEL_TESTING_DELTAS, test.touch_controller.ReadDeltas,
        test.args.deltas_min_val, test.args.deltas_max_val)


class CheckTouchController(FactoryTask):
  """Verifies that the touch controler interface exists."""

  def __init__(self, test):
    super(CheckTouchController, self).__init__()
    self.template = test.template
    self.touch_controller = test.touch_controller

  def Run(self):
    if self.touch_controller.IsPresent():
      self.Pass()
    else:
      self.template.SetState(_LABEL_NOT_FOUND)
      time.sleep(_MESSAGE_DELAY_SECS)
      self.Fail('Touch controller not found.')


class WaitTask(FactoryTask):
  """Waits for a specified number of seconds.

  Args:
    delay: Number of seconds to wait.
  """

  def __init__(self, delay):
    super(WaitTask, self).__init__()
    self.delay = delay

  def Run(self):
    time.sleep(self.delay)
    self.Pass()


class TouchscreenUniformity(unittest.TestCase):

  ARGS = [
    Arg('refs_max_val', int, 'Maximum value for reference data.',
      default=_DEFAULT_REFS_MAX, optional=True),
    Arg('refs_min_val', int, 'Minimum value for reference data.',
      default=_DEFAULT_REFS_MIN, optional=True),
    Arg('deltas_max_val', int, 'Maximum value for delta data.',
      default=_DEFAULT_DELTAS_MAX, optional=True),
    Arg('deltas_min_val', int, 'Minimum value for delta data.',
      default=_DEFAULT_DELTAS_MIN, optional=True),
    Arg('i2c_bus_id', str, 'i2c bus address of controller',
      default=_DEFAULT_I2C_BUS_ID, optional=True),
    Arg('matrix_size', tuple,
        'The size of touchscreen sensor row data for enabled sensors in the '
        'form of (rows, cols). This is used when the matrix size read from '
        'kernel i2c device path is different from the matrix size of enabled '
        'sensors.',
        optional=True),
  ]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.touch_controller = WDT87xxTouchController(
        self.args.i2c_bus_id, self.args.matrix_size)
    self.ui.AppendCSS(_CSS)
    self._task_manager = None

  def runTest(self):

    task_list = [
        CheckTouchController(self),
        CheckReferencesTask(self),
        CheckDeltasTask(self),
        WaitTask(_MESSAGE_DELAY_SECS)
    ]
    self._task_manager = FactoryTaskManager(self.ui, task_list)
    self._task_manager.Run()
