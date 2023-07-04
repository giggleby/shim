#!/usr/bin/env python3
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for TestCase module."""

import queue
import unittest
from unittest import mock

from cros.factory.test import device_data
from cros.factory.test import event as test_event
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.test.utils import pytest_utils
from cros.factory.unittest_utils import mock_time_utils
from cros.factory.utils import type_utils


_EventType = test_event.Event.Type


class TestCaseTest(unittest.TestCase):

  class _MockEventLoop:
    def __init__(self):
      self._event_loop_end = queue.Queue()
      # We don't use mock for PostNewEvent and Run, since there is race
      # condition within the mock library __call__...
      self.mock = mock.Mock()

    def PostNewEvent(self, event_type, **kwargs):
      if event_type == _EventType.END_EVENT_LOOP:
        self._event_loop_end.put(kwargs)
      # Call `MockPostNewEvent` for checking function calling
      # since we don't mock `PostNewEvent`.
      self.mock.MockPostNewEvent(event_type=event_type, **kwargs)

    def Run(self):
      end_event_kwargs = self._event_loop_end.get()
      return type_utils.Obj(**end_event_kwargs)

    def __getattr__(self, name):
      return getattr(self.mock, name)

  def setUp(self):
    self._patchers = []
    self._mock_device_data_dict = {}

    self._timeline = mock_time_utils.TimeLine()
    self._patchers.extend(mock_time_utils.MockAll(self._timeline))

    # Mocks goofy_rpc
    mock_goofy_rpc_attributes = {
        'GetAttributeOfCurrentFactoryTest.return_value': 'mock_attribute',
    }
    self._mock_goofy_rpc = mock.Mock(**mock_goofy_rpc_attributes)
    self._CreatePatcher(state,
                        'GetInstance').return_value = self._mock_goofy_rpc

    self._test = test_case.TestCase()
    self._test.ui_class = mock.Mock

    self._handler_exception_hook = None

    self._mock_event_loop = self._MockEventLoop()
    self._CreatePatcher(
        test_ui, 'EventLoop').side_effect = self._StubEventLoopConstructor

    self._CreatePatcher(device_data,
                        'GetDeviceData').side_effect = self._MockGetDeviceData
    self._CreatePatcher(
        device_data,
        'UpdateDeviceData').side_effect = self._MockUpdateDeviceData
    self._CreatePatcher(
        device_data,
        'DeleteDeviceData').side_effect = self._MockDeleteDeviceData

  def _StubEventLoopConstructor(self, handler_exception_hook):
    self._handler_exception_hook = handler_exception_hook
    return self._mock_event_loop

  def _MockGetDeviceData(self, key, default=0):
    return self._mock_device_data_dict.get(key, default)

  def _MockUpdateDeviceData(self, update_dict):
    for key, value in update_dict.items():
      self._mock_device_data_dict[key] = value

  def _MockDeleteDeviceData(self, delete_key, optional=False):
    if optional:
      self._mock_device_data_dict.pop(delete_key, None)
    else:
      del self._mock_device_data_dict[delete_key]

  def _CreatePatcher(self, *args, **kwargs):
    patcher = mock.patch.object(*args, **kwargs)
    self._patchers.append(patcher)
    return patcher.start()

  def tearDown(self):
    for patcher in self._patchers:
      patcher.stop()

  def GetRunResult(self):
    result = unittest.TestResult()
    self._test.run(result=result)
    errors = result.errors + result.failures
    return errors

  def AssertRunPass(self):
    errors = self.GetRunResult()
    self.assertFalse(errors)

  def AssertRunFailOrWaive(self, msg=None):
    errors = self.GetRunResult()
    self.assertEqual(1, len(errors))
    if msg:
      self.assertIn(msg, errors[0][1])

  def AssertNotReached(self):
    raise AssertionError('This should not be reached.')

  def testGetNextTaskStageKey(self):
    # pylint: disable=protected-access
    self.assertEqual(self._test._next_task_stage_key,
                     'factory.test_case.next_task_stage.mock_attribute')
    self._mock_goofy_rpc.GetAttributeOfCurrentFactoryTest.assert_called_with(
        current_invocation_uuid=None, attribute_name='id')

  def testAutomaticPass(self):
    def _RunTest():
      pass

    self._test.runTest = _RunTest

    self.AssertRunPass()
    self._mock_event_loop.AddEventHandler.assert_any_call(
        'goofy_ui_task_end', mock.ANY)

  def testPassTask(self):
    call_count = [0]

    def _Task():
      call_count[0] += 1
      self._test.PassTask()
      self.AssertNotReached()

    self._test.AddTask(_Task)
    self._test.AddTask(_Task)

    self.AssertRunPass()
    self.assertEqual([2], call_count)
    self._mock_event_loop.mock.MockPostNewEvent.assert_called_with(
        event_type=_EventType.END_EVENT_LOOP, status=state.TestState.PASSED)

  def testFailTask(self):

    def _Task():
      self._test.FailTask('Test fail.')
      self.AssertNotReached()

    self._test.AddTask(_Task)

    self.AssertRunFailOrWaive()
    self.assertRaises(pytest_utils.IndirectException)
    self._mock_event_loop.mock.MockPostNewEvent.assert_called_with(
        event_type=_EventType.END_EVENT_LOOP, status=state.TestState.FAILED,
        exception_index=0)

  def testWaiveTest(self):

    def _Task():
      self._test.WaiveTest('Test waived.')
      self.AssertNotReached()

    self._test.AddTask(_Task)

    self.AssertRunFailOrWaive()
    self.assertRaises(pytest_utils.IndirectException)
    self._mock_event_loop.mock.MockPostNewEvent.assert_called_with(
        event_type=_EventType.END_EVENT_LOOP,
        status=state.TestState.FAILED_AND_WAIVED, exception_index=0)
    self._mock_goofy_rpc.WaiveCurrentFactoryTest.assert_called_once()

  def testFailWithAssert(self):
    def _RunTest():
      self.assertTrue(False)  # pylint: disable=redundant-unittest-assert

    self._test.runTest = _RunTest

    self.AssertRunFailOrWaive('False is not true')

  def testAddTask_AllPass(self):
    executed_tasks = []

    def _Task(idx):
      self.assertEqual(idx, self._mock_event_loop.ClearHandlers.call_count)
      self.assertEqual(idx, self._test.ui.UnbindAllKeys.call_count)
      executed_tasks.append(idx)

    self._test.AddTask(lambda: _Task(0))
    self._test.AddTask(lambda: _Task(1))
    self._test.AddTask(lambda: _Task(2))

    self.AssertRunPass()
    self.assertEqual([0, 1, 2], executed_tasks)

  def testAddTask_SomeFail(self):
    executed_tasks = []

    def _Task(name, fail=False):
      executed_tasks.append(name)
      if fail:
        self._test.FailTask('Task fail.')

    self._test.AddTask(lambda: _Task('task1'))
    self._test.AddTask(lambda: _Task('task2', fail=True))
    self._test.AddTask(lambda: _Task('task3'))

    self.AssertRunFailOrWaive()
    self.assertEqual(['task1', 'task2'], executed_tasks)

  def testAddTask_CheckNextTaskStage_WithoutReboot(self):
    next_task_stages = []

    def _Task():
      next_task_stages.append(self._test.GetNextTaskStage())

    # next_task_stage will not be updated if all tasks were added with
    # `reboot=False`
    self._test.AddTask(_Task)
    self._test.AddTask(_Task)
    self._test.AddTask(_Task)

    self.AssertRunPass()
    self.assertEqual([0, 0, 0], next_task_stages)

  def testAddTask_CheckNextTaskStage_WithReboot(self):
    next_task_stages = []

    def _Task():
      next_task_stages.append(self._test.GetNextTaskStage())

    # next_task_stage will be updated if any task was added with
    # `reboot=True`
    self._test.AddTask(_Task)
    self._test.AddTask(_Task)
    self._test.AddTask(_Task, reboot=True)

    self.AssertRunFailOrWaive()
    self.assertEqual([1, 2, 3], next_task_stages)

  def testAddTasks_SkipFinishedTasksAfterReboot(self):
    executed_tasks = []
    next_task_stages = []

    def _Task(name):
      executed_tasks.append((name))
      next_task_stages.append(self._test.GetNextTaskStage())

    self._test.AddTask(lambda: _Task('task1'))
    self._test.AddTask(lambda: _Task('task2'), reboot=True)
    self._test.AddTask(lambda: _Task('task3'))

    # Sets the next stage flag for simulating the reboot scenario.
    # The tasks finished before reboot should be skipped.
    self._test.UpdateNextTaskStage(2)
    self.AssertRunPass()
    self.assertEqual(['task3'], executed_tasks)
    self.assertEqual([3], next_task_stages)

  def testAddTasks_ClearNextTaskStage_TestPass(self):

    def _Task():
      pass

    # Makes sure the next stage flag will be cleared if all tasks pass.
    self._test.AddTask(_Task, reboot=True)
    self._test.AddTask(_Task)
    self._test.AddTask(_Task)

    self._test.UpdateNextTaskStage(1)
    self.AssertRunPass()
    self.assertEqual(self._test.GetNextTaskStage(), 0)

  def testAddTasks_ClearNextTaskStage_TestFail(self):

    def _Task(fail_task=False):
      if fail_task:
        self._test.FailTask('Task fail.')

    # Makes sure the next stage flag will be cleared if any task fail.
    self._test.AddTask(_Task, reboot=True)
    self._test.AddTask(_Task, fail_task=True)
    self._test.AddTask(_Task)

    self._test.UpdateNextTaskStage(1)
    self.AssertRunFailOrWaive()
    self.assertEqual(self._test.GetNextTaskStage(), 0)

  def testAddTasks_UnexpectedReboot(self):

    def _Task():
      pass

    # Sets the next stage flag for simulating the reboot scenario.
    # Exception should be triggered if the device reboot
    # while running the task with 'reboot=False'
    self._test.UpdateNextTaskStage(2)

    self._test.AddTask(_Task, reboot=True)
    self._test.AddTask(_Task, reboot=False)
    self._test.AddTask(_Task)

    self.AssertRunFailOrWaive(
        'Unexpected reboot was triggered while running "_Task".')

  @mock.patch('time.sleep')
  def testAddTasks_RebootNotTriggeredWithinBufferTime(self, time_sleep):

    # Task without reboot process
    def _Task():
      pass

    self._test.AddTask(_Task, reboot=True)
    self._test.AddTask(_Task)

    self.AssertRunFailOrWaive('Reboot not triggered '
                              'within buffer time (5 seconds), '
                              'next task may be executed in advance.')
    time_sleep.assert_called_once()

  @mock.patch('time.sleep')
  def testAddTasks_SetRebootBufferTime(self, time_sleep):

    def _Task():
      pass

    self._test.AddTask(_Task, reboot=True, reboot_timeout_secs=3)
    self._test.AddTask(_Task)

    self.AssertRunFailOrWaive('Reboot not triggered '
                              'within buffer time (3 seconds), '
                              'next task may be executed in advance.')
    time_sleep.assert_called_once_with(3)

  def testWaitTaskEnd(self):
    def _RunTest():
      self._test.WaitTaskEnd()
      self.AssertNotReached()

    def _TestEnd():
      try:
        self._test.PassTask()
      except Exception:
        self._handler_exception_hook()

    self._test.runTest = _RunTest
    self._timeline.AddEvent(10, _TestEnd)

    self.AssertRunPass()
    self._timeline.AssertTimeAt(10)

  def testWaitTaskEndFail(self):
    def _RunTest():
      self._test.WaitTaskEnd()
      self.AssertNotReached()

    def _TestEnd():
      try:
        self._test.FailTask('FAILED!')
      except Exception:
        self._handler_exception_hook()

    self._test.runTest = _RunTest
    self._timeline.AddEvent(10, _TestEnd)

    self.AssertRunFailOrWaive()
    self._timeline.AssertTimeAt(10)

  def testSleep(self):
    times = []
    def _RunTest():
      while True:
        times.append(self._timeline.GetTime())
        self._test.Sleep(2)

    def _TestEnd():
      try:
        self._test.FailTask('FAILED!')
      except Exception:
        self._handler_exception_hook()

    self._test.runTest = _RunTest
    self._timeline.AddEvent(5, _TestEnd)

    self.AssertRunFailOrWaive()
    self.assertEqual(5, self._timeline.GetTime())
    self.assertEqual([0, 2, 4], times)

  def testSaveDataRightBeforeReboot(self):
    next_stage = []

    def _side_effect():
      next_stage.append(self._test.GetNextTaskStage())

    def _Task():
      pass

    self._test.AddTask(_Task)
    self._test.AddTask(_Task, reboot=True)
    self._mock_goofy_rpc.SaveDataForNextBoot.side_effect = _side_effect

    self.GetRunResult()

    self.assertEqual([2], next_stage)

  @mock.patch('subprocess.check_call')
  def testFlushLogRightBeforeReboot(self, mock_check_call):
    next_stage = []

    def _side_effect(_):
      next_stage.append(self._test.GetNextTaskStage())

    def _Task():
      pass

    self._test.AddTask(_Task, reboot=True)
    self._test.AddTask(_Task)
    mock_check_call.side_effect = _side_effect

    self.GetRunResult()

    self.assertEqual([1], next_stage)
    mock_check_call.assert_called_once_with('sync')

if __name__ == '__main__':
  unittest.main()
