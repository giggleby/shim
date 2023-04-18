# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Benchmark runner for testing a plugin."""

import abc
import time
from typing import Callable, Dict, List, Optional, Type

from cros.factory.instalog import datatypes
from cros.factory.instalog.plugin_base import IBufferPlugin
from cros.factory.instalog.plugin_base import OutputPlugin
from cros.factory.instalog.plugin_base import Plugin
from cros.factory.instalog.plugin_sandbox import PluginSandbox
from cros.factory.instalog.plugins.benchmark.benchmark import BenchmarkResult
from cros.factory.utils import file_utils


class BenchmarkTestConfig:
  """The config object for creating and running PluginBenchmarkRunner.

  The init function forces user to create this object with explicitly specify
  the config key and values. Currently supported config keys are:
  - plugin_class_to_test: A plugin class.
  - plugin_config: A dict supplied to the `plugin_class_to_test`.
  - pre_emit: A boolean value to test the `Produce` method with non-consumable
      events. This only takes effects when the plugin to test is `Buffer`.
  """

  def __init__(self, *, plugin_class_to_test: Type[Plugin], plugin_config: Dict,
               pre_emit: bool = False):
    self.plugin_class_to_test = plugin_class_to_test
    self.plugin_config = plugin_config
    self.pre_emit = pre_emit


class PluginBenchmarkRunner(abc.ABC):
  """The runner that sets up required dependencies to run plugin."""

  def __init__(self, plugin_class_to_test: Type[Plugin],
               plugin_config: Dict) -> None:
    self._plugin_class_to_test = plugin_class_to_test
    self._plugin_config = plugin_config
    self._start_time = 0.0
    self._finish_time = 0.0
    self._measurements: List[float] = []

  def RunBenchmarkTest(self, testing_events: List[datatypes.Event],
                       count: int) -> BenchmarkResult:
    """Starts the benchmark test."""
    for unused_i in range(count):
      self._RunOnce(testing_events)
      self._measurements.append(self._GetLastMeasurement())
    return BenchmarkResult(self._measurements, unit='seconds')

  @abc.abstractmethod
  def _RunOnce(self, testing_events: List[datatypes.Event]) -> None:
    """Run the plugin with testing_events once"""
    raise NotImplementedError

  def _StartCounting(self) -> None:
    self._start_time = time.perf_counter()
    self._finish_time = self._start_time

  def _StopCounting(self) -> None:
    self._finish_time = time.perf_counter()

  def _GetLastMeasurement(self) -> float:
    return self._finish_time - self._start_time


class _BufferPluginBenchmarkRunner(PluginBenchmarkRunner):

  PRODUCER_ID = 'benchmark_producer'
  CONSUMER_ID = 'benchmark_consumer'

  def __init__(self, plugin_class_to_test: Type[IBufferPlugin],
               plugin_config: Dict, pre_emit: bool) -> None:
    super().__init__(plugin_class_to_test, plugin_config)
    self._pre_emit = pre_emit

  def _RunOnce(self, testing_events: List[datatypes.Event]) -> None:
    with file_utils.TempDirectory() as tmp_dir_path:
      plugin_api = _BufferBenchmarkPluginAPIImpl(tmp_dir_path)
      plugin = self._plugin_class_to_test(self._plugin_config, '', {},
                                          plugin_api)
      assert isinstance(plugin, IBufferPlugin)
      plugin.SetUp()
      plugin.AddConsumer(self.CONSUMER_ID)

      self._StartCounting()

      if self._pre_emit:
        plugin.Produce(self.PRODUCER_ID, testing_events, False)
        plugin.Produce(self.PRODUCER_ID, [], True)
      else:
        plugin.Produce(self.PRODUCER_ID, testing_events, True)

      stream = plugin.Consume(self.CONSUMER_ID)
      event = stream.Next()
      while event is not None:
        event = stream.Next()

      self._StopCounting()


class _OutputPluginBenchmarkRunner(PluginBenchmarkRunner):

  def _RunOnce(self, testing_events: List[datatypes.Event]) -> None:
    with file_utils.TempDirectory() as tmp_dir_path:
      plugin_api = _OutputBenchmarkPluginAPIImpl(
          tmp_dir_path, testing_events, self._StartCounting, self._StopCounting)
      plugin = self._plugin_class_to_test(self._plugin_config, '', {},
                                          plugin_api)
      plugin.SetUp()
      plugin.Main()


class _BaseBenchmarkPluginAPIImpl:
  """Base class of PluginAPI implementation used in benchmark test.

  This class is just a placeholder by providing empty implementations for
  implementing the PluginAPI.

  Args:
    data_dir_path: A temp directory string path.
  """

  def __init__(self, data_dir_path: str) -> None:
    self._data_dir_path = data_dir_path

  def SaveStore(self, plugin: PluginSandbox) -> None:
    pass

  def GetDataDir(self, _plugin: PluginSandbox) -> str:
    return self._data_dir_path

  def IsStopping(self, plugin: PluginSandbox) -> bool:
    pass

  def IsFlushing(self, plugin: PluginSandbox) -> bool:
    pass

  def Emit(self, plugin: PluginSandbox, events: List[datatypes.Event]) -> bool:
    pass

  def PreEmit(self, plugin: PluginSandbox,
              events: List[datatypes.Event]) -> bool:
    pass

  def NewStream(self, plugin: PluginSandbox) -> datatypes.EventStream:
    pass

  def EventStreamNext(self, plugin: PluginSandbox,
                      plugin_stream: datatypes.EventStream,
                      timeout: float) -> Optional[datatypes.Event]:
    pass

  def EventStreamCommit(self, plugin: PluginSandbox,
                        plugin_stream: datatypes.EventStream) -> None:
    pass

  def EventStreamAbort(self, plugin: PluginSandbox,
                       plugin_stream: datatypes.EventStream) -> None:
    pass


class _BufferBenchmarkPluginAPIImpl(_BaseBenchmarkPluginAPIImpl):
  """The PluginAPI implementation used in Buffer plugin benchmark testing."""


class _OutputBenchmarkPluginAPIImpl(_BaseBenchmarkPluginAPIImpl):
  """The PluginAPI implementation used in Output plugin benchmark testing.

  Args:
    data_dir_path: A temp directory string path.
    events: a list of datatypes.Event used for testing.
    start_callback: callback function which is executed when the plugin starts
      to request data.
    finish_callback: callback function which is executed if all events are
      consumed and `Commit` is called from the plugin.
  """

  def __init__(self, data_dir_path, events: List[datatypes.Event],
               start_callback: Callable, finish_callback: Callable):
    super().__init__(data_dir_path)
    self._events = events
    self._idx = 0
    self._is_first_stream_requested = False
    self._is_last_event_finished = False
    self._start_callback = start_callback
    self._finish_callback = finish_callback

  def IsStopping(self, plugin: PluginSandbox) -> bool:
    return self._is_last_event_finished

  def IsFlushing(self, plugin: PluginSandbox) -> bool:
    return self.IsStopping(plugin)

  def NewStream(self, plugin: PluginSandbox) -> datatypes.EventStream:
    if not self._is_first_stream_requested:
      self._is_first_stream_requested = True
      self._start_callback()
    return datatypes.EventStream('', self)

  def EventStreamNext(self, plugin: PluginSandbox,
                      plugin_stream: datatypes.EventStream,
                      timeout: float) -> Optional[datatypes.Event]:
    if self._idx == len(self._events):
      return None
    return_idx = self._idx
    self._idx += 1
    return self._events[return_idx]

  def EventStreamCommit(self, plugin: PluginSandbox,
                        plugin_stream: datatypes.EventStream) -> None:
    if not self._idx == len(self._events):
      return

    if self._is_last_event_finished:
      return
    self._is_last_event_finished = True
    self._finish_callback()

  def EventStreamAbort(self, plugin: PluginSandbox,
                       plugin_stream: datatypes.EventStream) -> None:
    self.EventStreamCommit(plugin, plugin_stream)


def CreatePluginBenchmarkRunner(
    test_config: BenchmarkTestConfig) -> PluginBenchmarkRunner:
  if issubclass(test_config.plugin_class_to_test, IBufferPlugin):
    return _BufferPluginBenchmarkRunner(test_config.plugin_class_to_test,
                                        test_config.plugin_config,
                                        test_config.pre_emit)
  if issubclass(test_config.plugin_class_to_test, OutputPlugin):
    return _OutputPluginBenchmarkRunner(test_config.plugin_class_to_test,
                                        test_config.plugin_config)
  raise NotImplementedError(
      f'Unsupported plugin type for {test_config.plugin_class_to_test}')
