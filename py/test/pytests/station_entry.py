#!/usr/bin/env python
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Starts or ends a station-based test.

This factory test invokes functions to setup or teardown a station-based
test list.
"""

import threading
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import countdown_timer
from cros.factory.test import factory
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sync_utils


_CSS = """
.prompt {
  font-size: 2em;
}

.warning {
  color: red;
}
"""

_TITLE_START = i18n_test_ui.MakeI18nLabel('Start Station Test')
_TITLE_END = i18n_test_ui.MakeI18nLabel('End Station Test')

_ID_MSG_DIV = 'msg'
_ID_COUNTDOWN_DIV = 'countdown'

_STATE_HTML = """
<div id='%s'></div>
<div id='%s'></div>
""" % (_ID_MSG_DIV, _ID_COUNTDOWN_DIV)

_MSG_INSERT = i18n_test_ui.MakeI18nLabelWithClass(
    'Please attach DUT.', 'prompt')

_MSG_PRESS_SPACE = i18n_test_ui.MakeI18nLabelWithClass(
    'Press SPACE to start the test.', 'prompt')

_MSG_PRESS_SPACE_TO_END = i18n_test_ui.MakeI18nLabelWithClass(
    'Press SPACE to end the test.', 'prompt')

_MSG_SEND_RESULT = i18n_test_ui.MakeI18nLabelWithClass(
    'Sending test results to shopfloor...', 'prompt')

_MSG_REMOVE_DUT = i18n_test_ui.MakeI18nLabelWithClass(
    'Please remove DUT.', 'prompt')

_MSG_RESTART_TESTS = i18n_test_ui.MakeI18nLabelWithClass(
    'Restarting all tests...', 'prompt')


class StationEntry(unittest.TestCase):
  """The factory test to start station test process."""
  ARGS = [
      Arg('start_station_tests', bool,
          'To start or stop the factory station tests.',
          default=True, optional=True),
      Arg('prompt_start', bool,
          'Prompt for spacebar before starting test.',
          default=False, optional=True),
      Arg('timeout_secs', int,
          'Timeout for waiting the device. Set to None for waiting forever.',
          default=None, optional=True),
      Arg('disconnect_dut', bool,
          'Ask operator to disconnect DUT or not',
          default=True, optional=True),
      # TODO(hungte) When device_data and dut_storage has been synced, we should
      # change this to "clear_dut_storage" since testlog will still try to
      # reload device data from storage before invocation of next test.
      Arg('load_dut_storage', bool,
          'To load DUT storage into station session (DeviceData).',
          default=True, optional=True),
      Arg('invalidate_dut_info', bool,
          'To invoke dut.info.Invalidate() or not',
          default=True, optional=True),
      Arg('clear_serial_numbers', bool,
          'To invoke state.ClearAllSerialNumbers() or not',
          default=True, optional=True),
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._state = state.get_instance()
    self._ui = test_ui.UI()
    self._ui.AppendCSS(_CSS)
    self._template = ui_templates.OneSection(self._ui)
    self._template.SetTitle(_TITLE_START if self.args.start_station_tests else
                            _TITLE_END)
    self._space_event = threading.Event()

  def RestartAllTests(self):
    self._state.ScheduleRestart()

  def SendTestResult(self):
    self._dut.hooks.SendTestResult(self._state.get_test_states())

  def runTest(self):
    self._ui.RunInBackground(self._runTest)
    self._ui.Run()

  def _runTest(self):
    self._template.SetState(_STATE_HTML)
    self._ui.BindKey(test_ui.SPACE_KEY, lambda _: self._space_event.set())
    if self.args.start_station_tests:
      # Clear dut.info data.
      if self.args.invalidate_dut_info:
        factory.console.info('Clearing dut.info data...')
        self._dut.info.Invalidate()
      if self.args.clear_serial_numbers:
        factory.console.info('Clearing serial numbers')
        state.ClearAllSerialNumbers()
      self.Start()
      if self.args.load_dut_storage:
        # TODO(stimim): 1. cache dut.info, 2. load session on dut.
        self._dut.info.GetSerialNumber('serial_number')
        self._dut.info.GetSerialNumber('mlb_serial_number')
    else:
      self.End()
      # Clear dut.info data.
      if self.args.invalidate_dut_info:
        factory.console.info('Clearing dut.info data...')
        self._dut.info.Invalidate()
      if self.args.clear_serial_numbers:
        factory.console.info('Clearing serial numbers')
        state.ClearAllSerialNumbers()

  def Start(self):
    self._ui.SetHTML(_MSG_INSERT, id=_ID_MSG_DIV)
    disable_event = threading.Event()

    if self.args.timeout_secs:
      countdown_timer.StartCountdownTimer(
          self.args.timeout_secs,
          lambda: (self._ui.Fail('DUT is not connected in %d seconds' %
                                 self.args.timeout_secs)),
          self._ui,
          _ID_COUNTDOWN_DIV,
          disable_event=disable_event)

    def _IsReady():
      if not self._dut.link.IsReady():
        return False
      try:
        self._dut.CheckCall(['true'])
        return True
      except Exception:
        return False

    sync_utils.WaitFor(_IsReady, self.args.timeout_secs, poll_interval=1)
    disable_event.set()

    if self.args.prompt_start:
      self._ui.SetHTML(_MSG_PRESS_SPACE, id=_ID_MSG_DIV)
      sync_utils.WaitFor(self._space_event.isSet, None)
      self._space_event.clear()

  def End(self):
    self._ui.SetHTML(_MSG_SEND_RESULT, id=_ID_MSG_DIV)
    self.SendTestResult()

    self._ui.SetHTML(_MSG_REMOVE_DUT, id=_ID_MSG_DIV)
    if not self._dut.link.IsLocal():
      if self.args.disconnect_dut:
        sync_utils.WaitFor(lambda: not self._dut.link.IsReady(),
                           self.args.timeout_secs,
                           poll_interval=1)
      else:
        self._ui.SetHTML(_MSG_PRESS_SPACE_TO_END, id=_ID_MSG_DIV)
        sync_utils.WaitFor(self._space_event.isSet, None)
        self._space_event.clear()

    self._ui.SetHTML(_MSG_RESTART_TESTS, id=_ID_MSG_DIV)
    # TODO(hungte): Clear all device data.
    self.RestartAllTests()
