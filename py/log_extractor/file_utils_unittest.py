#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for log_extractor.file_utils."""

import os
import unittest

from cros.factory.log_extractor.file_utils import LogExtractorFileReader
from cros.factory.log_extractor.record import LogExtractorRecord
from cros.factory.utils import file_utils


class LogExtractorFileReaderTest(unittest.TestCase):

  _RECORD = [
      '{"time": 1.23, "message": "Test LogExtractorFileReader message 1"}',
      '{"message": "Test LogExtractorFileReader invalid message"}',
      '{"time": 2.34, "message": "Test LogExtractorFileReader message 2"}',
  ]

  def testReadRecord(self):
    with file_utils.TempDirectory() as temp_dir:
      testlog_path = os.path.join(temp_dir, 'test_filter_record.json')
      file_utils.WriteFile(testlog_path, '\n'.join(self._RECORD))

      reader = LogExtractorFileReader(testlog_path)
      self.assertEqual(
          LogExtractorRecord.Load(self._RECORD[0]), reader.GetCurRecord())
      # Should keep reading since the second record is invalid.
      self.assertEqual(
          LogExtractorRecord.Load(self._RECORD[2]),
          reader.ReadNextValidRecord())
      self.assertEqual(None, reader.ReadNextValidRecord())


if __name__ == '__main__':
  unittest.main()
