# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to check if the proximity sensor triggers events properly.

Description
-----------
It captures the proximity events from the given sensor device
(usually ``/dev/proximity-*``) and verifies if the ``close/far`` events are
triggered properly.

A typical use case of proximity sensor is controlling SAR.

Note that:

1. This test doesn't support station-based remote test yet.
2. This test stops ``powerd`` service when it is capturing the events.

Test Procedure
--------------
This test requires the operator to provide some actions.

1. The test shows instruction to ask the operator to remove the cover.
2. Wait until the sensor value is small enough.
3. The test shows instruction to ask the operator to cover the sensor.
4. The test starts to wait for proximity events.
5. If the first captured event is not a ``close`` event, the test ends with
   failure.
6. The test shows instruction to ask the operator to remove the cover.
7. The test starts to wait for proximity events.
8. If the first captured event is not a ``far`` event, the test ends with
   failure.
9. If timeout reaches before all the tasks done, the test also ends with
   failure.

Dependency
----------

Examples
--------
Let's assume we want to test the sensor device ``/dev/iio:device7``, which
``echo /sys/bus/iio/devices/iio:device7/name`` outputs sx9310, just add a test
item in the test list::

  {
    "pytest_name": "proximity_sensor",
    "disable_services": [
      "powerd"
    ],
    "args": {
      "device_name": "sx9310"
    }
  }

To provide the operator detail instructions, we can specify the messages to
show in the test list::

  {
    "pytest_name": "proximity_sensor",
    "disable_services": [
      "powerd"
    ],
    "args": {
      "device_name": "sx9310",
      "close_instruction": "i18n! Please cover the left edge by hand",
      "far_instruction": "i18n! Please remove the cover"
    }
  }

To test the multiple sensor devices with the same device_name, add a test items
in the test list::

  {
    "pytest_name": "proximity_sensor",
    "disable_services": [
      "powerd"
    ],
    "args": {
      "device_name": "sx9324",
      "device_count": 2
    }
  }

"""

import ctypes
import enum
import fcntl
import logging
import mmap
import os
import select

from cros.factory.device import device_utils
from cros.factory.device import sensor_utils
from cros.factory.test.i18n import _
from cros.factory.test.i18n import arg_utils as i18n_arg_utils
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


IIO_GET_EVENT_FD_IOCTL = 0x80046990

PROXIMITY_EVENT_BUF_SIZE = 16
_DEFAULT_CALIBRATE_PATH = 'events/in_proximity0_thresh_either_en'
_DEFAULT_SENSOR_VALUE_PATH = 'in_proximity0_raw'


class ProximityEventType(int, enum.Enum):
  close = 0
  far = 1

  def __str__(self):
    return self.name


class ProximitySensor(test_case.TestCase):
  related_components = (test_case.TestCategory.SAR_SENSOR, )
  ARGS = [
      Arg(
          'device_name', str,
          'If present, the device name specifying which sensor to test. Auto'
          'detect the device if not present', default=None),
      Arg('device_count', int, 'How many devices with device_name to test',
          default=1),
      Arg('calibrate_path', str, ('The path to enable testing.  '
                                  'Must be relative to the iio device path.'),
          default=_DEFAULT_CALIBRATE_PATH),
      Arg('enable_sensor_sleep_secs', (int, float),
          'The seconds of sleep after enabling sensor.', default=1),
      Arg('sensor_value_path', str,
          ('The path of the sensor value to show on the UI.  Must be relative '
           'to the iio device path.  If it is None then show nothing.'),
          default=_DEFAULT_SENSOR_VALUE_PATH),
      Arg('sensor_initial_max', int,
          ('The test will start after the sensor value lower than this value.  '
           'If it is None then do not wait.'), default=50),
      i18n_arg_utils.I18nArg(
          'close_instruction',
          'Message for the action to trigger the ``close`` event.',
          default=_('Please cover the sensor by hand')),
      i18n_arg_utils.I18nArg(
          'far_instruction',
          'Message for the action to trigger the ``far`` event.',
          default=_('Please un-cover the sensor')),
      Arg('timeout', int, 'Timeout of the test.', default=15)
  ]

  _POLLING_TIME_INTERVAL = 0.1

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    # TODO(cyueh): Find a way to support open, close, read fd on remote DUT.
    if not self._dut.link.IsLocal():
      raise ValueError('The test does not work on remote DUT.')
    self.assertTrue(self.args.sensor_initial_max is None or
                    self.args.sensor_value_path)
    self._event_fd = None
    self.stop_countdown_event = None
    attr_filter = {
        self.args.calibrate_path: None,
        'name': self.args.device_name
    }
    if self.args.sensor_value_path:
      attr_filter.update({self.args.sensor_value_path: None})
    self._iio_device_path_list = sensor_utils.FindDevice(
        self._dut, sensor_utils.IIO_DEVICES_PATTERN, allow_multiple=True,
        **attr_filter)

    if len(self._iio_device_path_list) != self.args.device_count:
      raise ValueError('Found unexpected device number. Found: '
                       f'{self._iio_device_path_list}')

  def runTest(self):
    errors = {}
    for device_path in self._iio_device_path_list:
      logging.info('Testing iio device with path: %s', device_path)
      # If the sensor is enabled by default then we don't want to disable it
      # after the test.
      initial_state = self._GetSensorState(device_path)
      self.addCleanup(self._SensorSwitcher, initial_state, device_path)
      try:
        self._RunSubTest(device_path)
      except Exception as e:
        errors[device_path] = e
      finally:
        self._SubTestCleanup(device_path)
    if errors:
      self.FailTask(errors)

  def _RunSubTest(self, device_path):
    # TODO(jimmysun) Migrate: how we read value, calibrate, enable sensor and
    # how we judge a close or fat event. b/297977526.
    self.stop_countdown_event = self.ui.StartFailingCountdownTimer(
        self.args.timeout)
    # We must enable the sensor before os.open. Otherwise the sensor may create
    # ghost event.
    self._SensorSwitcher(sensor_utils.SensorState.ON, device_path)
    # Before the test, make sure the sensor is un-covered
    sensor_value_path = self._dut.path.join(
        device_path,
        self.args.sensor_value_path) if self.args.sensor_value_path else None
    if self.args.sensor_initial_max is not None:
      self.ui.SetHTML(self.args.far_instruction,
                      id='proximity-sensor-instruction')
      self.ui.SetHTML(_('Setting the sensor'), id='proximity-sensor-value')
      self.CalibrateSensor(sensor_value_path)

    self._event_fd = self._GetEventFd(device_path)

    test_flow = [(ProximityEventType.close, self.args.close_instruction),
                 (ProximityEventType.far, self.args.far_instruction)]
    for expect_event_type, instruction in test_flow:
      self.ui.SetHTML(instruction, id='proximity-sensor-instruction')

      buf = self._ReadEventBuffer(sensor_value_path)

      got_event_type = ProximityEventType(buf[6])
      if got_event_type != expect_event_type:
        self.FailTask(f'Expect to get a {expect_event_type!r} event, but got a '
                      f'{got_event_type!r} event.')
      logging.info('Pass %s.', expect_event_type)

  def _SensorSwitcher(self, mode, device_path):
    """Enable or disable the sensor."""
    # echo value > calibrate
    if mode == self._GetSensorState(device_path):
      return
    path = self._dut.path.join(device_path, self.args.calibrate_path)
    try:
      try:
        # self.ui is not available after StartFailingCountdownTimer timeout
        self.ui.SetHTML(self.args.far_instruction,
                        id='proximity-sensor-instruction')
        self.ui.SetHTML(_('Setting the sensor'), id='proximity-sensor-value')
      except Exception:
        pass
      self._dut.WriteFile(path, mode.value)
      self.Sleep(self.args.enable_sensor_sleep_secs)
    except Exception:
      logging.exception('Failed to turn sensor %s', mode)

  def _GetSensorState(self, device_path):
    path = self._dut.path.join(device_path, self.args.calibrate_path)
    return sensor_utils.SensorState(self._dut.ReadFile(path).strip())

  def _GetSensorValue(self, sensor_value_path, log=True):
    """Get and log sensor value.

    Args:
      sensor_value_path: The path to the sensor value file.
      log: Whether to log the sensor value.

    Returns:
      The sensor value.
    """
    output = self._dut.ReadFile(sensor_value_path).strip()
    if log:
      self.ui.SetHTML(output, id='proximity-sensor-value')
      logging.info('sensor value: %s', output)
    return int(output)

  def _SubTestCleanup(self, device_path):
    self.stop_countdown_event.set()
    self._SensorSwitcher(sensor_utils.SensorState.OFF, device_path)
    if self._event_fd is not None:
      try:
        os.close(self._event_fd)
      except Exception as e:
        logging.warning('Failed to close the event fd: %r', e)

  def _GetEventFd(self, device_path):
    path = self._dut.path.join('/dev', self._dut.path.basename(device_path))
    fd = os.open(path, 0)
    self.assertTrue(fd >= 0, f"Can't open the device, error = {int(fd)}")

    # Python fcntl only allows a 32-bit input to fcntl - using 0x40 here
    # allows us to try and obtain a pointer in the low 2GB of the address space.
    mm = mmap.mmap(-1, 4096, flags=mmap.MAP_ANONYMOUS | mmap.MAP_SHARED | 0x40)
    event_fdp = ctypes.c_int.from_buffer(mm)

    ret = fcntl.ioctl(fd, IIO_GET_EVENT_FD_IOCTL, event_fdp)
    os.close(fd)
    self.assertTrue(ret >= 0, f"Can't get the IIO event fd, error = {int(ret)}")

    event_fd = event_fdp.value
    self.assertTrue(event_fd >= 0, f"Invalid IIO event fd = {int(event_fd)}")

    return event_fd

  def _ReadEventBuffer(self, sensor_value_path):
    """Poll the event fd until one event occurs.

    Args:
      sensor_value_path: The path to the sensor value file.

    Returns:
      The event buffer.
    """
    while True:
      try:
        fds = select.select([self._event_fd], [], [],
                            self._POLLING_TIME_INTERVAL)[0]
      except select.error as e:
        self.FailTask(f'Unable to read from the event fd: {e!r}.')

      if not fds:
        if sensor_value_path:
          self._GetSensorValue(sensor_value_path)
        # make sure the user can manually stop the test
        self.Sleep(self._POLLING_TIME_INTERVAL)
        continue

      buf = os.read(self._event_fd, PROXIMITY_EVENT_BUF_SIZE)

      if len(buf) != PROXIMITY_EVENT_BUF_SIZE:
        self.FailTask(f'The event buffer has the wrong size: {len(buf)!r}.')
      return buf

  def CalibrateSensor(self, sensor_value_path):
    while True:
      values = [
          self._GetSensorValue(sensor_value_path, False)
          for unused_index in range(32)
      ]
      if max(values) < self.args.sensor_initial_max:
        break
      logging.info('sensor initial values with min %s and max %s', min(values),
                   max(values))
      self.Sleep(self._POLLING_TIME_INTERVAL)
