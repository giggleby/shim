#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import csv
import shutil
import tempfile
import unittest
from unittest import mock

from cros.factory.test.utils import csv_utils
from cros.factory.utils import sync_utils


class StubFactoryServerException(Exception):
  pass


class _StubFactoryServerProxy:

  def __init__(self):
    self.upload_csv_entry_mock = mock.Mock()

  def UploadCSVEntry(self, *args, **kwargs):
    self.upload_csv_entry_mock(*args, **kwargs)


class _StubUnreliableFactoryServerProxy(_StubFactoryServerProxy):

  def __init__(self):
    super().__init__()
    self.will_fail = True

  def UploadCSVEntry(self, *args, **kwargs):
    self.will_fail = not self.will_fail
    if self.will_fail:
      raise StubFactoryServerException
    self.upload_csv_entry_mock(*args, **kwargs)


class CSVManagerUnittest(unittest.TestCase):
  # pylint: disable=protected-access

  def setUp(self):
    self.csv_dir = tempfile.mkdtemp()
    self.addCleanup(shutil.rmtree, self.csv_dir)
    self.manager = csv_utils.CSVManager(self.csv_dir)

  def testGetCSVPath(self):
    path = self.manager._GetCSVPath('123')
    self.assertTrue(path.startswith(self.csv_dir))

  def testGetCSVFilename(self):
    csv_filename = 'a_csv_filename'
    csv_path = self.manager._GetCSVPath(csv_filename)
    self.assertEqual(self.manager._GetCSVFilename(csv_path), csv_filename)

  def testSaveOneEntry(self):
    csv_filename = 'csv_filename'
    self.manager.Append(csv_filename, ['hello', 'world'])

    with open(self.manager._GetCSVPath(csv_filename), encoding='utf-8') as f:
      reader = csv.reader(f)
      self.assertEqual(list(reader), [['hello', 'world']])

  def testSaveMultipleEntries(self):
    expected = self._SaveMultipleEntries()

    for csv_filename, content in expected.items():
      with open(self.manager._GetCSVPath(csv_filename), encoding='utf-8') as f:
        reader = csv.reader(f)
        self.assertEqual(list(reader), content)

  def _SaveMultipleEntries(self):
    data_to_save = {
        'file_a': [['0', '1'], ['2', '3']],
        'file_b': [['4', '5'], ['6', '7']]
    }
    for csv_filename, entries in data_to_save.items():
      for entry in entries:
        self.manager.Append(csv_filename, entry)
    return data_to_save

  def testUploadAll(self):
    expected = self._SaveMultipleEntries()

    with mock.patch.object(self.manager, '_UploadOneFile') as patched:
      server_proxy = _StubFactoryServerProxy()
      self.manager.UploadAll(server_proxy)
      self.assertEqual(
          sorted(patched.call_args_list),
          sorted([
              mock.call(server_proxy, self.manager._GetCSVPath(csv_filename))
              for csv_filename in expected
          ]))

  def testUploadOneFile(self):
    expected = self._SaveMultipleEntries()

    server_proxy = _StubFactoryServerProxy()

    for csv_filename, entries in expected.items():
      csv_path = self.manager._GetCSVPath(csv_filename)
      self.manager._UploadOneFile(server_proxy, csv_path)

      self.assertEqual(server_proxy.upload_csv_entry_mock.call_args_list,
                       [mock.call(csv_filename, entry) for entry in entries])
      server_proxy.upload_csv_entry_mock.reset_mock()

  def testUploadWithFailure(self):
    expected = self._SaveMultipleEntries()

    server_proxy = _StubUnreliableFactoryServerProxy()

    for csv_filename, entries in expected.items():
      csv_path = self.manager._GetCSVPath(csv_filename)

      retry_decoractor = sync_utils.RetryDecorator(
          interval_sec=0, exceptions_to_catch=[StubFactoryServerException])

      retry_decoractor(self.manager._UploadOneFile)(server_proxy, csv_path)

      # When everything is done, we should still have CSV entries in the correct
      # order, and no duplications.
      self.assertEqual(server_proxy.upload_csv_entry_mock.call_args_list,
                       [mock.call(csv_filename, entry) for entry in entries])
      server_proxy.upload_csv_entry_mock.reset_mock()


if __name__ == '__main__':
  unittest.main()
