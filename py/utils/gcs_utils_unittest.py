#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for gcs_utils.py."""

import logging
import multiprocessing
import sys
import unittest
from unittest import mock

sys.modules['google.cloud.storage'] = mock.Mock()
from cros.factory.utils import gcs_utils  # pylint: disable=wrong-import-position


class TestParallelDownloader(unittest.TestCase):

  def setUp(self):
    self.mock_cloud_storage = mock.MagicMock()
    self.patcher = mock.patch('cros.factory.utils.gcs_utils.CloudStorage',
                              return_value=self.mock_cloud_storage)
    self.patcher.start()

  def tearDown(self):
    self.patcher.stop()

  def testDownloadFile(self):
    TOTAL_FILE = 1000

    download_list = []
    for num in range(TOTAL_FILE):
      target_path = f'/bucket{num}/target{num}'
      local_path = f'/path/to/local{num}'
      download_list.append((target_path, local_path))

    queue = multiprocessing.Queue()

    def MockDownloadFile(target_path, local_path, overwrite=False):
      del overwrite
      queue.put((target_path, local_path))
      return True

    self.mock_cloud_storage.DownloadFile = MockDownloadFile

    pd = gcs_utils.ParallelDownloader(process_number=3)
    return_list = list(pd.Download(download_list))
    call_list = []
    # According to the Python document, the function queue.empty() is not
    # reliable. It may return True even when the queue is not empty here.
    # Therefore, we try to get TOTAL_FILE times from the queue.
    for unused_num in range(TOTAL_FILE):
      call_list.append(queue.get())

    # imap_unordered may cause different order.
    self.assertCountEqual(download_list, return_list)
    self.assertCountEqual(download_list, call_list)


if __name__ == '__main__':
  logging.basicConfig(level=logging.DEBUG)
  unittest.main()
