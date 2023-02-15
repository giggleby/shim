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


class VarLogMessageRecordTest(unittest.TestCase):

  def testGetTestRunStatus(self):
    testrun_starting = record_module.VarLogMessageRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) starting"}', check_valid=False)
    self.assertEqual(testrun_starting.GetTestRunStatus(),
                     record_module.TestRunStatus.STARTED)

    testrun_passed = record_module.VarLogMessageRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) completed: PASSED"}', check_valid=False)
    self.assertEqual(testrun_passed.GetTestRunStatus(),
                     record_module.TestRunStatus.COMPLETED)

    testrun_failed = record_module.VarLogMessageRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) completed: FAILED (reason)"}', check_valid=False)
    self.assertEqual(testrun_failed.GetTestRunStatus(),
                     record_module.TestRunStatus.COMPLETED)

    testrun_running = record_module.VarLogMessageRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) resuming"}', check_valid=False)
    self.assertEqual(testrun_running.GetTestRunStatus(),
                     record_module.TestRunStatus.RUNNING)

    testrun_unknown = record_module.VarLogMessageRecord.FromJSON(
        '{"message": "kernel: [   13.644255] usb 4-2: new SuperSpeed USB", '
        '"time": 1.23}', check_valid=False)
    self.assertEqual(testrun_unknown.GetTestRunStatus(),
                     record_module.TestRunStatus.UNKNOWN)

  def testGetTestRunName(self):
    testrun_starting = record_module.VarLogMessageRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) starting"}', check_valid=False)
    self.assertEqual(testrun_starting.GetTestRunName(),
                     'generic:SMT.Update-f9c665ff-55d0')


class TestlogRecordTest(unittest.TestCase):

  def testGetShutdownStatusAndGetTime(self):
    pre_shutdown_start = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "pre-shutdown"}]}},'
        '"status": "STARTING", "startTime": 1.22}', check_valid=False)
    self.assertEqual(pre_shutdown_start.GetTestRunStatus(),
                     record_module.TestRunStatus.STARTED)
    self.assertEqual(pre_shutdown_start.GetTime(), 1.22)

    pre_shutdown_end = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "pre-shutdown"}]}},'
        '"status": "FAIL", "endTime": 1.24}', check_valid=False)
    self.assertEqual(pre_shutdown_end.GetTestRunStatus(),
                     record_module.TestRunStatus.RUNNING)
    self.assertEqual(pre_shutdown_end.GetTime(), 1.24)

    post_shutdown_start = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "post-shutdown"}]}},'
        '"status": "STARTING", "startTime": 1.22}', check_valid=False)
    self.assertEqual(post_shutdown_start.GetTestRunStatus(),
                     record_module.TestRunStatus.RUNNING)
    self.assertEqual(post_shutdown_start.GetTime(), 1.22)

    post_shutdown_end = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "post-shutdown"}]}},'
        '"status": "PASS", "endTime": 1.24}', check_valid=False)
    self.assertEqual(post_shutdown_end.GetTestRunStatus(),
                     record_module.TestRunStatus.COMPLETED)
    self.assertEqual(post_shutdown_end.GetTime(), 1.24)

  def testGetTestRunStatusAndGetTime(self):
    testrun_starting = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "STARTING",'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(testrun_starting.GetTestRunStatus(),
                     record_module.TestRunStatus.STARTED)
    self.assertEqual(testrun_starting.GetTime(), 1.22)

    testrun_passed = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "PASS",'
        '"endTime": 1.24, "testType": "mock"}', check_valid=False)
    self.assertEqual(testrun_passed.GetTestRunStatus(),
                     record_module.TestRunStatus.COMPLETED)
    self.assertEqual(testrun_passed.GetTime(), 1.24)

    testrun_failed = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "FAIL",'
        '"endTime": 1.24, "testType": "mock"}', check_valid=False)
    self.assertEqual(testrun_failed.GetTestRunStatus(),
                     record_module.TestRunStatus.COMPLETED)
    self.assertEqual(testrun_passed.GetTime(), 1.24)

    testrun_running = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "RUNNING",'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(testrun_running.GetTestRunStatus(),
                     record_module.TestRunStatus.RUNNING)
    self.assertEqual(testrun_running.GetTime(), 1.22)

    testrun_unknown = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "UNKNOWN",'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(testrun_unknown.GetTestRunStatus(),
                     record_module.TestRunStatus.UNKNOWN)
    self.assertEqual(testrun_unknown.GetTime(), 1.22)

  def testGetTestRunName(self):
    testrun_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "testName": "generic_main:Idle",'
        '"testRunId": "abc-123", "time": 1656340134.0011251,'
        '"status": "UNKNOWN", "startTime": 1656340133.123}', check_valid=False)
    self.assertEqual(testrun_record.GetTestRunName(),
                     'generic_main:Idle-abc-123')

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
        '"testName": "generic_main:Idle", "testRunId": "abc-123",'
        '"status": "RUNNING", "startTime": 1656340133.123}', check_valid=False)
    self.assertEqual(
        str(testrun_record),
        '[INFO] 2022-06-27T14:28:53.123000Z generic_main:Idle-abc-123 RUNNING')

    status_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.status", "time": 1656340134.0011251, '
        '"filePath": "testlog.py", "parameters": {"status": {'
        '"type": "measurement"}}}', check_valid=False)
    self.assertEqual(
        str(status_record), '[INFO] 2022-06-27T14:28:54.001125Z testlog.py\n'
        'parameters:\n{\n  "status": {\n    "type": "measurement"\n  }\n}')

    init_record = record_module.TestlogRecord.FromJSON(
        '{"type": "station.init", "time": 1656340134.0011251, "count": 1,'
        '"success": true}', check_valid=False)
    self.assertEqual(
        str(init_record),
        '[INFO] 2022-06-27T14:28:54.001125Z Goofy init count: 1, success: True')


if __name__ == '__main__':
  unittest.main()
