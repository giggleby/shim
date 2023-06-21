#!/usr/bin/env python3
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import math
import queue
import signal
import threading
import time
import unittest
from unittest import mock

from cros.factory.unittest_utils import mock_time_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


class PollingTestBase(unittest.TestCase):

  def setUp(self):
    self._timeline = mock_time_utils.TimeLine()
    self._patchers = mock_time_utils.MockAll(self._timeline)
    self._polling_sleep_context = sync_utils.WithPollingSleepFunction(
        self._timeline.AdvanceTime)
    self._polling_sleep_context.__enter__()

  def tearDown(self):
    self._polling_sleep_context.__exit__(None, None, None)
    for patcher in self._patchers:
      patcher.stop()


class PollForConditionTest(PollingTestBase):

  def _Increment(self):
    self.counter = self.counter + 1
    return self.counter

  def _IncrementCheckTrigger(self, trigger=3):
    return self._Increment() > trigger

  def setUp(self):
    super().setUp()
    self.counter = 1

  def testPollForCondition(self):
    self.assertEqual(True, sync_utils.PollForCondition(
        poll_method=self._IncrementCheckTrigger,
        timeout_secs=5, poll_interval_secs=0.01))

  def testPollForConditionSeparateConditionMethod(self):
    self.assertEqual(5, sync_utils.PollForCondition(
        poll_method=self._Increment,
        condition_method=lambda x: x >= 5,
        timeout_secs=5, poll_interval_secs=0.01))

  def testPollForConditionTimeout(self):
    self.assertRaises(
        type_utils.TimeoutError, sync_utils.PollForCondition,
        poll_method=lambda: self._IncrementCheckTrigger(trigger=30),
        timeout_secs=2, poll_interval_secs=0.1)


class WaitForTest(PollingTestBase):

  def setUp(self):
    super().setUp()
    self.start_time = self._timeline.GetTime()

  def runTest(self):

    def _ReturnTrueAfter(delta_time: float):
      return self._timeline.GetTime() > self.start_time + delta_time

    self.assertRaises(type_utils.TimeoutError, sync_utils.WaitFor,
                      condition=lambda: _ReturnTrueAfter(1), timeout_secs=0.5)

    self.start_time = self._timeline.GetTime()
    self.assertTrue(
        sync_utils.WaitFor(lambda: _ReturnTrueAfter(0.5), timeout_secs=1))


class EventWaitTest(unittest.TestCase):

  def testEventWait(self):
    start_event = threading.Event()

    def Target():
      start_event.clear()
      time.sleep(1)
      start_event.set()

    t = threading.Thread(target=Target)
    t.start()

    self.assertEqual(False, sync_utils.EventWait(start_event, 0.5, 1))
    self.assertEqual(True, sync_utils.EventWait(start_event, 2, 0.5))


class QueueGetTest(PollingTestBase):

  def setUp(self):
    super().setUp()
    self._queue = queue.Queue()

  def testQueueGetEmpty(self):
    self.assertRaises(queue.Empty, sync_utils.QueueGet, self._queue, timeout=.5,
                      poll_interval_secs=0.2)

  def testQueueGetSomething(self):
    self._queue.put(123)
    self.assertEqual(123, sync_utils.QueueGet(self._queue, timeout=0))

  def testQueueGetNone(self):
    self._queue.put('foo')

    self.assertEqual(
        'foo',
        sync_utils.QueueGet(self._queue, timeout=.5, poll_interval_secs=0.2))

  def testQueueGetTimeout(self):
    self.assertRaises(queue.Empty, sync_utils.QueueGet, self._queue, timeout=.5,
                      poll_interval_secs=0.2)

    self._queue.put('foo')

    self.assertEqual(
        'foo',
        sync_utils.QueueGet(self._queue, timeout=.5, poll_interval_secs=0.2))

    self.assertRaises(queue.Empty, sync_utils.QueueGet, self._queue,
                      timeout=0.5, poll_interval_secs=0.2)

    self._queue.put('bar')

    self.assertEqual(
        'bar',
        sync_utils.QueueGet(self._queue, timeout=.5, poll_interval_secs=0.2))

  @mock.patch('logging.exception')
  def testQueueGetSuccessByDefaultNoLogs(self, logging_mock: mock.MagicMock):
    answer = 123

    def Put():
      self._queue.put(answer)

    self._timeline.AddEvent(10, Put)
    value = sync_utils.QueueGet(self._queue, timeout=None, poll_interval_secs=1)
    logging_mock.assert_not_called()
    self.assertEqual(value, answer)

  @mock.patch('logging.exception')
  def testQueueGetSuccessEnableLoggingShouldLog(self,
                                                logging_mock: mock.MagicMock):
    answer = 123

    def Put():
      self._queue.put(answer)

    self._timeline.AddEvent(10, Put)
    value = sync_utils.QueueGet(self._queue, timeout=None, poll_interval_secs=1,
                                enable_logging=True)
    logging_mock.assert_called()
    self.assertEqual(value, answer)

  @mock.patch(sync_utils.__name__ + '.GetPollingSleepFunction')
  def testQueueGetPassThroughTimeout(self, get_polling_mock: mock.MagicMock):
    # pylint: disable=protected-access
    get_polling_mock.side_effect = (
        lambda: sync_utils._DEFAULT_POLLING_SLEEP_FUNCTION)
    answer = 123

    def Get(timeout, **unused_kwargs):
      if timeout is not None:
        self.assertLessEqual(
            timeout, threading.TIMEOUT_MAX,
            'sleep duration must be smaller than threading.TIMEOUT_MAX.')
      return answer

    local_queue = mock.Mock()
    local_queue.get = Get

    value = sync_utils.QueueGet(local_queue, timeout=None)
    self.assertEqual(value, answer)

  @mock.patch(sync_utils.__name__ + '.GetPollingSleepFunction')
  def testQueueTimeoutInfRaise(self, get_polling_mock: mock.MagicMock):
    # pylint: disable=protected-access
    get_polling_mock.side_effect = (
        lambda: sync_utils._DEFAULT_POLLING_SLEEP_FUNCTION)

    # Return something in case the underlying implementation accepts math.inf.
    self._queue.put(123)
    with self.assertRaises(OverflowError):
      sync_utils.QueueGet(self._queue, timeout=math.inf)


class RetryTest(PollingTestBase):

  def testNormal(self):
    counter = []

    @sync_utils.RetryDecorator(
        max_attempt_count=3,
        interval_sec=0.1,
    )
    def CountFunc():
      counter.append(0)

    CountFunc()

    self.assertEqual(1, len(counter))

  def testRetryCount(self):
    counter = []

    @sync_utils.RetryDecorator(
        max_attempt_count=3,
        interval_sec=0.1,
    )
    def CountFunc():
      counter.append(0)
      if len(counter) != 3:
        raise type_utils.TestFailure

    CountFunc()
    self.assertEqual(3, len(counter))

  def testMaxRetryError(self):

    retry_wrapper = sync_utils.RetryDecorator(
        max_attempt_count=3,
        interval_sec=0,
    )

    def CountFunc():
      raise type_utils.TestFailure

    TestFunc = retry_wrapper(CountFunc)

    self.assertRaises(type_utils.MaxRetryError, TestFunc)

  def testEndOnNoException(self):
    counter = []
    @sync_utils.RetryDecorator(
        timeout_sec=1,
        interval_sec=0,
    )
    def CountFunc():
      counter.append(0)
      if len(counter) != 10:
        raise type_utils.TestFailure

    CountFunc()
    self.assertEqual(10, len(counter))

  def testCatchCustomException(self):
    counter = []

    @sync_utils.RetryDecorator(max_attempt_count=3, interval_sec=0,
                               exceptions_to_catch=[type_utils.TestFailure],
                               reraise=True)
    def CountFunc():
      counter.append(0)
      raise type_utils.TestFailure

    self.assertRaises(type_utils.TestFailure, CountFunc)
    self.assertEqual(3, len(counter))

  def testCatchException(self):
    counter = []

    @sync_utils.RetryDecorator(max_attempt_count=3, interval_sec=0,
                               exceptions_to_catch=[type_utils.TestFailure])
    def CountFunc():
      counter.append(0)
      raise type_utils.Error

    self.assertRaises(type_utils.Error, CountFunc)
    self.assertEqual(1, len(counter))

  def testRetryOnTarget(self):
    counter = []

    @sync_utils.RetryDecorator(timeout_sec=2, interval_sec=0,
                               target_condition=lambda x: len(x) == 2)
    def CountFunc():
      counter.append(0)
      return counter

    CountFunc()
    self.assertEqual(2, len(counter))

  def testRaiseOnTarget(self):

    @sync_utils.RetryDecorator(timeout_sec=0.5, interval_sec=0,
                               exceptions_to_catch=[])
    def CountFunc():
      raise type_utils.TestFailure

    self.assertRaises(type_utils.TestFailure, CountFunc)

  def testRetryUntilTimeout(self):

    @sync_utils.RetryDecorator(timeout_sec=0.5, interval_sec=0.1)
    def CountFunc():
      raise type_utils.TestFailure

    self.assertRaises(type_utils.TimeoutError, CountFunc)

  def testRetryTimeoutErrorReraise(self):

    @sync_utils.RetryDecorator(timeout_sec=0.5, interval_sec=0.1, reraise=True)
    def CountFunc():
      raise type_utils.TestFailure

    self.assertRaises(type_utils.TestFailure, CountFunc)

  def testRetryUntilTimeoutCustomException(self):

    @sync_utils.RetryDecorator(timeout_sec=0.5, interval_sec=0.1,
                               timeout_exception_to_raise=type_utils.Error)
    def CountFunc():
      raise type_utils.TestFailure

    self.assertRaises(type_utils.Error, CountFunc)

  def testNoExceptionTargetNotMet(self):

    counter = []

    @sync_utils.RetryDecorator(max_attempt_count=3,
                               target_condition=lambda x: len(x) == 100)
    def CountFunc():
      counter.append(0)
      return counter

    with self.assertRaises(type_utils.MaxRetryError):
      CountFunc()

  def testCallback(self):

    counter = []

    mock_callback = mock.MagicMock()

    @sync_utils.RetryDecorator(max_attempt_count=5, interval_sec=0.1,
                               target_condition=lambda x: len(x) == 3,
                               retry_callback=mock_callback)
    def CountFunc():
      counter.append(0)
      return counter

    CountFunc()
    # (2, 5) will not be called because it has already satisfied the
    # target_condition.
    mock_callback.assert_called_with(1, 5)



class TimeoutTest(unittest.TestCase):

  def testSignalTimeout(self):
    with sync_utils.SignalTimeout(3):
      time.sleep(1)

    prev_secs = signal.alarm(10)
    self.assertTrue(prev_secs == 0,
                    msg='signal.alarm() is in use after "with SignalTimeout()"')
    try:
      with sync_utils.SignalTimeout(3):
        time.sleep(1)
    except AssertionError:
      pass
    else:
      raise AssertionError("No assert raised on previous signal.alarm()")
    signal.alarm(0)

    try:
      with sync_utils.SignalTimeout(1):
        time.sleep(3)
    except type_utils.TimeoutError:
      pass
    else:
      raise AssertionError("No timeout")

  def testThreadTimeout(self):
    with sync_utils.ThreadTimeout(0.3):
      time.sleep(0.1)

    with sync_utils.ThreadTimeout(0.3):
      with sync_utils.ThreadTimeout(0.2):
        time.sleep(0.1)

    with sync_utils.ThreadTimeout(0.2):
      with sync_utils.ThreadTimeout(0.3):
        time.sleep(0.1)

    with self.assertRaises(type_utils.TimeoutError):
      with sync_utils.ThreadTimeout(0.1):
        time.sleep(0.3)

    with self.assertRaises(type_utils.TimeoutError):
      with sync_utils.ThreadTimeout(0.1):
        with sync_utils.ThreadTimeout(0.5):
          time.sleep(0.3)

    with self.assertRaises(type_utils.TimeoutError):
      with sync_utils.ThreadTimeout(0.5):
        with sync_utils.ThreadTimeout(0.1):
          time.sleep(0.3)

  def testThreadTimeoutInOtherThread(self):
    def WillPass():
      with sync_utils.ThreadTimeout(0.3):
        with sync_utils.ThreadTimeout(0.2):
          time.sleep(0.1)

    def WillTimeout():
      with sync_utils.ThreadTimeout(0.2):
        with sync_utils.ThreadTimeout(0.5):
          time.sleep(0.3)

    def Run(func, q):
      try:
        q.put((True, func()))
      except BaseException as e:
        q.put((False, e))

    q = queue.Queue(1)
    thread = threading.Thread(target=Run, args=(WillPass, q))
    thread.daemon = True
    thread.start()
    thread.join(1)
    self.assertFalse(thread.is_alive())
    flag, value = q.get()
    self.assertTrue(flag)
    self.assertIsNone(value)

    q = queue.Queue(1)
    thread = threading.Thread(target=Run, args=(WillTimeout, q))
    thread.daemon = True
    thread.start()
    thread.join(1)
    self.assertFalse(thread.is_alive())
    flag, value = q.get()
    self.assertFalse(flag)
    self.assertTrue(isinstance(value, type_utils.TimeoutError))

  def testThreadTimeoutCancelTimeout(self):
    with sync_utils.ThreadTimeout(0.2) as timer:
      time.sleep(0.1)
      timer.CancelTimeout()
      time.sleep(0.3)


DELAY = 0.1


class SynchronizedTest(unittest.TestCase):
  class MyClass:
    def __init__(self):
      self._lock = threading.RLock()
      self.data = []

    @sync_utils.Synchronized
    def A(self):
      self.data.append('A1')
      time.sleep(DELAY * 2)
      self.data.append('A2')

    @sync_utils.Synchronized
    def B(self):
      self.data.append('B')

  def setUp(self):
    self.obj = self.MyClass()

  def testSynchronized(self):
    thread_a = threading.Thread(target=self.obj.A, name='A')
    thread_a.start()
    time.sleep(DELAY)
    self.obj.B()
    thread_a.join()
    self.assertEqual(['A1', 'A2', 'B'], self.obj.data)


if __name__ == '__main__':
  unittest.main()
