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


class SystemLogRecordTest(unittest.TestCase):

  def testToStr(self):
    message_record = record_module.SystemLogRecord.FromJSON(
        '{"filePath": "testlog.py", "lineNumber": 230, "logLevel": "WARNING", '
        '"time": 1656340134.0011251, "message": "factory msg"}')
    self.assertEqual(
        str(message_record),
        '[WARNING] 2022-06-27T14:28:54.001125Z testlog.py:230 factory msg')


class TestlogRecordTest(unittest.TestCase):

  def testGetTime(self):
    record_has_start_time = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23,'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(record_has_start_time.GetTime(), 1.22)

    record_has_end_time = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23,'
        '"endTime": 1.24, "testType": "mock"}', check_valid=False)
    self.assertEqual(record_has_end_time.GetTime(), 1.24)

  def testToStr(self):
    message_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.message", "filePath": "testlog.py", '
        '"lineNumber": 230, "logLevel": "ERROR", "time": 1656340134.0011251,'
        '"message": "err message"}', check_valid=False)
    self.assertEqual(
        str(message_record),
        '[ERROR] 2022-06-27T14:28:54.001125Z testlog.py:230 err message')

    testrun_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1656340134.0011251,'
        '"testName": "generic_main:Idle", "testType" : "idle", '
        '"testRunId": "abc-123", "status": "RUNNING", "startTime": '
        '1656340133.123}', check_valid=False)
    self.assertEqual(
        str(testrun_record),
        '[INFO] 2022-06-27T14:28:53.123000Z generic_main:Idle-abc-123 RUNNING')

    failed_testrun_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1656340134.0011251,'
        '"testName": "generic_main:Idle", "testType" : "idle", '
        '"testRunId": "abc-123", "status": "FAIL", "startTime": '
        '1656340133.123, "failures": [{"code": "GoofyErrorMsg", '
        '"details": "TestFailure"}]}', check_valid=False)
    self.assertEqual(
        str(failed_testrun_record),
        '[INFO] 2022-06-27T14:28:53.123000Z generic_main:Idle-abc-123 FAIL\n'
        '  Failed reason: TestFailure')

    shutdown_testrun_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1656340134.0011251,'
        '"testName": "generic_main:Reboot", "testRunId": "abc-123",'
        '"status": "STARTING", "startTime": 1656340133.123, '
        '"testType": "shutdown", "parameters": {"tag": {"data": '
        '[{"textValue": "post-shutdown"}]}}}', check_valid=False)
    self.assertEqual(
        str(shutdown_testrun_record),
        '[INFO] 2022-06-27T14:28:53.123000Z generic_main:Reboot-abc-123 '
        'STARTING (post-shutdown)')

    status_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.status", "time": 1656340134.0011251, '
        '"filePath": "testlog.py"}', check_valid=False)
    self.assertEqual(
        str(status_record), '[INFO] 2022-06-27T14:28:54.001125Z testlog.py')

    init_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.init", "time": 1656340134.0011251, "count": 1,'
        '"success": true}', check_valid=False)
    self.assertEqual(
        str(init_record),
        '[INFO] 2022-06-27T14:28:54.001125Z Goofy init count: 1, success: True')


if __name__ == '__main__':
  unittest.main()
