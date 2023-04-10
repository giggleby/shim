# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Synchronization-related utilities (waiting for state change)."""

import _thread
import contextlib
import functools
import logging
import math
import queue
import signal
import sys
import threading
import time
from typing import Callable, Optional, Sequence, Type, TypeVar, Union

from cros.factory.utils import thread_utils
from cros.factory.utils import time_utils
from cros.factory.utils import type_utils


_HAVE_CTYPES = False
try:
  import ctypes
  _HAVE_CTYPES = True
except Exception:
  pass

DEFAULT_TIMEOUT_SECS = 10
DEFAULT_POLL_INTERVAL_SECS = 0.1

_DEFAULT_POLLING_SLEEP_FUNCTION = time.sleep
_POLLING_SLEEP_FUNCTION_KEY = 'sync_utils_polling_sleep_function'


def GetPollingSleepFunction() -> Callable[[float], None]:
  return thread_utils.LocalEnv().get(_POLLING_SLEEP_FUNCTION_KEY,
                                     _DEFAULT_POLLING_SLEEP_FUNCTION)


@contextlib.contextmanager
def WithPollingSleepFunction(sleep_func):
  """Set the function to be used to sleep for PollForCondition and Retry.

  Note that the Timeout() context manager is not affected by this.

  Args:
    sleep_func: A function whose only argument is number of seconds to sleep.
  """
  with thread_utils.SetLocalEnv(**{_POLLING_SLEEP_FUNCTION_KEY: sleep_func}):
    yield


T = TypeVar('T')


def PollForCondition(poll_method: Callable[[], T],
                     condition_method: Callable[[T], bool] = bool,
                     timeout_secs: float = DEFAULT_TIMEOUT_SECS,
                     poll_interval_secs: float = DEFAULT_POLL_INTERVAL_SECS,
                     condition_name: Optional[str] = None) -> T:
  """Polls for every poll_interval_secs until timeout reached or condition met.

  It is a blocking call. If the condition is met, poll_method's return value
  is passed onto the caller. Otherwise, a TimeoutError is raised.

  Args:
    poll_method: a method to be polled. The method's return value will be passed
        into condition_method.
    condition_method: a method to decide if poll_method's return value is valid.
        None for standard Python if statement.
    timeout_secs: maximum number of seconds to wait, None means forever.
    poll_interval_secs: interval to poll condition.
    condition_name: description of the condition. Used for TimeoutError when
        timeout_secs is reached.

  Returns:
    poll_method's return value.

  Raises:
    type_utils.TimeoutError when timeout_secs is reached but condition has not
        yet been met.
  """
  end_time = time_utils.MonotonicTime() + timeout_secs if timeout_secs else None
  sleep = GetPollingSleepFunction()
  while True:
    if condition_name and end_time is not None:
      logging.debug('[%ds left] %s', end_time - time_utils.MonotonicTime(),
                    condition_name)
    ret = poll_method()
    if condition_method(ret):
      return ret
    if ((end_time is not None) and
        (time_utils.MonotonicTime() + poll_interval_secs > end_time)):
      if condition_name:
        msg = f'Timed out waiting for condition: {condition_name}'
      else:
        msg = 'Timed out waiting for unnamed condition'
      logging.info(msg)
      raise type_utils.TimeoutError(msg, ret)
    sleep(poll_interval_secs)


def WaitFor(condition: Callable[[],
                                T], timeout_secs: float = DEFAULT_TIMEOUT_SECS,
            poll_interval: float = DEFAULT_POLL_INTERVAL_SECS) -> T:
  """Wait for the given condition for at most the specified time.

  Args:
    condition: A function object.
    timeout_secs: Timeout value in seconds.
    poll_interval: Interval to poll condition.

  Raises:
    ValueError: If condition is not a function.
    TimeoutError: If cond does not become True after timeout_secs seconds.
  """
  if not callable(condition):
    raise ValueError('condition must be a callable object')

  @RetryDecorator(timeout_sec=timeout_secs if timeout_secs else math.inf,
                  interval_sec=poll_interval, target_condition=bool)
  def WaitForCondition() -> T:
    return condition()

  return WaitForCondition()


def QueueGet(q: 'queue.Queue[T]',
             timeout: Optional[float] = DEFAULT_TIMEOUT_SECS,
             poll_interval_secs: float = DEFAULT_POLL_INTERVAL_SECS) -> T:
  """Get from a queue.Queue, possibly by polling.

  This is useful when a custom polling sleep function is set.
  """
  if not timeout:
    timeout = math.inf

  if GetPollingSleepFunction() is _DEFAULT_POLLING_SLEEP_FUNCTION:
    return q.get(timeout=timeout)

  @RetryDecorator(timeout_sec=timeout, interval_sec=poll_interval_secs,
                  exceptions_to_catch=[queue.Empty], reraise=True)
  def QueueGetNowait() -> T:
    return q.get_nowait()

  return QueueGetNowait()


def EventWait(event: threading.Event, timeout: Optional[float] = None,
              poll_interval_secs: float = DEFAULT_POLL_INTERVAL_SECS) -> bool:
  """Wait for a threading.Event upto `timeout` seconds

  This function waits for a `Event` to be set. If the `Event` is set within
  `timeout` seconds, the function returns `True`. Otherwise, `False`.

  Returns:
    bool: True if the event is set, otherwise False.
  """
  if not timeout:
    timeout = math.inf

  @RetryDecorator(timeout_sec=timeout, interval_sec=poll_interval_secs,
                  target_condition=bool)
  def WaitEventSet() -> bool:
    return event.is_set()

  try:
    return WaitEventSet()
  except type_utils.TimeoutError:
    return False


# TODO(louischiu) Migrate all the RetryDecorator to retry
def RetryDecorator(
    *, max_attempt_count: int = sys.maxsize, timeout_sec: float = math.inf,
    interval_sec: float = 0.5,
    target_condition: Optional[Callable[[T], bool]] = None,
    exceptions_to_catch: Union[None, Sequence[Type[Exception]]] = None,
    timeout_exception_to_raise: Type[Exception] = type_utils.TimeoutError,
    reraise: bool = False, sleep: Optional[Callable[[float], None]] = None,
    retry_callback: Optional[Callable[[int, int], None]] = None) -> Callable:
  """A decorator to handle the retry mechanism

  The decorator to handle the nuances of retrying.

  Usage:
    1. We want to attempt execution for 5 times.
    @RetryDecorator(max_attempt_count=5)
    def foo():
      raise Exception

    foo() # Executes 5 times and stops

    2. We want to retry for 10 seconds and abort.
    @RetryDecorator(timeout_sec=10)
    def foo():
      raise Exception

    3. We want to retry for 5 seconds, between each run wait for
      0.5 seconds.
    @RetryDecorator(timeout_sec=5,
      interval_sec=0.5
    )
    def foo():
      raise Exception

    4. We want to retry until it returns 5
    @RetryDecorator(
      target_condition=lambda x: x == 5
    )
    def foo():
      return random.randint(0, 10)

    4.1 We want to retry on a condition but raise any exception
      it encountered.
    @RetryDecorator(
      target_condition=lambda x: x == 5,
      exceptions_to_catch=[]
    )
    def foo():
      raise Exceptions

    foo() # Raises exception

    5. We only retry if the exception is what we want.
    @RetryDecorator(
      exceptions_to_catch=[MyException]
    )
    def foo():
      raise MyExcept

    @RetryDecorator(
      exceptions_to_catch=[MyException]
    )
    def bar():
      raise AnotherException

    foo() # Will retry forever
    bar() # Will NOT retry and raises AnotherException

    6. We want to raise custom timeout exception on timeout
    @RetryDecorator(
      timeout_sec=1,
      timeout_exception_to_raise=MyTimeoutException
    )
    def foo():
      raise

    foo() # raises MyTimeoutException

  Args:
    max_attempt_count: Number of times to attempt execution.
        It will retry forever, if not set.
    timeout_sec: Number of seconds to wait before ending. Defaults to inf,
        which is no timeout.
    interval_sec: Number of seconds to wait between each run.
    target_condition: The function that takes the result of the function
        as parameter and evaluates the result. If not given, then the decorator
        will end as soon as the function has ended without any exception.
    exceptions_to_catch: The exception(s) we wanted to catch.
        Set to None if you want to catch all the
        exceptions. Set to [] if you don't want to catch
        any exceptions.
    timeout_exception_to_raise: The exception to raise if timeout is
        encountered. Defaults to type_utils.TimeoutError.
    reraise: If you want to re-raise the error at timeout or
        exceed max_attempt_count.
    sleep: The sleep function we want to use.
    retry_callback: A callback function accepting two int arguments,
        `loop_count` and `max_attempt_count`. The callback function will be
        called right after executing the wrapped function.
  """
  if exceptions_to_catch is None:
    # set default
    exceptions_to_catch = [Exception]
  custom_exceptions = type_utils.MakeTuple(exceptions_to_catch)

  if target_condition is not None and not callable(target_condition):
    raise TypeError

  if retry_callback and not callable(retry_callback):
    raise TypeError('retry_callback should be callable')

  if timeout_sec is None:
    raise ValueError('timeout_sec cannot be None, please use float("inf")')

  end_time = time_utils.MonotonicTime() + timeout_sec

  if not callable(sleep):
    sleep = GetPollingSleepFunction()

  def Decorator(func: Callable[..., T]):
    @functools.wraps(func)
    def Execute(*args, **kwargs):
      result = None
      captured_exception = None
      for loop_count in range(max_attempt_count):
        try:
          result = func(*args, **kwargs)
        except custom_exceptions as captured_exception:  # pylint: disable=catching-non-exception
          logging.exception('Retry... loop count: %d / %d', loop_count,
                            max_attempt_count)
          if retry_callback:
            retry_callback(loop_count, max_attempt_count)
          now = time_utils.MonotonicTime()
          if now + interval_sec > end_time:
            if reraise:
              raise captured_exception
            raise timeout_exception_to_raise from captured_exception
          if loop_count == max_attempt_count - 1:
            if reraise:
              raise captured_exception
            raise type_utils.MaxRetryError from captured_exception
          sleep(interval_sec)
          continue
        # Use target condition to verify
        if target_condition is not None and not target_condition(result):
          logging.warning('Target condition not met, loop count: %d / %d',
                          loop_count, max_attempt_count)
          if retry_callback:
            retry_callback(loop_count, max_attempt_count)
          now = time_utils.MonotonicTime()
          if now + interval_sec > end_time:
            raise timeout_exception_to_raise
          if loop_count == max_attempt_count - 1:
            raise type_utils.MaxRetryError
          sleep(interval_sec)
        else:
          logging.info('Retry: Get result in retry_time: %d.', loop_count)
          # target condition met or function successfully executed
          break
      return result

    return Execute

  return Decorator


# TODO(louischiu) This Retry function will be deprecated soon
#                 use the above retry decorator instead.
def Retry(max_retry_times, interval, callback, target, *args, **kwargs):
  """Retries a function call with limited times until it returns True.

  Args:
    max_retry_times: The max retry times for target function to return True.
    interval: The sleep interval between each trial.
    callback: The callback after each retry iteration. Caller can use this
              callback to track progress. Callback should accept two arguments:
              callback(retry_time, max_retry_times).
    target: The target function for retry. *args and **kwargs will be passed to
            target.

  Returns:
    Within max_retry_times, if the return value of target function is
    neither None nor False, returns the value.
    If target function returns False or None or it throws
    any exception for max_retry_times, returns None.
  """
  result = None
  sleep = GetPollingSleepFunction()
  for retry_time in range(max_retry_times):
    try:
      result = target(*args, **kwargs)
    except Exception:
      logging.exception('Retry...')
    if callback:
      callback(retry_time, max_retry_times)
    if result:
      logging.info('Retry: Get result in retry_time: %d.', retry_time)
      break
    sleep(interval)
  return result


def Timeout(secs: float, use_signal=False):
  """Timeout context manager.

  It will raise TimeoutError after timeout is reached, interrupting execution
  of the thread.  Since implementation `ThreadTimeout` is more powerful than
  `SignalTimeout` in most cases, by default, ThreadTimeout will be used.

  You can force using SignalTimeout by setting `use_signal` to True.

  Example::

    with Timeout(0.5):
      # script in this block has to be done in 0.5 seconds

  Args:
    secs: Number of seconds to wait before timeout.
    use_signal: force using SignalTimeout (implemented by signal.alarm)
  """
  if not _HAVE_CTYPES or use_signal:
    # b/275018373: SignalTimeout fails when secs is not integer.
    return SignalTimeout(secs)
  return ThreadTimeout(secs)


def WithTimeout(secs: float, use_signal=False):
  """Function decorator that adds a limited execution time to the function.

  Please see `Timeout`

  Example::

    @WithTimeout(0.5)
    def func(a, b, c):  # execution time of func will be limited to 0.5 seconds
      ...
  """

  def _Decorate(func: Callable):

    @functools.wraps(func)
    def _Decorated(*func_args, **func_kwargs):
      with Timeout(secs, use_signal):
        return func(*func_args, **func_kwargs)

    return _Decorated

  return _Decorate


@contextlib.contextmanager
def SignalTimeout(secs: float):
  """Timeout context manager.

  It will raise TimeoutError after timeout is reached, interrupting execution
  of the thread.  It does not support nested "with Timeout" blocks, and can only
  be used in the main thread of Python.

  Args:
    secs: Number of seconds to wait before timeout.

  Raises:
    TimeoutError if timeout is reached before execution has completed.
    ValueError if not run in the main thread.
  """
  def handler(signum, frame):
    del signum, frame  # Unused.
    raise type_utils.TimeoutError('Timeout')

  old_handler = None
  if secs:
    old_handler = signal.signal(signal.SIGALRM, handler)
    prev_secs = signal.alarm(secs)
    assert not prev_secs, 'Alarm was already set before.'

  try:
    yield
  finally:
    if secs:
      signal.alarm(0)
      assert old_handler is not None
      signal.signal(signal.SIGALRM, old_handler)


def Synchronized(f: Callable):
  """Decorates a member function to run with a lock

  The decorator is for Synchronizing member functions of a class object. To use
  this decorator, the class must initialize self._lock as threading.RLock in
  its constructor.

  Example:

  class MyServer:
    def __init__(self):
      self._lock = threading.RLock()

    @sync_utils.Synchronized
    def foo(self):
      ...

    @sync_utils.Synchronized
    def bar(self):
      ...

  """
  @functools.wraps(f)
  def wrapped(self, *args, **kw):
    # pylint: disable=protected-access
    if not self._lock or not isinstance(self._lock, _thread.RLock):
      raise RuntimeError(
          ("To use @Synchronized, the class must initialize self._lock as"
           " threading.RLock in its __init__ function."))

    with self._lock:
      return f(self, *args, **kw)

  return wrapped


class ThreadTimeout:
  """Timeout context manager.

  It will raise TimeoutError after timeout is reached, interrupting execution
  of the thread.

  Args:
    secs: Number of seconds to wait before timeout.

  Raises:
    TimeoutError if timeout is reached before execution has completed.
    ValueError if not run in the main thread.
  """

  def __init__(self, secs: float):
    self._secs = secs
    self._timer: Optional[threading.Timer] = None
    self._current_thread = threading.current_thread().ident
    self._lock = threading.RLock()

  def __enter__(self):
    with self._lock:
      self.SetTimeout()
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    with self._lock:
      self.CancelTimeout()
      return False

  def SetTimeout(self):
    if self._secs:
      self._timer = threading.Timer(self._secs, self._RaiseTimeoutException)
      self._timer.start()

  def CancelTimeout(self):
    with self._lock:
      if self._timer:
        self._timer.cancel()
      logging.debug('timer cancelled')

  def _RaiseTimeoutException(self):
    with self._lock:
      logging.debug('will raise exception')
      TryRaiseExceptionInThread(self._current_thread, type_utils.TimeoutError)


def TryRaiseExceptionInThread(thread_id, exception_class):
  """Try to raise an exception in a thread.

  This relies on cpython internal, does not guarantee to work and is generally
  a bad idea to do. So this function should only be used for exception that is
  "nice to have", but not necessary.

  Args:
    thread_id: The thread id of the thread, can be obtained by thread.ident.
    exception_class: The class of the exception to be thrown. Only exception
        class can be set, but not exception instance due to limit of cpython
        API.
  """
  num_modified_threads = ctypes.pythonapi.PyThreadState_SetAsyncExc(
      ctypes.c_long(thread_id), ctypes.py_object(exception_class))
  if num_modified_threads == 0:
    # thread ID is invalid, maybe the thread no longer exists?
    raise ValueError('Invalid thread ID')
  if num_modified_threads > 1:
    # somehow, more than one threads are modified, try to undo
    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_id), None)
    raise SystemError('PthreadState_SetAsyncExc failed')
