#!/usr/bin/env python3
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import multiprocessing.pool
import os
import shutil
import unittest

from cros.factory.umpire.server import resource
from cros.factory.umpire.server import umpire_env
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils


TESTDATA_DIR = os.path.join(os.path.dirname(__file__), 'testdata')
TEST_CONFIG = os.path.join(TESTDATA_DIR, 'minimal_empty_services_umpire.json')
TOOLKIT_DIR = os.path.join(TESTDATA_DIR, 'install_factory_toolkit.run')


class UmpireEnvTest(unittest.TestCase):

  def setUp(self):
    self.env = umpire_env.UmpireEnvForTest()

  def tearDown(self):
    self.env.Close()

  def testLoadConfigDefault(self):
    default_path = os.path.join(self.env.base_dir, 'active_umpire.json')
    shutil.copy(TEST_CONFIG, default_path)

    self.env.LoadConfig()
    self.assertEqual(default_path, self.env.config_path)

  def testLoadConfigCustomPath(self):
    custom_path = os.path.join(self.env.base_dir, 'custom_config.json')
    shutil.copy(TEST_CONFIG, custom_path)

    self.env.LoadConfig(custom_path=custom_path)
    self.assertEqual(custom_path, self.env.config_path)

  def testActivateConfigFile(self):
    file_utils.TouchFile(self.env.active_config_file)
    config_to_activate = os.path.join(self.env.base_dir, 'to_activate.json')
    file_utils.TouchFile(config_to_activate)

    self.env.ActivateConfigFile(config_path=config_to_activate)
    self.assertTrue(os.path.exists(self.env.active_config_file))
    self.assertEqual(config_to_activate,
                     os.path.realpath(self.env.active_config_file))

  def testGetResourcePath(self):
    resource_path = self.env.AddConfigFromBlob(
        'hello', resource.ConfigTypes.umpire_config)
    resource_name = os.path.basename(resource_path)

    self.assertTrue(resource_path, self.env.GetResourcePath(resource_name))

  def testGetResourcePathNotFound(self):
    self.assertRaises(IOError, self.env.GetResourcePath, 'foobar')

    # Without check, just output resource_dir/resource_name
    self.assertEqual(os.path.join(self.env.resources_dir, 'foobar'),
                     self.env.GetResourcePath('foobar', check=False))


class ReportIndexManagerTest(unittest.TestCase):

  def setUp(self):
    self.database_path = file_utils.CreateTemporaryFile()
    self.server_uuid = 'random_server_uuid'
    self._InitDatabase()

    self.manager = umpire_env.ReportIndexManager(self.database_path)

  def _InitDatabase(self):
    json_utils.DumpFile(self.database_path, {
        'server_uuid': self.server_uuid,
        'next_report_index': 1,
    })

  def tearDown(self):
    os.unlink(self.database_path)

  def testAllocateNextIndex_Success(self):
    with self.manager.AllocateNextIndex() as (server_uuid, report_index):
      self.assertEqual(server_uuid, self.server_uuid)
      self.assertEqual(report_index, 1)

    with self.manager.AllocateNextIndex() as (server_uuid, report_index):
      self.assertEqual(server_uuid, self.server_uuid)
      self.assertEqual(report_index, 2)

  def testAllocateNextIndex_Exception(self):
    with self.manager.AllocateNextIndex() as (server_uuid, report_index):
      self.assertEqual(server_uuid, self.server_uuid)
      self.assertEqual(report_index, 1)

    with self.assertRaises(ValueError):
      with self.manager.AllocateNextIndex() as (server_uuid, report_index):
        self.assertEqual(server_uuid, self.server_uuid)
        self.assertEqual(report_index, 2)
        raise ValueError('something went wrong')

    with self.manager.AllocateNextIndex() as (server_uuid, report_index):
      self.assertEqual(server_uuid, self.server_uuid)
      self.assertEqual(report_index, 2)

  def testAllocateNextIndex_Threaded(self):

    def _CallOnce(unused_args):
      manager = umpire_env.ReportIndexManager(self.database_path)
      with manager.AllocateNextIndex() as (server_uuid, report_index):
        return server_uuid, report_index

    num_reports = 20

    with multiprocessing.pool.ThreadPool(10) as p:
      result = p.map(_CallOnce, [None] * num_reports)
      self.assertEqual(
          sorted(list(result)),
          [(self.server_uuid, i) for i in range(1, num_reports + 1)])

  def testAllocateNextIndex_Threaded_with_Failure(self):

    def _ShouldSuccess(thread_index: int):
      return thread_index % 3 != 0

    def _CallOnce(thread_index: int):
      try:
        with self.manager.AllocateNextIndex() as (server_uuid, report_index):
          if _ShouldSuccess(thread_index):
            return thread_index, server_uuid, report_index
          raise ValueError
      except ValueError:
        return thread_index, None, None

    num_reports = 20
    with multiprocessing.pool.ThreadPool(10) as p:
      results = p.map(_CallOnce, list(range(num_reports)))

      success_results = []
      for result in results:
        thread_index, server_uuid, report_index = result

        self.assertEqual(_ShouldSuccess(thread_index), server_uuid is not None)

        if _ShouldSuccess(thread_index):
          success_results.append((server_uuid, report_index))

      n_success = len(success_results)
      self.assertEqual(
          sorted(list(success_results)),
          [(self.server_uuid, i) for i in range(1, n_success + 1)])


if __name__ == '__main__':
  unittest.main()
