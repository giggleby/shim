# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for base test case for pytests."""

import collections
import sys
import threading
import time
import unittest

from cros.factory.test import device_data
from cros.factory.test import event as test_event
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test.utils import pytest_utils
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


class TaskEndException(Exception):
  """The exception to end a task."""


class TestWaivedException(Exception):
  """The exception to waive a test."""


_Task = collections.namedtuple('Task',
                               ['name', 'run', 'reboot', 'reboot_timeout_secs'])


class TestCase(unittest.TestCase):
  """A unittest.TestCase, with task system and optional UI.

  Test should override runTest to do testing in background.
  """

  ui_class = test_ui.StandardUI

  def __init__(self, methodName='runTest'):
    super().__init__(methodName='_RunTest')
    self.event_loop = None

    self.__method_name = methodName
    self.__task_end_event = threading.Event()
    self.__task_stopped = False
    self.__tasks = collections.deque()

    self.__exceptions = []
    self.__exceptions_lock = threading.Lock()

    self.goofy_rpc = state.GetInstance()

    self.invocation_uuid = session.GetCurrentTestInvocation()

  @type_utils.LazyProperty
  def _next_task_stage_key(self):
    # Gets the unique id of test object as the key name of next stage flag.
    test_id = self.goofy_rpc.GetAttributeOfCurrentFactoryTest(
        current_invocation_uuid=self.invocation_uuid, attribute_name='id')
    return '.'.join(('factory.test_case.next_task_stage', test_id))

  def PassTask(self):
    """Pass current task.

    Should only be called in the event callbacks or primary background test
    thread.
    """
    raise TaskEndException

  def FailTask(self, msg):
    """Fail current task.

    Should only be called in the event callbacks or primary background test
    thread.
    """
    raise type_utils.TestFailure(msg)

  def WaiveTest(self, msg):
    """The function for making test waived.

    Make current task stopped, then stop the test and make it waived.

    Should only be called in the event callbacks or primary background test
    thread.
    """
    raise TestWaivedException(msg)

  def __WaitTaskEnd(self, timeout):
    if self.__task_end_event.wait(timeout=timeout):
      raise TaskEndException

  def WaitTaskEnd(self):
    """Wait for either TaskPass or TaskFail is called.

    Task that need to wait for frontend events to judge pass / fail should call
    this at the end of the task.
    """
    self.__WaitTaskEnd(None)

  def Sleep(self, secs):
    """Sleep for secs seconds, but ends early if test failed.

    An exception would be raised if TaskPass or TaskFail is called before
    timeout. This makes the function acts like time.sleep that ends early when
    timeout is given.

    Args:
      secs: Seconds to sleep, would return or raise immediately if value <= 0.

    Raises:
      TaskEndException if the task end before secs seconds.
    """
    self.__WaitTaskEnd(secs)

  def AddTask(self, task, *task_args, reboot: bool = False,
              reboot_timeout_secs: int = 5, **task_kwargs):
    """Add a task to the test.

    Extra arguments would be passed to the task function.
    The 'reboot' argument is for the tasks that include reboot process,
    the test flow will continue after reboot instead of fail
    if the last executed task was added with 'reboot=True'.
    Remember to add '"allow_reboot": true' in test_list,
    which allows reboot while running the pytest.

    Args:
      task: A task function.
      reboot: True if the task include reboot process.
      reboot_timeout_secs: Buffer time of reboot. The test will fail
                           if reboot is not triggered within it.
      task_args, task_kwargs: Arguments for the task function.

    Example:

      def Task(arg):
        print(arg + 5)

      def RebootTask(arg):
        print(arg)
        os.system('reboot')

      AddTask(RebootTask, 1, reboot=True)
      AddTask(Task, 2)
      AddTask(RebootTask, 3, reboot=True)
    """
    name = task.__name__
    run = lambda: task(*task_args, **task_kwargs)

    self.__tasks.append(
        _Task(name=name, run=run, reboot=reboot,
              reboot_timeout_secs=reboot_timeout_secs))

  def GetNextTaskStage(self) -> None:
    return device_data.GetDeviceData(self._next_task_stage_key, default=0)

  def UpdateNextTaskStage(self, next_task_stage) -> None:
    device_data.UpdateDeviceData({self._next_task_stage_key: next_task_stage})

  def ClearNextTaskStage(self):
    device_data.DeleteDeviceData(self._next_task_stage_key, optional=False)

  def ClearTasks(self):
    self.__tasks.clear()

  @type_utils.LazyProperty
  def ui(self):
    """The UI of the test.

    This is initialized on first use, so task can be used even for tests that
    want to use default UI.
    """
    ui = self.ui_class(event_loop=self.event_loop)
    ui.SetupStaticFiles()
    return ui

  def run(self, result=None):
    # We override TestCase.run and do initialize of ui objects here, since the
    # session.GetCurrentTestFilePath() used by UI is not set when __init__ is
    # called (It's set by invocation after the TestCase instance is created),
    # and initialize using setUp() means that all pytests inheriting this need
    # to remember calling super().setUp(), which is a lot of
    # boilerplate code and easy to forget.
    self.event_loop = test_ui.EventLoop(self.__HandleException)

    super().run(result=result)

  def _RunTest(self):
    """The main test procedure that would be run by unittest."""
    thread = process_utils.StartDaemonThread(target=self.__RunTasks)
    try:
      end_event = self.event_loop.Run()
      if end_event.status != state.TestState.PASSED:
        exc_idx = getattr(end_event, 'exception_index', None)

        if end_event.status == state.TestState.FAILED:
          if exc_idx is None:
            raise type_utils.TestFailure(getattr(end_event, 'error_msg', None))
        elif end_event.status == state.TestState.FAILED_AND_WAIVED:
          waived_test = self.goofy_rpc.WaiveCurrentFactoryTest(
              self.invocation_uuid)
          session.console.warning(
              f'Waive current running factory test: {waived_test}')
          if exc_idx is None:
            raise TestWaivedException(getattr(end_event, 'waive_msg', None))

        # pylint: disable=invalid-sequence-index
        raise pytest_utils.IndirectException(*self.__exceptions[exc_idx])
    finally:
      # Ideally, the background would be the one calling FailTask / PassTask,
      # or would be waiting in WaitTaskEnd when an exception is thrown, so the
      # thread should exit cleanly shortly after the event loop ends.
      #
      # If after 1 second, the thread is alive, most likely that the thread is
      # in some blocking operation and someone else fails the test, then we
      # assume that we don't care about the thread not cleanly stopped.
      #
      # In this case, we try to raise an exception in the thread (To possibly
      # trigger some cleanup process in finally block or context manager),
      # wait for 3 more seconds for (possible) cleanup to run, and just ignore
      # the thread. (Even if the thread doesn't terminate in time.)
      thread.join(1)
      if thread.is_alive():
        try:
          sync_utils.TryRaiseExceptionInThread(thread.ident, TaskEndException)
        except ValueError:
          # The thread is no longer valid, ignore it
          pass
        else:
          thread.join(3)

  def __CheckAndSkipPassedTasks(self):
    """Checks the next_task_stage flag and skips the tasks that have passed."""
    next_task_stage = self.GetNextTaskStage()

    # Fails the pytest if last executed task triggered an unexpected reboot.
    if next_task_stage > 0:
      last_task_before_reboot = self.__tasks[next_task_stage - 1]
      if not last_task_before_reboot.reboot:
        self.FailTask('Unexpected reboot was triggered while running '
                      f'"{last_task_before_reboot.name}".')

    # Skips the tasks that have passed.
    for unused_passed_tasks in range(next_task_stage):
      self.__tasks.popleft()

  def __RunTask(self, task, tasks_with_reboot):
    """Runs the task that was added to self.__tasks."""
    self.__task_end_event.clear()
    try:
      self.__SetupGoofyJSEvents()

      if tasks_with_reboot:
        # Updates the next task stage for stage checking before running.
        self.UpdateNextTaskStage(self.GetNextTaskStage() + 1)

      task.run()
      # Adds buffer time for avoiding run next task before
      # triggering reboot.
      if task.reboot:
        time.sleep(task.reboot_timeout_secs)
        # Fails the pytest if reboot not triggered
        # within reboot_timeout_secs ,which avoid race condition.
        self.FailTask('Reboot not triggered within buffer time '
                      f'({task.reboot_timeout_secs} seconds), '
                      'next task may be executed in advance.')
    except Exception:
      self.__HandleException()
    finally:
      self.__task_end_event.set()
      self.event_loop.ClearHandlers()
      self.ui.UnbindAllKeys()

  def __RunTasks(self):
    """Run the tasks in background daemon thread."""
    # Set the sleep function for various polling methods in sync_utils to
    # self.WaitTaskEnd, so tests using methods like sync_utils.WaitFor would
    # still be ended early when the test ends.
    with sync_utils.WithPollingSleepFunction(self.Sleep):
      # Add runTest as the only task if there's none.
      if not self.__tasks:
        self.AddTask(getattr(self, self.__method_name))

      tasks_with_reboot = any(task.reboot for task in self.__tasks)

      try:
        if tasks_with_reboot:
          self.__CheckAndSkipPassedTasks()

          # Saves pending test list for restoring test list after reboot.
          self.goofy_rpc.SaveDataForNextBoot()

        for task in self.__tasks:
          self.__RunTask(task, tasks_with_reboot)
          if self.__task_stopped:
            return
      except Exception:
        self.__HandleException()
        if self.__task_stopped:
          return
      finally:
        if tasks_with_reboot:
          # Clears next_task_stage after all tasks passed or any task failed.
          session.console.info(
              'Test finished. Clear the data of next task stage.')
          self.ClearNextTaskStage()

      self.event_loop.PostNewEvent(
          test_event.Event.Type.END_EVENT_LOOP, status=state.TestState.PASSED)

  def __HandleException(self):
    """Handle exception in event handlers or tasks.

    This should be called in the except clause, and is also called by the event
    loop in the main thread.
    """
    unused_exc_type, exception, tb = sys.exc_info()
    assert exception is not None, 'Not handling an exception'

    if not isinstance(exception, TaskEndException):
      with self.__exceptions_lock:
        exc_idx = len(self.__exceptions)
        self.__exceptions.append((exception, tb))

      test_status = (
          state.TestState.FAILED_AND_WAIVED if isinstance(
              exception, TestWaivedException) else state.TestState.FAILED)

      self.event_loop.PostNewEvent(test_event.Event.Type.END_EVENT_LOOP,
                                   status=test_status, exception_index=exc_idx)
      self.__task_stopped = True

    self.__task_end_event.set()

  def __SetupGoofyJSEvents(self):
    """Setup handlers for events from frontend JavaScript."""

    def TestResultHandler(event):
      status = event.data.get('status')
      if status == state.TestState.PASSED:
        self.PassTask()
      elif status == state.TestState.FAILED:
        self.FailTask(event.data.get('error_msg', ''))
      elif status == state.TestState.FAILED_AND_WAIVED:
        self.WaiveTest(event.data.get('waive_msg', ''))
      else:
        raise ValueError(f'Unexpected status in event {event!r}')

    # pylint: disable=unused-argument
    def ScreenshotHandler(event):
      output_filename = (f"/var/factory/log/screenshots/screenshot_"
                         f"{time.strftime('%Y%m%d-%H%M%S')}.png")
      state.GetInstance().DeviceTakeScreenshot(output_filename)
      session.console.info('Take a screenshot of Goofy page and store as %s',
                           output_filename)

    file_utils.TryMakeDirs('/var/factory/log/screenshots')
    self.event_loop.AddEventHandler('goofy_ui_task_end', TestResultHandler)
    self.event_loop.AddEventHandler('goofy_ui_screenshot', ScreenshotHandler)
