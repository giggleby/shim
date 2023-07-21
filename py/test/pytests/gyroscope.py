# Copyright 2016 The ChromiumOS Authors
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
To run a test on base gyroscope::

  {
    "pytest_name": "gyroscope",
    "args": {
      "rotation_threshold": 1.0,
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

from cros.factory.device import device_utils
from cros.factory.device import gyroscope
from cros.factory.test.i18n import _
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sync_utils


_RADIAN_TO_DEGREE = gyroscope.RADIAN_TO_DEGREE
_DEFAULT_POLL_INTERVAL = 0

class Gyroscope(test_case.TestCase):

  related_components = (test_case.TestCategory.ACCELEROMETER, )
  ARGS = [
      Arg('rotation_threshold', float,
          'The expected value (rad/s) to read when dut start rotating.'),
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
          'Timeout in seconds for gyro to return expected value.', default=30),
      Arg('setup_time_secs', int, 'Seconds to wait before starting the test.',
          default=2),
      Arg('autostart', bool, 'Auto start this test.', default=False),
      Arg('setup_sensor', bool, 'Setup gyro sensor via ectool', default=True),
      Arg('location', enum.Enum('location', ['base', 'lid']),
          'Gyro is located in "base" or "lid".', default='base'),
      Arg('capture_count', int,
          'How many records to read for each time getting data', default=50),
      Arg('sample_rate', int, 'Sample rate in Hz to read data from sensors',
          default=200)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.gyroscope = self.dut.gyroscope.GetController(
        location=self.args.location,
        gyro_id=self.args.gyro_id,
        freq=self.args.freq)
    self.ui.ToggleTemplateClass('font-large', True)

  def runTest(self):
    if self.args.setup_sensor:
      self.gyroscope.SetupMotionSensor()

    logging.info('%r', self.gyroscope)

    if not self.args.autostart:
      self.ui.SetInstruction(
          _('Please put device on a horizontal plane then press space to '
            'start testing.'))
      self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    for i in range(self.args.setup_time_secs):
      self.ui.SetInstruction(
          _(
              'Test will be started within {secs} seconds. '
              'Please do not move the device.',
              secs=self.args.setup_time_secs - i))
      self.Sleep(1)

    logging.info('Wait for device stop.')
    self.ui.SetInstruction(_('Please do not move the device.'))
    self._WaitForDeviceStop()

    logging.info('Wait for device rotate.')
    self.ui.SetInstruction(_('Please rotate the device.'))
    self.SetImage('chromebook.png')
    self._WaitForDeviceRotate()

  def _UpdateState(self, data, is_passed, rule_text, rotation_degree):
    html = [f'<div>{rule_text}</div>']
    degree_x, degree_y, degree_z = 0, 0, 0
    for k, v in data.items():
      state = ('test-status-passed' if is_passed[k] else 'test-status-failed')
      axis = re.match(r'in_anglvel_(?P<axis>x|y|z)', k).group('axis')
      if axis == 'x':
        degree_x = int(rotation_degree[k])
      elif axis == 'y':
        degree_y = int(rotation_degree[k])
      elif axis == 'z':
        degree_z = int(rotation_degree[k])

      html.append(f'<div class="{state}">{test_ui.Escape(k)}={v:.4f} rad/s,'
                  f'{rotation_degree[k]:.2f} deg</div>')

    self.RotateImage(degree_x, degree_y, degree_z)
    self.ui.SetHTML(''.join(html), id='state')

  def _UpdateRotationDegree(self, data, rotation_degree, time_period):
    for k, v in data.items():
      degree = v * _RADIAN_TO_DEGREE
      rotation_degree[k] += degree * time_period

  def _WaitForDeviceStop(self):
    """Wait until absolute value of all sensors less than stop_threshold."""

    rotation_degree = collections.defaultdict(int)

    def CheckSensorState():
      data = self.gyroscope.GetData()
      logging.info('sensor value: %r', data)
      is_passed = {
          k: abs(v) < self.args.stop_threshold
          for k, v in data.items()
      }
      self._UpdateState(data, is_passed, f'< {self.args.stop_threshold:.10f}',
                        rotation_degree)
      return all(is_passed.values())

    sync_utils.WaitFor(CheckSensorState, self.args.timeout_secs)

  def _WaitForDeviceRotate(self):
    """Wait until all sensors has absolute value > rotation_threshold."""

    max_values = collections.defaultdict(float)
    rotation_degree = collections.defaultdict(int)

    def CheckSensorMaxValues():
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
      for sensor_name, value in cleaned_data.items():
        max_values[sensor_name] = max(max_values[sensor_name], abs(value))
      is_passed = {
          k: v > self.args.rotation_threshold
          for k, v in max_values.items()
      }
      after_get_data = time.time()
      self._UpdateRotationDegree(cleaned_data, rotation_degree,
                                 after_get_data - before_get_data)
      self._UpdateState(max_values, is_passed,
                        f'> {self.args.rotation_threshold:.10f}',
                        rotation_degree)
      return all(is_passed.values())

    sync_utils.WaitFor(condition=CheckSensorMaxValues,
                       timeout_secs=self.args.timeout_secs,
                       poll_interval=_DEFAULT_POLL_INTERVAL)

  def SetImage(self, url):
    """Sets the image src."""
    self.ui.RunJS('document.getElementById("chromebook_img").src = args.url;',
                  url=url)

  def RotateImage(self, degree_x, degree_y, degree_z):
    """Rotates the image according to the degree captured."""
    if self.args.location == 'base':
      # Switch y and z axis as the image follows the axes of the screen
      degree_y, degree_z = degree_z, degree_y
    if self.args.location == 'lid':
      # Turn y and z values into negative as the axes have opposite direction
      degree_y, degree_z = -degree_y, -degree_z

    self.ui.RunJS(f'document.getElementById("chromebook_img").style.transform '
                  f'="rotateX({degree_x}deg) rotateY({degree_y}deg) '
                  f'rotateZ({degree_z}deg)";')
