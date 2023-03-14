#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for log_extractor.file_utils."""

import os
import textwrap
import unittest

import cros.factory.log_extractor.file_utils as log_extractor_file_utils
import cros.factory.log_extractor.record as record_module
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

      loader = record_module.FactoryRecord.FromJSON
      reader = log_extractor_file_utils.LogExtractorFileReader(
          testlog_path, loader)
      self.assertEqual(loader(self._RECORD[0]), next(reader))
      self.assertEqual(loader(self._RECORD[0]), reader.GetCurRecord())
      # Should keep reading since the second record is invalid.
      self.assertEqual(loader(self._RECORD[2]), next(reader))
      self.assertEqual(loader(self._RECORD[2]), reader.GetCurRecord())
      # Read till the end of file.
      with self.assertRaises(StopIteration):
        next(reader)
      self.assertEqual(None, reader.GetCurRecord())


class ExtractAndWriteRecordByTestRunTest(unittest.TestCase):

  def ReadExtractedLog(self, test_name, test_run_id, root, output_name):
    return file_utils.ReadFile(
        log_extractor_file_utils.GetExtractedLogOutputPath(
            test_name, test_run_id, root, output_name))

  # TODO(phoebewang): Add reboot logs in /var/log/message.
  def testWriteVarLogMessage(self):
    VAR_LOG_MESSAGE_JSON = textwrap.dedent("""\
      {"filePath": "messages", "lineNumber": 3840, "logLevel": "ERROR", "message": "chapsd[1288]: InitStage2 failed because SRK is not ready", "time": 1675736100.571854}
      {"filePath": "messages", "lineNumber": 3841, "logLevel": "WARNING", "message": "cryptohomed[2172]: GetTpmTokenSlotForPath: Path not found.", "time": 1675736100.572054}
      {"filePath": "messages", "lineNumber": 3842, "logLevel": "INFO", "message": "goofy[2051]: Test generic:SMT.ECWPPinHigh (042a5e4f-3c08) starting", "time": 1675736100.663978}
      {"filePath": "messages", "lineNumber": 3843, "logLevel": "WARNING", "message": "kernel: [    9.412059] x86/PAT: flashrom:4034 conflicting memory types", "time": 1675736101.305057}
      {"filePath": "messages", "lineNumber": 3844, "logLevel": "INFO", "message": "goofy[2051]: Test generic:SMT.ECWPPinHigh (042a5e4f-3c08) completed: PASSED", "time": 1675736101.851173}
      {"filePath": "messages", "lineNumber": 3845, "logLevel": "INFO", "message": "goofy[2051]: Test generic:SMT.Barrier (042a5e69-cd9a) starting", "time": 1675736101.9592}
      {"filePath": "messages", "lineNumber": 3846, "logLevel": "INFO", "message": "goofy[2051]: Test generic:SMT.Barrier (042a5e69-cd9a) resuming", "time": 1675736102.147357}
      {"filePath": "messages", "lineNumber": 3847, "logLevel": "INFO", "message": "goofy[2051]: Test generic:SMT.Barrier (042a5e69-cd9a) completed: FAILED", "time": 1675736102.347357}
      {"filePath": "messages", "lineNumber": 3848, "logLevel": "INFO", "message": "kernel: [    9.412065] x86/PAT: memtype_reserve failed", "time": 1675736102.305098}
    """)
    TEST_NAME_1 = 'generic:SMT.ECWPPinHigh'
    TEST_RUN_ID_1 = '042a5e4f-3c08'
    TEST_RUN_EXPECTED_OUTPUT_1 = textwrap.dedent("""\
      [INFO] 2023-02-07T02:15:00.663978Z messages:3842 goofy[2051]: Test generic:SMT.ECWPPinHigh (042a5e4f-3c08) starting
      [WARNING] 2023-02-07T02:15:01.305057Z messages:3843 kernel: [    9.412059] x86/PAT: flashrom:4034 conflicting memory types
      [INFO] 2023-02-07T02:15:01.851173Z messages:3844 goofy[2051]: Test generic:SMT.ECWPPinHigh (042a5e4f-3c08) completed: PASSED
    """)

    TEST_NAME_2 = 'generic:SMT.Barrier'
    TEST_RUN_ID_2 = '042a5e69-cd9a'
    TEST_RUN_EXPECTED_OUTPUT_2 = textwrap.dedent("""\
      [INFO] 2023-02-07T02:15:01.959200Z messages:3845 goofy[2051]: Test generic:SMT.Barrier (042a5e69-cd9a) starting
      [INFO] 2023-02-07T02:15:02.147357Z messages:3846 goofy[2051]: Test generic:SMT.Barrier (042a5e69-cd9a) resuming
      [INFO] 2023-02-07T02:15:02.347357Z messages:3847 goofy[2051]: Test generic:SMT.Barrier (042a5e69-cd9a) completed: FAILED
    """)

    OUTPUT_NAME = 'message'
    with file_utils.TempDirectory() as temp_dir:
      # Setup environment
      input_path = os.path.join(temp_dir, OUTPUT_NAME)
      file_utils.WriteFile(input_path, VAR_LOG_MESSAGE_JSON)

      reader = log_extractor_file_utils.LogExtractorFileReader(
          input_path, record_module.SystemLogRecord.FromJSON, False)
      log_extractor_file_utils.ExtractAndWriteRecordByTestRun(
          reader, temp_dir, OUTPUT_NAME)
      self.assertEqual(
          TEST_RUN_EXPECTED_OUTPUT_1,
          self.ReadExtractedLog(TEST_NAME_1, TEST_RUN_ID_1, temp_dir,
                                OUTPUT_NAME))

      self.assertEqual(
          TEST_RUN_EXPECTED_OUTPUT_2,
          self.ReadExtractedLog(TEST_NAME_2, TEST_RUN_ID_2, temp_dir,
                                OUTPUT_NAME))

  def testWriteTestlog(self):
    FACTORY_TEST_LOG = textwrap.dedent("""\
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599400.133407, "message": "err message"}
      {"startTime": 1673599400.633407, "status": "STARTING", "testName": "generic:Test_1", "testRunId": "abc", "time": 1673599400.682136, "type": "station.test_run", "testType": "mock"}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "ERROR", "time": 1673599410.122136, "message": "info message"}
      {"endTime": 1673599411.0909407, "status": "FAIL", "testName": "generic:Test_1", "testRunId": "abc", "time": 1673599400.682136, "type": "station.test_run", "testType": "mock"}
      {"startTime": 1673599497.0769532, "status": "STARTING", "testName": "generic:Test_2", "testRunId": "def", "time": 1673599497.132981, "type": "station.test_run", "testType": "shutdown", "parameters": {"tag": {"data": [{"textValue": "pre-shutdown"}]}}}
      {"endTime": 1673599498.1234567, "status": "FAIL", "testName": "generic:Test_2", "testRunId": "def", "time": 1673599497.132981, "type": "station.test_run", "testType": "shutdown", "parameters": {"tag": {"data": [{"textValue": "pre-shutdown"}]}}}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599500.5086327, "message": "device rebooting"}
      {"startTime": 1673599499.4567321, "status": "STARTING", "testName": "generic:Test_2", "testRunId": "def", "time": 1673599497.132981, "type": "station.test_run", "testType": "shutdown", "parameters": {"tag": {"data": [{"textValue": "post-shutdown"}]}}}
      {"endTime": 1673599500.5086327, "status": "PASS", "testName": "generic:Test_2", "testRunId": "def", "time": 1673599497.132981, "type": "station.test_run", "testType": "shutdown", "parameters": {"tag": {"data": [{"textValue": "post-shutdown"}]}}}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599500.5086327, "message": "info message"}
    """)
    TEST_NAME_1 = 'generic:Test_1'
    TEST_RUN_ID_1 = 'abc'
    TEST_RUN_EXPECTED_OUTPUT_1 = textwrap.dedent("""\
      [INFO] 2023-01-13T08:43:20.633407Z generic:Test_1-abc STARTING
      [ERROR] 2023-01-13T08:43:30.122136Z testlog.py:230 info message
      [INFO] 2023-01-13T08:43:31.090941Z generic:Test_1-abc FAIL
    """)

    TEST_NAME_2 = 'generic:Test_2'
    TEST_RUN_ID_2 = 'def'
    TEST_RUN_EXPECTED_OUTPUT_2 = textwrap.dedent("""\
      [INFO] 2023-01-13T08:44:57.076953Z generic:Test_2-def STARTING
      parameters:
      {
        "tag": {
          "data": [
            {
              "textValue": "pre-shutdown"
            }
          ]
        }
      }
      [INFO] 2023-01-13T08:44:58.123457Z generic:Test_2-def FAIL
      parameters:
      {
        "tag": {
          "data": [
            {
              "textValue": "pre-shutdown"
            }
          ]
        }
      }
      [INFO] 2023-01-13T08:45:00.508633Z testlog.py:230 device rebooting
      [INFO] 2023-01-13T08:44:59.456732Z generic:Test_2-def STARTING
      parameters:
      {
        "tag": {
          "data": [
            {
              "textValue": "post-shutdown"
            }
          ]
        }
      }
      [INFO] 2023-01-13T08:45:00.508633Z generic:Test_2-def PASS
      parameters:
      {
        "tag": {
          "data": [
            {
              "textValue": "post-shutdown"
            }
          ]
        }
      }
    """)

    OUTPUT_NAME = 'testlog'
    with file_utils.TempDirectory() as temp_dir:
      # Setup environment
      input_path = os.path.join(temp_dir, OUTPUT_NAME)
      file_utils.WriteFile(input_path, FACTORY_TEST_LOG)

      reader = log_extractor_file_utils.LogExtractorFileReader(
          input_path, record_module.TestlogRecord.FromJSON, False)
      log_extractor_file_utils.ExtractAndWriteRecordByTestRun(
          reader, temp_dir, OUTPUT_NAME)
      self.assertEqual(
          TEST_RUN_EXPECTED_OUTPUT_1,
          self.ReadExtractedLog(TEST_NAME_1, TEST_RUN_ID_1, temp_dir,
                                OUTPUT_NAME))

      self.assertEqual(
          TEST_RUN_EXPECTED_OUTPUT_2,
          self.ReadExtractedLog(TEST_NAME_2, TEST_RUN_ID_2, temp_dir,
                                OUTPUT_NAME))

  def testWriteTestlogParallelTest(self):
    PARALLEL_TEST_LOG = textwrap.dedent("""\
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599400.133407, "message": "err message"}
      {"startTime": 1673599400.633407, "status": "STARTING", "testName": "generic:Test_1", "testRunId": "abc", "time": 1673599400.682136, "type": "station.test_run", "testType": "mock"}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "ERROR", "time": 1673599410.122136, "message": "only test1 is running"}
      {"startTime": 1673599497.0769532, "status": "STARTING", "testName": "generic:Test_2", "testRunId": "def", "time": 1673599497.132981, "type": "station.test_run", "testType": "mock"}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599500.5086327, "message": "test1 and test2 are running"}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599502.6081234, "message": "test1 and test2 are running"}
      {"endTime": 1673599601.1234567, "status": "FAIL", "testName": "generic:Test_2", "testRunId": "def", "time": 1673599600.132981, "type": "station.test_run", "testType": "mock"}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599602.5086327, "message": "only test1 is running"}
      {"endTime": 1673599610.6086327, "status": "PASS", "testName": "generic:Test_1", "testRunId": "abc", "time": 1673599608.123457, "type": "station.test_run", "testType": "mock"}
      {"type": "station.message", "filePath": "testlog.py", "lineNumber": 230, "logLevel": "INFO", "time": 1673599610.5086327, "message": "no test is running"}
    """)
    TEST_NAME_1 = 'generic:Test_1'
    TEST_RUN_ID_1 = 'abc'
    TEST_RUN_EXPECTED_OUTPUT_1 = textwrap.dedent("""\
      [INFO] 2023-01-13T08:43:20.633407Z generic:Test_1-abc STARTING
      [ERROR] 2023-01-13T08:43:30.122136Z testlog.py:230 only test1 is running
      [INFO] 2023-01-13T08:45:00.508633Z testlog.py:230 test1 and test2 are running
      [INFO] 2023-01-13T08:45:02.608123Z testlog.py:230 test1 and test2 are running
      [INFO] 2023-01-13T08:46:42.508633Z testlog.py:230 only test1 is running
      [INFO] 2023-01-13T08:46:50.608633Z generic:Test_1-abc PASS
    """)

    TEST_NAME_2 = 'generic:Test_2'
    TEST_RUN_ID_2 = 'def'
    TEST_RUN_EXPECTED_OUTPUT_2 = textwrap.dedent("""\
      [INFO] 2023-01-13T08:44:57.076953Z generic:Test_2-def STARTING
      [INFO] 2023-01-13T08:45:00.508633Z testlog.py:230 test1 and test2 are running
      [INFO] 2023-01-13T08:45:02.608123Z testlog.py:230 test1 and test2 are running
      [INFO] 2023-01-13T08:46:41.123457Z generic:Test_2-def FAIL
    """)

    OUTPUT_NAME = 'parallel_testlog'
    with file_utils.TempDirectory() as temp_dir:
      # Setup environment
      input_path = os.path.join(temp_dir, OUTPUT_NAME)
      file_utils.WriteFile(input_path, PARALLEL_TEST_LOG)

      reader = log_extractor_file_utils.LogExtractorFileReader(
          input_path, record_module.TestlogRecord.FromJSON, False)
      log_extractor_file_utils.ExtractAndWriteRecordByTestRun(
          reader, temp_dir, OUTPUT_NAME)
      self.assertEqual(
          TEST_RUN_EXPECTED_OUTPUT_1,
          self.ReadExtractedLog(TEST_NAME_1, TEST_RUN_ID_1, temp_dir,
                                OUTPUT_NAME))

      self.assertEqual(
          TEST_RUN_EXPECTED_OUTPUT_2,
          self.ReadExtractedLog(TEST_NAME_2, TEST_RUN_ID_2, temp_dir,
                                OUTPUT_NAME))


if __name__ == '__main__':
  unittest.main()
