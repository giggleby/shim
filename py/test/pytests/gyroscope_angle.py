# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A factory test for gyroscopes.

Description
-----------
There are steps required to run a complete gyroscope test::
  - Motion sensor setup via `ectool motionsense odr ${gyro_id} ${freq}`
  - (optional) Calibration for tri-axis (x, y, and z) gyroscopes.
  - The main gyroscope test.

This pytest executes the motion sensor setup and main gyro test in sequence.

Test Procedure
--------------
This test supports and enables auto start by default.  In this case::
1. Put the device (base/lid) on a static plane then press space.
2. Wait for completion.

Otherwise operators will be asked to place DUT on a horizontal plane and
press space.

Dependency
----------
- Device API (``cros.factory.device.gyroscope``).

Examples
--------
To run the test on base gyroscope::

  {
    "pytest_name": "gyroscope_angle",
    "args": {
      "rotation_threshold": 90,
      "stop_threshold": 0.1,
      "location": "base"
    }
  }
"""

import collections
import enum
import logging
import re
import statistics
import time
from typing import Optional

from cros.factory.device import device_utils
from cros.factory.device import gyroscope
from cros.factory.goofy.plugins import display_manager
from cros.factory.goofy.plugins import plugin_controller
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sync_utils


_RADIAN_TO_DEGREE = gyroscope.RADIAN_TO_DEGREE
_DEFAULT_POLL_INTERVAL = 0


class Gyroscope(test_case.TestCase):

  ARGS = [
      Arg('rotation_threshold', int,
          'The expected rotating degree for the dut to reach during rotation.',
          default=90),
      Arg('stop_threshold', float,
          'The expected value to read when dut stop moving.'),
      Arg('gyro_id', int,
          'Gyroscope ID.  Will read a default ID via ectool if not set.',
          default=None),
      Arg(
          'freq', int,
          'Gyroscope sampling frequency in mHz.  Will apply the minimal '
          'frequency from ectool info if not set.', default=None),
      Arg('timeout_secs', int,
          'Timeout in seconds for gyro to return expected value.', default=60),
      Arg('setup_time_secs', int, 'Seconds to wait before starting the test.',
          default=2),
      Arg('autostart', bool, 'Auto start this test.', default=False),
      Arg('setup_sensor', bool, 'Setup gyro sensor via ectool', default=True),
      Arg('location', enum.Enum('location', ['base', 'lid']),
          'Gyro is located in "base" or "lid".', default='base'),
      Arg('capture_count', int,
          'How many records to read for each time getting data', default=40),
      Arg('sample_rate', int, 'Sample rate in Hz to read data from sensors',
          default=200)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

    self._display_manager: Optional[display_manager.DisplayManager] = (
        plugin_controller.GetPluginRPCProxy('display_manager'))
    if not self._display_manager:
      raise RuntimeError('display_manager plugin is not defined.')

    self.gyroscope = self.dut.gyroscope.GetController(
        location=self.args.location, gyro_id=self.args.gyro_id,
        freq=self.args.freq)
    self.ui.ToggleTemplateClass('font-large', True)
    self._display_manager.SetInternalDisplayRotation(0)
    self.addCleanup(self._display_manager.SetInternalDisplayRotation, -1)

  def runTest(self):
    if self.args.setup_sensor:
      self.gyroscope.SetupMotionSensor()

    logging.info('%r', self.gyroscope)

    if not self.args.autostart:
      self.ui.SetHTML(
          'Please put device on a horizontal plane then press space to '
          'start testing.', id='instruction')
      self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    for i in range(self.args.setup_time_secs):
      self.ui.SetHTML(
          f'Test will be started within {self.args.setup_time_secs-i} '
          'seconds. Please do not move the device.', id='instruction')
      self.Sleep(1)

    logging.info('Wait for device stop.')
    self.ui.SetHTML('Please do not move the device.', id='instruction')
    self._WaitForDeviceStop()

    logging.info('Wait for device rotate.')
    self.SetImage('chromebook.png')
    for axis in ['x', 'y', 'z']:
      self.ui.SetHTML(
          f'Please rotate the device along the <b>{axis} axis until '
          f'> {self.args.rotation_threshold}</b>.', id='instruction')
      self.ShowRotationAnimation(axis)
      self._WaitForDeviceRotate(axis)
      # Rotate the image back to original position for the next axis
      self.RotateImage(axis, 0, 0, 0)
      self.Sleep(1)

  def _UpdateState(self, test_axis, rotation_degree):
    html = ['']
    degree_x, degree_y, degree_z = 0, 0, 0
    degree_progress = 0
    for k, v in rotation_degree.items():
      axis = re.match(r'in_anglvel_(?P<axis>x|y|z)', k).group('axis')
      if axis == test_axis:
        degree_progress = int(v)
      if axis == 'x':
        degree_x = int(v)
      elif axis == 'y':
        degree_y = int(v)
      elif axis == 'z':
        degree_z = int(v)

      html.append(f'<div>{axis}: {rotation_degree[k]:.2f} deg</div>')

    self.RotateImage(test_axis, degree_x, degree_y, degree_z)
    progress = self.SetProgress(test_axis, degree_progress)
    self.ui.SetHTML(''.join(html), id='state')
    return progress >= 100

  def _UpdateRotationDegree(self, data, rotation_degree, time_period):
    for k, v in data.items():
      degree = v * _RADIAN_TO_DEGREE
      rotation_degree[k] += degree * time_period

  def _WaitForDeviceStop(self):
    """Wait until absolute value of all sensors less than stop_threshold."""

    def CheckSensorState():
      data = self.gyroscope.GetData()
      logging.info('sensor value: %r', data)
      is_passed = {
          k: abs(v) < self.args.stop_threshold
          for k, v in data.items()
      }
      return all(is_passed.values())

    sync_utils.WaitFor(CheckSensorState, self.args.timeout_secs)

  def _WaitForDeviceRotate(self, test_axis):
    """Waits until all sensors has absolute value > rotation_threshold."""

    rotation_degree = collections.defaultdict(int)

    def CheckSensorMaxValue():
      before_get_data = time.time()
      data = self.gyroscope.GetData(capture_count=self.args.capture_count,
                                    sample_rate=self.args.sample_rate,
                                    average=False)

      cleaned_data = collections.defaultdict(float)
      for sensor_name, values in data.items():
        # Remove the first five data items since the sensor bug caused the
        # first few data to be incorrect. After experimenting with different
        # values, 5 is the smallest value to avoid wrong data items
        # and minimize data lost
        cleaned_data[sensor_name] = statistics.mean(values[5:])
      logging.info('sensor value: %r', data)
      after_get_data = time.time()
      self._UpdateRotationDegree(cleaned_data, rotation_degree,
                                 after_get_data - before_get_data)
      passed = self._UpdateState(test_axis, rotation_degree)
      return passed

    sync_utils.WaitFor(condition=CheckSensorMaxValue,
                       timeout_secs=self.args.timeout_secs,
                       poll_interval=_DEFAULT_POLL_INTERVAL)

  def SetImage(self, url):
    """Sets the image src."""
    self.ui.RunJS('document.getElementById("chromebook_img").src = args.url;',
                  url=url)
    self.ui.RunJS(
        f'document.getElementById("xaxis_instruction").style.backgroundImage '
        f'= "url({url})";')
    self.ui.RunJS(
        f'document.getElementById("yaxis_instruction").style.backgroundImage '
        f'= "url({url})";')
    self.ui.RunJS(
        f'document.getElementById("zaxis_instruction").style.backgroundImage '
        f'= "url({url})";')

  def RotateImage(self, test_axis, degree_x, degree_y, degree_z):
    """Rotates the image according to the degree captured."""
    if self.args.location == 'base':
      # Switch y and z axis as the image follows the axes of the screen
      degree_y, degree_z = degree_z, degree_y
    if self.args.location == 'lid':
      # Turn y and z values into negative as the axes have opposite direction
      degree_y, degree_z = -degree_y, -degree_z

    rotate_command = ''
    if test_axis == 'x':
      rotate_command = f'rotateX({degree_x}deg)'
    elif test_axis == 'y' and self.args.location == 'lid':
      rotate_command = f'rotateY({degree_y}deg)'
    elif test_axis == 'y' and self.args.location == 'base':
      # Rotate along z axis as the image follows the axes of the screen
      rotate_command = f'rotateZ({degree_z}deg)'
    elif test_axis == 'z' and self.args.location == 'lid':
      rotate_command = f'rotateZ({degree_z}deg)'
    elif test_axis == 'z' and self.args.location == 'base':
      # Rotate along y axis as the image follows the axes of the screen
      rotate_command = f'rotateY({degree_y}deg)'

    self.ui.RunJS(f'document.getElementById("chromebook_img").style.transform '
                  f'="{rotate_command}";')

  def SetProgress(self, test_axis, degree_progress):
    percent = 100 * abs(degree_progress) / self.args.rotation_threshold
    self.ui.RunJS(
        f'document.getElementById("{test_axis}axis_progress").style.background '
        '= "radial-gradient(closest-side, white 84%, transparent 85% 100%)'
        f', conic-gradient(green {percent}%, lightgray 0)";')
    return percent

  def ShowRotationAnimation(self, test_axis):
    animation_axis = test_axis
    if self.args.location == 'base':
      # Switch y and z axis as the image follows the axes of the screen
      if test_axis == 'y':
        animation_axis = 'z'
      elif test_axis == 'z':
        animation_axis = 'y'

    self.ui.RunJS(f'document.getElementById("{test_axis}axis_instruction")'
                  f'.style.animation="{animation_axis}_rotation 3s infinite";')
