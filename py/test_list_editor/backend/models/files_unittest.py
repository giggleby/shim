# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import unittest
from unittest import mock

from cros.factory.test.test_lists import test_list_common
from cros.factory.test_list_editor.backend.models import files


class TestTestListFileFactory(unittest.TestCase):

  def setUp(self):
    self.test_list_factory = files.GetFactoryInstance()

  def testGetJSON(self):
    json_test_list = self.test_list_factory.Get(data={}, filename='')
    self.assertIsInstance(json_test_list, files.TestListFile)


class TestTestListFile(unittest.TestCase):

  def setUp(self):
    self.data = {
        'foo': 'bar'
    }
    self.filename = 'test_list.json'
    self.test_list_file = files.TestListFile(self.data, self.filename)

  @mock.patch.object(test_list_common, 'SaveTestList')
  def testSaveToDisk(self, MockSave):
    self.test_list_file.Save()
    MockSave.assert_called_once_with(self.data, self.filename)

  @mock.patch.object(test_list_common, 'LoadTestList')
  def testLoadFromDisk(self, MockSave: mock.Mock):
    fake_data = {
        'test': True
    }
    MockSave.return_value = fake_data
    self.test_list_file = files.TestListFile({}, self.filename)
    self.test_list_file.Load()
    self.assertEqual(self.test_list_file.data, fake_data)
