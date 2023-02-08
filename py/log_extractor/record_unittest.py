#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for log_extractor.record."""

import unittest

from cros.factory.log_extractor.record import InvalidRecord
from cros.factory.log_extractor.record import LogExtractorRecord


class LogExtractorRecordTest(unittest.TestCase):

  def testHasTimeField(self):
    json_has_time = '{"filePath": "/test/file/path", "time": 1.23}'
    LogExtractorRecord.Load(json_has_time)

  def testNoTimeField(self):
    json_no_time = '{"filePath": "/test/file/path"}'
    with self.assertRaises(InvalidRecord):
      LogExtractorRecord.Load(json_no_time)

  def testNonNumericTime(self):
    json_non_numeric_time = '{"time": "1.23"}'
    with self.assertRaises(InvalidRecord):
      LogExtractorRecord.Load(json_non_numeric_time)

  def testComparator(self):
    record1 = LogExtractorRecord.Load('{"time": 1.23}')
    record2 = LogExtractorRecord.Load('{"time": 2.34}')
    self.assertTrue(record1 < record2)

  def testTestRunEventType(self):
    record = LogExtractorRecord.Load(
        '{"type": "station.test_run", "time": 1.23, "endTime": 1.24}')
    self.assertEqual(record.GetTime(), 1.24)


if __name__ == '__main__':
  unittest.main()
