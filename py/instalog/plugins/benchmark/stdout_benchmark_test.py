#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.instalog.plugins.benchmark import benchmark
from cros.factory.instalog.plugins.benchmark import benchmark_runner
from cros.factory.instalog.plugins.benchmark.benchmark_runner import BenchmarkTestConfig
from cros.factory.instalog.plugins.benchmark.benchmark_runner import BenchmarkResult
from cros.factory.instalog.plugins.benchmark import events
from cros.factory.instalog.plugins import output_stdout


class BenchmarkStdout(benchmark.BenchmarkCase):

  def BenchmarkSimpleEvents(self) -> BenchmarkResult:
    test_events = events.CreateSimpleEvents(100)
    runner = benchmark_runner.CreatePluginBenchmarkRunner(
        BenchmarkTestConfig(plugin_class_to_test=output_stdout.OutputStdout,
                            plugin_config={}))
    return runner.RunBenchmarkTest(test_events, 10)


if __name__ == '__main__':
  benchmark.Main()
