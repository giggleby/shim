#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
from collections import Counter
import logging
import multiprocessing
import shutil
import tempfile
import threading
from typing import Any
import unittest

from cros.factory.test.utils import csv_utils


CSV_NAME_PREFIX = 'hello_world'
NUM_APPENDER = 10
NUM_EVENT_PER_APPENDER = 1000


class StubFactoryServerProxyError(Exception):
  pass


class StubUnreliableFactoryServer:

  def __init__(self):
    self.counter = Counter()
    self.is_good = True

  def UploadCSVEntry(self, csv_filename, row):
    del csv_filename
    self.is_good = not self.is_good
    if self.is_good:
      self.counter.update([str(row)])
    else:
      raise StubFactoryServerProxyError('OMG...')


class _BaseClassNamespace:
  """A dummy namespace to hide base classes from unittest.main()."""

  class BaseTest(unittest.TestCase, metaclass=abc.ABCMeta):

    def setUp(self):
      self.csv_dir = tempfile.mkdtemp(prefix='csv_util_e2e_test.')
      self.addCleanup(shutil.rmtree, self.csv_dir)
      self.manager = csv_utils.CSVManager(self.csv_dir)

    def testOnce(self):
      appenders, total_entries = self._PrepareAppenders()

      for appender in appenders:
        appender.start()
        self.addCleanup(appender.join)

      self.assertTrue(Upload(self.manager, appenders, total_entries))

    def _PrepareAppenders(self):
      appenders = []

      total_entries = 0
      for i in range(NUM_APPENDER):
        appender, num_entries = self._NewAppender(i)
        appenders.append(appender)
        total_entries += num_entries
      return appenders, total_entries

    def _NewAppender(self, i):
      filename = f'{CSV_NAME_PREFIX}_{i % 2}'
      entries = [(i, j) for j in range(NUM_EVENT_PER_APPENDER)]
      runner = self._NewRunner(target=Append,
                               args=(self.manager, filename, entries))
      return runner, len(entries)

    @abc.abstractmethod
    def _NewRunner(self, target, args) -> Any:
      ...


class ThreadedTester(_BaseClassNamespace.BaseTest):

  def _NewRunner(self, target, args):
    return threading.Thread(target=target, args=args)


class MultiprocessTester(_BaseClassNamespace.BaseTest):

  def _NewRunner(self, target, args):
    return multiprocessing.Process(target=target, args=args)


def Append(manager, filename, entries):
  for e in entries:
    manager.Append(filename, e)
  logging.info('%r: done', filename)


def Upload(manager, appenders, expected_total):
  logging.info('start uploading...')
  server_proxy = StubUnreliableFactoryServer()

  while True:
    try:
      manager.UploadAll(server_proxy)
    except StubFactoryServerProxyError:
      continue

    if any(appender.is_alive() for appender in appenders):
      continue

    if not CheckCounter(server_proxy.counter, expected_total):
      logging.error('Some data is missing')
      return False

    return True


def CheckCounter(counter: Counter, expected_total):
  total = sum(counter.values())
  logging.info('total: %d', total)
  return total == expected_total


if __name__ == '__main__':
  logging.basicConfig(level=logging.DEBUG)
  unittest.main()
