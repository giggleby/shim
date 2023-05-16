#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import tempfile
from typing import List

import psutil

from cros.factory.instalog import datatypes
from cros.factory.instalog.plugins.benchmark import benchmark
from cros.factory.instalog.plugins.benchmark import benchmark_runner
from cros.factory.instalog.plugins.benchmark.benchmark_runner import BenchmarkResult
from cros.factory.instalog.plugins.benchmark.benchmark_runner import BenchmarkTestConfig
from cros.factory.instalog.plugins.benchmark import events
from cros.factory.instalog.plugins import buffer_simple_file
from cros.factory.utils import file_utils


EVENT_NUM = 10000


class BenchmarkBufferSimpleFile(benchmark.BenchmarkCase):

  def _BenchmarkEvents(self, test_events: List[datatypes.Event], pre_emit: bool,
                       count: int) -> BenchmarkResult:
    runner = benchmark_runner.CreatePluginBenchmarkRunner(
        BenchmarkTestConfig(
            plugin_class_to_test=buffer_simple_file.BufferSimpleFile,
            pre_emit=pre_emit, plugin_config={}))
    return runner.RunBenchmarkTest(test_events, count)

  def BenchmarkSimpleEvents(self) -> BenchmarkResult:
    test_events = events.CreateSimpleEvents(100)
    return self._BenchmarkEvents(test_events, False, 10)

  def BenchmarkSimpleEventsWithPreEmit(self) -> BenchmarkResult:
    test_events = events.CreateSimpleEvents(100)
    return self._BenchmarkEvents(test_events, True, 10)

  def BenchmarkEventsWithAttachment(self) -> BenchmarkResult:
    with file_utils.TempDirectory() as tmp_dir_path:
      test_events = events.CreateEvents(1000, 5, 1 * 1024 * 1024, tmp_dir_path)
      return self._BenchmarkEvents(test_events, False, 1)

  def BenchmarkEventsWithAttachmentWithPreEmit(self) -> BenchmarkResult:
    with file_utils.TempDirectory() as tmp_dir_path:
      test_events = events.CreateEvents(1000, 5, 1 * 1024 * 1024, tmp_dir_path)
      return self._BenchmarkEvents(test_events, True, 1)

  def BenchmarkEventsMemoryUsage(self) -> BenchmarkResult:
    # Count virtual memory as we care about the total memory used by objects,
    # not the occupied size on the physical memory.
    memory_before_creating_events = psutil.Process().memory_info().vms
    test_events = events.CreateSimpleEvents(EVENT_NUM)
    memory_after_creating_events = psutil.Process().memory_info().vms
    del test_events
    rough_memory_for_events = \
        memory_after_creating_events - memory_before_creating_events
    return BenchmarkResult([rough_memory_for_events], unit='KiB')

  def BenchmarkEventsMemoryUsage_NonConsumable(self) -> BenchmarkResult:
    sf = buffer_simple_file.BufferSimpleFile(config={}, logger_name='',
                                             store={}, plugin_api=None)
    data_dir = tempfile.mkdtemp(prefix='buffer_simple_file_benchmark_')
    sf.GetDataDir = lambda: data_dir
    sf.SetUp()

    memory_before_produce = psutil.Process().memory_info().vms
    test_events = events.CreateSimpleEvents(1)
    for unused_i in range(EVENT_NUM):
      sf.Produce('test_producer', test_events, False)
    memory_after_produce = psutil.Process().memory_info().vms
    rough_memory_for_non_consumable = \
        memory_after_produce - memory_before_produce
    return BenchmarkResult([rough_memory_for_non_consumable], unit='KiB')


if __name__ == '__main__':
  benchmark.Main()
