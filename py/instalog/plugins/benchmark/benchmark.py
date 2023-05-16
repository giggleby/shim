# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import functools
import statistics
from typing import Callable, Dict, List


class NoBenchmarkResultError(Exception):
  """Benchmark result is not ready, or benchmark test not conducted."""


class BenchmarkResult:

  def __init__(self, measurements: List[float], unit: str = '') -> None:
    self.measurements = measurements
    self.unit = unit

  def GetAverage(self) -> float:
    """Get the average from recorded measurements."""
    if not self.measurements:
      raise NoBenchmarkResultError
    return statistics.mean(self.measurements)


def _IsBenchmarkMethod(attr_name, attr):
  return attr_name.startswith('Benchmark') and callable(attr)


class BenchmarkMetaclass(type):

  def __new__(cls, classname, bases, classDict):
    newClassDict = {}
    for attr_name, attr in classDict.items():
      if _IsBenchmarkMethod(attr_name, attr):
        newClassDict[attr_name] = cls._WrapBenchmarkCallable(attr)
      else:
        newClassDict[attr_name] = attr
    return type.__new__(cls, classname, bases, newClassDict)

  @classmethod
  def _WrapBenchmarkCallable(cls, benchmark_callable: Callable) -> Callable:

    @functools.wraps(benchmark_callable)
    def _WrappedFunction(*args, **kwargs):
      result = benchmark_callable(*args, **kwargs)
      assert isinstance(result, BenchmarkResult)
      return result

    return _WrappedFunction


class BenchmarkCase(metaclass=BenchmarkMetaclass):
  """BenchmarkCase is the base class of all benchmark test cases.

  All benchmark test case should inherit from this base class, then the
  benchmark Main function provided in this module can extract instance methods,
  and run these methods to get a `BenchmarkResult` instance.

  A valid benchmark method must have the prefix `Benchmark`, and returns a
  `BenchmarkResult`.

  Examples:
    class A(BenchmarkCase):
      def BenchmarkA(self):
        return BenchmarkResult()

  The `BenchmarkA` is extract by the `Main` function.
  """

  def GetBenchmarkTests(self) -> Dict[str, Callable]:
    """Returns all the instance methods where name starts with `Benchmark`.

    Returns:
      A dict from benchmark method name to that callable.
    """
    benchmark_tests: Dict[str, Callable] = {}
    for element_str in dir(self):
      attr = getattr(self, element_str)
      if _IsBenchmarkMethod(element_str, attr):
        benchmark_tests[element_str] = attr
    return benchmark_tests


def CreateBenchmarkCases(module) -> Dict[str, BenchmarkCase]:
  """Find benchmark cases from the give module.

  Args:
    module: A python module.

  Returns:
    A dict of derived `BenchmarkCase` class name to that case instance.
  """
  benchmark_cases = {}
  for element_str in dir(module):
    obj = getattr(module, element_str)
    if isinstance(obj, type) and issubclass(obj, BenchmarkCase):
      benchmark_cases[element_str] = obj()
  return benchmark_cases


def Main(module='__main__'):
  """The helper main function is for running benchmark tests.

  This function must be called from a benchmark test .py file, and all functions
  in the caller file with name starts with `Benchmark` will be treated as a
  runnable benchmark function
  """
  caller_module = __import__(module)
  benchmark_cases = CreateBenchmarkCases(caller_module)
  available_benchmarks: Dict[str, Callable] = {}
  for case_name, case_class in benchmark_cases.items():
    for benchmark_name, method in case_class.GetBenchmarkTests().items():
      available_benchmarks[f'{case_name}.{benchmark_name}'] = method

  parser = argparse.ArgumentParser(description='Run benchmarks.')
  parser.add_argument('--list', action='store_true',
                      help='list available benchmark tests')
  parser.add_argument('--benchmarks', nargs='+', default=['all'],
                      choices=['all'] + list(available_benchmarks),
                      help='benchmark tests to run')
  args = parser.parse_args()

  if args.list:
    print('Available benchmark tests found:')
    for benchmark in available_benchmarks:
      print(f'- {benchmark}')
    return

  if 'all' in args.benchmarks:
    args.benchmarks = list(available_benchmarks)

  for benchmark in args.benchmarks:
    result = available_benchmarks[benchmark]()
    print(f'Run {benchmark}, get average = {result.GetAverage()} {result.unit}')
