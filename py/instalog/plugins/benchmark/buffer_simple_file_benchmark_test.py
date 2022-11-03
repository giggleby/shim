#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List

from cros.factory.instalog import datatypes
from cros.factory.instalog.plugins.benchmark import benchmark
from cros.factory.instalog.plugins.benchmark import benchmark_runner
from cros.factory.instalog.plugins.benchmark.benchmark_runner import BenchmarkResult
from cros.factory.instalog.plugins.benchmark.benchmark_runner import BenchmarkTestConfig
from cros.factory.instalog.plugins.benchmark import events
from cros.factory.instalog.plugins import buffer_simple_file
from cros.factory.instalog.utils import file_utils


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


if __name__ == '__main__':
  benchmark.Main()
