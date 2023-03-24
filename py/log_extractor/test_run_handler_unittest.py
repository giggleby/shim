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
        status_handler.Parse(testrun_running), handler.TestRunStatus.RUNNING)

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


class ShutdownHandlerTest(unittest.TestCase):

  def testParseTestlogRecord(self):
    status_handler = handler.ShutdownStatusHandler()
    pre_shutdown_start = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "pre-shutdown"}]}},'
        '"status": "STARTING", "startTime": 1.22}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(pre_shutdown_start), handler.TestRunStatus.STARTED)

    pre_shutdown_end = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "pre-shutdown"}]}},'
        '"status": "FAIL", "endTime": 1.24}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(pre_shutdown_end), handler.TestRunStatus.RUNNING)

    post_shutdown_start = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "post-shutdown"}]}},'
        '"status": "STARTING", "startTime": 1.22}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(post_shutdown_start),
        handler.TestRunStatus.RUNNING)

    post_shutdown_end = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"parameters": {"tag": {"data": [{"textValue": "post-shutdown"}]}},'
        '"status": "PASS", "endTime": 1.24}', check_valid=False)
    self.assertEqual(
        status_handler.Parse(post_shutdown_end),
        handler.TestRunStatus.COMPLETED)


class TestTypeHandlerTest(unittest.TestCase):

  def testParseGenericRecord(self):
    test_type_handler = handler.TestTypeHandler()
    no_test_type = record_module.FactoryRecord.FromJSON('{"time": 1.23}',
                                                        check_valid=False)
    self.assertEqual(test_type_handler.Parse(no_test_type), None)

  def testParseSystemLogRecord(self):
    test_type_handler = handler.TestTypeHandler()
    no_test_type = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) starting"}', check_valid=False)
    self.assertEqual(test_type_handler.Parse(no_test_type), None)

  def testParseTestlogRecord(self):
    test_type_handler = handler.TestTypeHandler()
    test_type = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "mock_test",'
        '"startTime": 1.22}', check_valid=False)
    self.assertEqual(test_type_handler.Parse(test_type), 'mock_test')

    no_test_type = record_module.TestlogRecord.FromJSON(
        '{"type": "station.message", "time": 1.23}', check_valid=False)
    self.assertEqual(test_type_handler.Parse(no_test_type), None)


class DetermineStatusHandlerTypeTest(unittest.TestCase):

  def testParseGenericRecord(self):
    no_status = record_module.FactoryRecord.FromJSON('{"time": 1.23}',
                                                     check_valid=False)
    status_handler_type = handler.DetermineStatusHandlerType(no_status)
    self.assertEqual(status_handler_type, handler.StatusHandler)

  def testParseSystemLogRecord(self):
    starting_record = record_module.SystemLogRecord.FromJSON(
        '{"message": "goofy[1845]: Test generic:SMT.Update '
        '(f9c665ff-55d0) starting"}', check_valid=False)
    status_handler_type = handler.DetermineStatusHandlerType(starting_record)
    self.assertEqual(status_handler_type, handler.StatusHandler)

  def testParseTestlogRecord(self):
    shutdown_test_type = record_module.TestlogRecord.FromJSON(
        '{"type": "station.test_run", "time": 1.23, "testType": "shutdown",'
        '"startTime": 1.22}', check_valid=False)
    shutdown_status_handler_type = handler.DetermineStatusHandlerType(
        shutdown_test_type)
    self.assertEqual(shutdown_status_handler_type,
                     handler.ShutdownStatusHandler)

    non_shutdown_test_type = record_module.TestlogRecord.FromJSON(
        '{"type": "station.message", "time": 1.23}', check_valid=False)
    status_handler_type = handler.DetermineStatusHandlerType(
        non_shutdown_test_type)
    self.assertEqual(status_handler_type, handler.StatusHandler)


if __name__ == '__main__':
  unittest.main()
