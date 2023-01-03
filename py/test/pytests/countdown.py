# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A count down monitor for better user interface in run-in tests.

Description
-----------
Count down and display system load. This is helpful for run-in phase to run
multiple stress tests (for example, CPU, memory, disk, GPU, ... etc) in
background so operator can see how long the run-in has been executed, and a
quick overview of system status.  It also alarms if there's any abnormal status
(for example overheat) detected during run-in.

Test Procedure
--------------
This test is designed to run in parallel with other background tests.
No user interaction is needed but if there were abnormal events operator should
collect debug logs for fault analysis.

Dependency
----------
- Thermal in Device API (`cros.factory.device.thermal`) for system thermal
  sensor readings.

Examples
--------
To run a set of tests for 120 seconds in parallel with countdown showing
progress, add this in test list::

  {
    "pytest_name": "countdown",
    "args": {
      "duration_secs": 120
    }
  }

To run 8 hours and alert if main sensor (CPU) reaches 60 Celcius and fail when
exceeding 65 Celcius::

  {
    "pytest_name": "countdown",
    "args": {
      "duration_secs": 28800,
      "temp_criteria": [
        ["CPU", null, 60, 65]
      ]
    }
  }
"""

import collections
import enum
import logging
import os
import threading
import time
from typing import Dict, List

from cros.factory.device import device_types
from cros.factory.device import device_utils
from cros.factory.device import wifi
from cros.factory.goofy.plugins import plugin_controller
from cros.factory.test import event_log  # TODO(chuntsen): Deprecate event log.
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.test.utils import bluetooth_utils
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import time_utils
from cros.factory.utils import type_utils


_WARNING_TEMP_RATIO = 0.95
_CRITICAL_TEMP_RATIO = 0.98
_ALS_LOCATION = 'camera'


Status = collections.namedtuple('Status',
                                ['temperatures', 'fan_rpm', 'cpu_freq'])


class PanelID(str, enum.Enum):

  def __str__(self) -> str:
    return self.value

  LOG = 'cd-log-panel'
  LEGEND = 'cd-legend-panel'
  LEGEND_ITEM = 'cd-legend-item-panel'
  WIFI = 'cd-wifi-panel'
  BLUETOOTH = 'cd-bluetooth-panel'
  ALS = 'cd-als-panel'


class CountDownTest(test_case.TestCase):
  """A countdown test that monitors and logs various system status."""

  ui_class = test_ui.UI
  ARGS = [
      Arg('duration_secs', int, 'Duration of time to countdown.'),
      Arg('log_interval', int,
          'Interval of time in seconds to log system status.', default=120),
      Arg('ui_update_interval', int,
          'Interval of time in seconds to update system status on UI.',
          default=10),
      Arg('wifi_update_interval', int,
          'Interval of time in seconds to scan wifi.', default=0),
      Arg('bluetooth_update_interval', int,
          'Interval of time in seconds to scan bluetooth.', default=0),
      Arg('als_update_interval', int,
          'Interval of time in seconds to scan ALS.', default=0),
      Arg('grace_secs', int,
          'Grace period before starting abnormal status detection.',
          default=120),
      Arg(
          'temp_max_delta', int,
          'Allowed difference between current and last temperature of a '
          'sensor.', default=None),
      Arg(
          'temp_criteria', list,
          'A list of rules to check that temperature is under the given range, '
          'rule format: (name, temp_sensor, warning_temp, critical_temp)',
          default=[]),
      Arg(
          'relative_temp_criteria', list,
          'A list of rules to check the difference between two temp sensors, '
          'rule format: (relation, first_sensor, second_sensor, max_diff). '
          'relation is a text output with warning messages to describe the two '
          'temp sensors in the rule', default=[]),
      Arg('fan_min_expected_rpm', int, 'Minimum fan rpm expected',
          default=None),
      Arg(
          'allow_invalid_temp', bool,
          'Allow invalid temperature e.g. values less then or equal to zero, '
          'which may mean thermal nodes are not ready in early builds.',
          default=False),
      Arg('cpu_min_expected_freq', int,
          'Minimum CPU frequency expected. (unit: MHz)', default=None),
      Arg('cpu_max_expected_freq', int,
          'Maximum CPU frequency expected. (unit: MHz)', default=None)
  ]

  def FormatSeconds(self, secs):
    hours = int(secs / 3600)
    minutes = int((secs / 60) % 60)
    seconds = int(secs % 60)
    return f'{int(hours):02}:{int(minutes):02}:{int(seconds):02}'

  def UpdateTimeAndLoad(self):
    self._elapsed_secs = time.time() - self._start_secs
    self.ui.SetHTML(
        self.FormatSeconds(self._elapsed_secs),
        id='cd-elapsed-time')
    self.ui.SetHTML(
        self.FormatSeconds(self.args.duration_secs - self._elapsed_secs),
        id='cd-remaining-time')
    self.ui.SetHTML(' '.join(file_utils.ReadFile('/proc/loadavg').split()[0:3]),
                    id='cd-system-load')

  def UpdateUILog(self):
    sys_status = self.SnapshotStatus()
    # Simplify thermal output by the order of self._sensors
    log_items = [
        time_utils.TimeString(),
        (f'Temperatures: '
         f'{[sys_status.temperatures[sensor] for sensor in self._sensors]}'),
        f'Fan RPM: {sys_status.fan_rpm}',
        f'CPU frequency (MHz): {sys_status.cpu_freq}'
    ]
    log_str = '.  '.join(log_items)
    if self._verbose_log:
      self._verbose_log.write(log_str + os.linesep)
      self._verbose_log.flush()
    self.ui.AppendHTML(f'<div>{test_ui.Escape(log_str)}</div>', id=PanelID.LOG,
                       autoscroll=True)
    self.ui.RunJS(f'const panel = document.getElementById("{PanelID.LOG}");'
                  'if (panel.childNodes.length > 512)'
                  '  panel.removeChild(panel.firstChild);')

  def UpdateLegend(self, sensor_names):
    for i, sensor in enumerate(sensor_names):
      self.ui.AppendHTML(
          f'<div class="cd-legend-item">[{int(i)}] {sensor}</div>',
          id=PanelID.LEGEND_ITEM)
    if sensor_names:
      self.ui.ToggleClass(PanelID.LEGEND, 'hidden', False)

  def DetectAbnormalStatus(self, status, last_status):
    def GetTemperature(sensor):
      try:
        if sensor is None:
          sensor = self._main_sensor
        return status.temperatures[sensor]
      except IndexError:
        return None

    warnings = []

    if self.args.temp_max_delta:
      if len(status.temperatures) != len(last_status.temperatures):
        warnings.append(f'Number of temperature sensors differ (current: '
                        f'{len(status.temperatures)}, last: '
                        f'{len(last_status.temperatures)}) ')

      for sensor in status.temperatures:
        current = status.temperatures[sensor]
        last = last_status.temperatures[sensor]
        # Ignore the case when both are None since it could just mean the
        # sensor doesn't exist. If only one of them is None, then there
        # is a problem.
        if last is None and current is None:
          continue
        if last is None or current is None:
          warnings.append(
              f'Cannot read temperature sensor {sensor} (current: {current!r}, '
              f'last: {last!r})')
        elif abs(current - last) > self.args.temp_max_delta:
          warnings.append(
              f'Temperature sensor {sensor} delta over '
              f'{int(self.args.temp_max_delta)} (current: {int(current)}, last:'
              f' {int(last)})')

    for name, sensor, warning_temp, critical_temp in self.args.temp_criteria:
      temp = GetTemperature(sensor)
      if temp is None:
        warnings.append(f'{name} temperature unavailable')
        continue

      if warning_temp is None or critical_temp is None:
        try:
          sys_temp = self._dut.thermal.GetCriticalTemperature(sensor)
        except NotImplementedError:
          raise type_utils.TestFailure(
              f'Failed to get the critical temperature of {name!r}, please '
              f'explicitly specify the value in the test arguments.') from None
        if warning_temp is None:
          warning_temp = sys_temp * _WARNING_TEMP_RATIO
        if critical_temp is None:
          critical_temp = sys_temp * _CRITICAL_TEMP_RATIO

      if temp >= critical_temp:
        warnings.append(
            f'{name} over critical temperature (now: {temp:.1f}, critical: '
            f'{critical_temp:.1f})')
      elif temp >= warning_temp:
        warnings.append(
            f'{name} over warning temperature (now: {temp:.1f}, warning: '
            f'{warning_temp:.1f})')

    for (relation, first_sensor, second_sensor,
         max_diff) in self.args.relative_temp_criteria:
      first_temp = GetTemperature(first_sensor)
      second_temp = GetTemperature(second_sensor)
      if first_temp is None or second_temp is None:
        unavailable_sensor = []
        if first_temp is None:
          unavailable_sensor.append(first_sensor)
        if second_temp is None:
          unavailable_sensor.append(second_sensor)
        warnings.append(
            f"Cannot measure temperature difference between {relation}: "
            f"temperature {', '.join(unavailable_sensor)} unavailable")
      elif abs(first_temp - second_temp) > max_diff:
        warnings.append(
            f'Temperature difference between {relation} over {int(max_diff)} '
            f'(first: {int(first_temp)}, second: {int(second_temp)})')

    if self.args.fan_min_expected_rpm:
      for i, fan_rpm in enumerate(status.fan_rpm):
        if fan_rpm < self.args.fan_min_expected_rpm:
          warnings.append(
              f'Fan {int(i)} rpm {int(fan_rpm)} less than min expected '
              f'{int(self.args.fan_min_expected_rpm)}')

    if self.args.cpu_min_expected_freq:
      for cpu_freq in status.cpu_freq:
        if cpu_freq < self.args.cpu_min_expected_freq:
          warnings.append(f'CPU frequency {cpu_freq:f} MHz less than expected '
                          f'{int(self.args.cpu_min_expected_freq)} MHz')

    if self.args.cpu_max_expected_freq:
      for cpu_freq in status.cpu_freq:
        if cpu_freq > self.args.cpu_max_expected_freq:
          warnings.append(
              f'CPU frequency {cpu_freq:f} MHz larger than expected '
              f'{int(self.args.cpu_max_expected_freq)} MHz')

    if not self.args.allow_invalid_temp:
      for sensor, temp in status.temperatures.items():
        if temp is None:
          warnings.append(f'Cannot read temperature sensor {sensor}.')
        elif temp <= 0:
          warnings.append(
              f'Thermal zone {sensor} reports abnormal temperature {int(temp)}')

    in_grace_period = self._elapsed_secs < self.args.grace_secs
    if warnings:
      event_log.Log('warnings', elapsed_secs=self._elapsed_secs,
                    in_grace_period=in_grace_period, warnings=warnings)
      if not in_grace_period:
        for w in warnings:
          session.console.warn(w)

    with self._group_checker:
      testlog.CheckNumericParam('elapsed', self._elapsed_secs,
                                max=self.args.grace_secs)
      testlog.LogParam('temperatures', status.temperatures)
      testlog.LogParam('fan_rpm', status.fan_rpm)
      testlog.LogParam('cpu_freq', status.cpu_freq)
      testlog.LogParam('warnings', warnings)

  def SnapshotStatus(self):
    return Status(self._dut.thermal.GetAllTemperatures(),
                  self._dut.fan.GetFanRPM(),
                  self._cpu_freq_manager.GetCurrentFrequency())

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()

    self._main_sensor = self._dut.thermal.GetMainSensorName()
    # Normalize the sensors so main sensor is always the first one.
    sensors = sorted(self._dut.thermal.GetAllSensorNames())
    sensors.insert(0, sensors.pop(sensors.index(self._main_sensor)))
    self._sensors = sensors
    self._cpu_freq_manager = plugin_controller.GetPluginRPCProxy(
        'cpu_freq_manager')

    self._als_controller = None
    try:
      self._als_controller = self._dut.ambient_light_sensor.GetController(
          location=_ALS_LOCATION)
    except device_types.DeviceException:
      # Disable the ALS scanning if the device does not support ALS.
      self.ui.HideElement(PanelID.ALS)
      self.args.als_update_interval = 0

    # Group checker for Testlog.
    self._group_checker = testlog.GroupParam(
        'system_status',
        ['elapsed', 'temperatures', 'fan_rpm', 'cpu_freq', 'warnings'])
    testlog.UpdateParam('elapsed', description='In grace period or not')

    self._start_secs = time.time()
    self._elapsed_secs = 0
    self._verbose_log = None
    self._event_loop_stop = False
    self.last_status = Status(None, None, None)
    self.goofy = state.GetInstance()
    self.btmgmt = bluetooth_utils.BtMgmt()
    self.btmgmt.PowerOn()
    self._last_thread: Dict[str, threading.Thread] = {}

  def Log(self):
    """Add event log and detects abnormal status."""
    sys_status = self.SnapshotStatus()
    event_log.Log('system_status', elapsed_secs=self._elapsed_secs,
                  **sys_status._asdict())
    self.DetectAbnormalStatus(sys_status, self.last_status)
    self.last_status = sys_status

  def StartNewScanThread(self, scan_func):
    if scan_func in self._last_thread:
      self._last_thread[scan_func].join()
      del self._last_thread[scan_func]

    if self._event_loop_stop:
      logging.info('Stop in StartNewScanThread(%s) because event loop stopped.',
                   scan_func.__name__)
      return
    self._last_thread[scan_func] = threading.Thread(target=scan_func)
    self._last_thread[scan_func].start()

  def StartNewScanWiFiThread(self):
    self.StartNewScanThread(self.ScanWiFi)

  def StartNewScanBluetoothThread(self):
    self.StartNewScanThread(self.ScanBluetooth)

  def StartNewScanALSThread(self):
    self.StartNewScanThread(self.ScanALS)

  def ScanWiFi(self):
    """Launch WiFi scan in another thread."""
    self.ui.SetHTML(f'<div>scan start time: {self._elapsed_secs}</div>',
                    id=PanelID.WIFI)
    wifi_aps: List[wifi.AccessPoint] = (
        self._dut.wifi.FilterAccessPoints(log=False))
    self.ui.AppendHTML(f'<div>scan end time: {self._elapsed_secs}</div>',
                       id=PanelID.WIFI)
    for ap in wifi_aps:
      self.ui.AppendHTML(
          f'<div>ssid: {ap.ssid!r}, strength: {ap.strength!r}</div>',
          id=PanelID.WIFI)

    if self._event_loop_stop:
      logging.info('Stop in ScanWiFi because event loop stopped.')
    else:
      self.event_loop.AddTimedHandler(self.StartNewScanWiFiThread,
                                      self.args.wifi_update_interval)

  def ScanBluetooth(self):
    """Launch bluetooth scan in another thread."""
    self.ui.SetHTML(f'<div>scan start time: {self._elapsed_secs}</div>',
                    id=PanelID.BLUETOOTH)
    # There may be hundreds of bluetooth device inside the factory and the
    # scanning may be too long to be finished so we have to set a timeout.
    devices: Dict[str, Dict] = self.btmgmt.FindDevices(
        timeout_secs=self.args.bluetooth_update_interval, log=False)
    self.ui.AppendHTML(f'<div>scan end time: {self._elapsed_secs}</div>',
                       id=PanelID.BLUETOOTH)
    for mac, data in devices.items():
      self.ui.AppendHTML(f'<div>mac: {mac!r}, {data!r}</div>',
                         id=PanelID.BLUETOOTH)

    if self._event_loop_stop:
      logging.info('Stop in ScanBluetooth because event loop stopped.')
    else:
      self.event_loop.AddTimedHandler(self.StartNewScanBluetoothThread,
                                      self.args.bluetooth_update_interval)

  def ScanALS(self):
    """Launch ALS scan in another thread."""
    self.ui.SetHTML(f'<div>scan start time: {self._elapsed_secs}</div>',
                    id=PanelID.ALS)
    lux = self._als_controller.GetLuxValue()
    self.ui.AppendHTML(f'<div>scan end time: {self._elapsed_secs}</div>',
                       id=PanelID.ALS)
    self.ui.AppendHTML(f'<div>lux: {lux!r}</div>', id=PanelID.ALS)

    if self._event_loop_stop:
      logging.info('Stop in ScanALS because event loop stopped.')
    else:
      self.event_loop.AddTimedHandler(self.StartNewScanALSThread,
                                      self.args.als_update_interval)

  def runTest(self):
    verbose_log_path = session.GetVerboseTestLogPath()
    file_utils.TryMakeDirs(os.path.dirname(verbose_log_path))
    logging.info('Raw verbose logs saved in %s', verbose_log_path)
    with open(verbose_log_path, 'a', encoding='utf8') as verbose_log:
      self._verbose_log = verbose_log

      self.last_status = self.SnapshotStatus()

      self.UpdateLegend(self._sensors)

      # Loop until count-down ends.
      self.event_loop.AddTimedHandler(self.UpdateTimeAndLoad, 0.5, repeat=True)
      self.event_loop.AddTimedHandler(self.Log, self.args.log_interval,
                                      repeat=True)
      self.event_loop.AddTimedHandler(self.UpdateUILog,
                                      self.args.ui_update_interval, repeat=True)

      # For the events of components scanning,
      # we use a dict to store the {event}:{interval} pair
      event_interval_dict = {
          self.StartNewScanWiFiThread: self.args.wifi_update_interval,
          self.StartNewScanBluetoothThread: self.args.bluetooth_update_interval,
          self.StartNewScanALSThread: self.args.als_update_interval
      }
      for event, interval in event_interval_dict.items():
        if interval:
          self.event_loop.AddTimedHandler(event, interval)

      self.Sleep(self.args.duration_secs)
      self._event_loop_stop = True
      self.event_loop.RemoveTimedHandler()
      self._verbose_log = None

    self.goofy.WaitForWebSocketUp()
