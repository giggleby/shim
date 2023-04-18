#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for log_extractor.record."""

import unittest

from cros.factory.log_extractor import record as record_module
from cros.factory.log_extractor import test_run_handler as handler


class StatusHandlerTest(unittest.TestCase):

  def testParseGenericRecord(self):
    status_handler = handler.StatusHandler()
    no_status = record_module.FactoryRecord.FromJSON('{"time": 1.23}',
                                                     check_valid=False)
    self.assertEqual(
        status_handler.Parse(no_status), handler.TestRunStatus.UNKNOWN)

  def testParseSystemLogRecord(self):
    status_handler = handler.StatusHandler()
    testrun_starting = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) starting"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_starting), handler.TestRunStatus.STARTED)

    testrun_passed = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) completed: PASSED"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_passed), handler.TestRunStatus.COMPLETED)

    testrun_failed = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) completed: FAILED (reason)"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_failed), handler.TestRunStatus.COMPLETED)

    testrun_running = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) resuming"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_running), handler.TestRunStatus.STARTED)

    testrun_unknown = record_module.SystemLogRecord.FromJSON(
        '{"message": "kernel: [   13.644255] usb 4-2: new SuperSpeed USB"}',
        check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_unknown), handler.TestRunStatus.UNKNOWN)

  def testParseTestlogRecord(self):
    status_handler = handler.StatusHandler()
    testrun_starting = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "STARTING",'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_starting), handler.TestRunStatus.STARTED)

    testrun_passed = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "PASS",'
        '"endTime": 1.24, "testType": "mock"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_passed), handler.TestRunStatus.COMPLETED)

    testrun_failed = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "FAIL",'
        '"endTime": 1.24, "testType": "mock"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_failed), handler.TestRunStatus.COMPLETED)

    testrun_running = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "RUNNING",'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_running), handler.TestRunStatus.RUNNING)

    testrun_unknown = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "status": "UNKNOWN",'
        '"startTime": 1.22, "testType": "mock"}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(testrun_unknown), handler.TestRunStatus.UNKNOWN)

class TestRunNameHandlerTest(unittest.TestCase):

  def testParseSystemLogRecord(self):
    has_test_info = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) starting"}', check_valid=False)
    test_name, test_run_id = handler.TestRunNameHandler().Parse(has_test_info)
    self.assertEqual(test_name, 'generic:SMT.Update')
    self.assertEqual(test_run_id, 'f9c665ff-55d0')

    no_test_info = record_module.SystemLogRecord.FromJSON(
        '{"message": "kernel: [   13.644255] usb 4-2: new SuperSpeed USB"}',
        check_valid=False)
    test_name, test_run_id = handler.TestRunNameHandler().Parse(no_test_info)
    self.assertEqual(test_name, None)
    self.assertEqual(test_run_id, None)

  def testParseTestlogRecord(self):
    test_run = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "testName": "generic_main:Idle",'
        '"testRunId": "abc-123", "time": 1656340134.0011251,'
        '"startTime": 1656340133.123}', check_valid=False)
    test_name, test_run_id = handler.TestRunNameHandler().Parse(test_run)
    self.assertEqual(test_name, 'generic_main:Idle')
    self.assertEqual(test_run_id, 'abc-123')

    message = record_module.TestlogRecord.FromJSON(
        '{"type": "station.message", "testRunId": "18fb0d2a-6d72", '
        '"time": 1656340134.0011251}', check_valid=False)
    test_name, test_run_id = handler.TestRunNameHandler().Parse(message)
    self.assertEqual(test_name, None)
    self.assertEqual(test_run_id, '18fb0d2a-6d72')


if __name__ == '__main__':
  unittest.main()
