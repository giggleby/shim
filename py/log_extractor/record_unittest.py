#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for log_extractor.record."""

import unittest

from cros.factory.log_extractor import record as record_module
from cros.factory.utils.schema import SchemaException


class FactoryRecordTest(unittest.TestCase):

  def testHasTimeField(self):
    json_has_time = '{"time": 1.23}'
    record = record_module.FactoryRecord.FromJSON(json_has_time)
    self.assertEqual(record.GetTime(), 1.23)

  def testNoTimeField(self):
    json_no_time = '{"filePath": "/test/file/path"}'
    with self.assertRaises(SchemaException):
      record_module.FactoryRecord.FromJSON(json_no_time)

  def testComparator(self):
    record1 = record_module.FactoryRecord.FromJSON('{"time": 1.23}')
    record2 = record_module.FactoryRecord.FromJSON('{"time": 2.34}')
    self.assertTrue(record1 < record2)

if __name__ == '__main__':
  unittest.main()
