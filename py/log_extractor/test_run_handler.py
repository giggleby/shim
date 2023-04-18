# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum
import re
from typing import Optional, Tuple

import cros.factory.log_extractor.record as record_module


class AbstractTestRunHandler(abc.ABC):
  """A base class for parsing the test run record according to the its type."""

  def Parse(self, record: record_module.IRecord):
    if isinstance(record, record_module.SystemLogRecord):
      return self.ParseSystemLogRecord(record)
    if isinstance(record, record_module.TestlogRecord):
      return self.ParseTestlogRecord(record)
    return self.ParseGenericRecord(record)

  @abc.abstractmethod
  def ParseGenericRecord(self, record: record_module.IRecord):
    """Default handler for record."""
    raise NotImplementedError

  @abc.abstractmethod
  def ParseSystemLogRecord(self, record: record_module.SystemLogRecord):
    raise NotImplementedError

  @abc.abstractmethod
  def ParseTestlogRecord(self, record: record_module.TestlogRecord):
    raise NotImplementedError


class TestRunStatus(enum.Enum):
  UNKNOWN = 'UNKNOWN'
  STARTED = 'STARTED'
  RUNNING = 'RUNNING'
  COMPLETED = 'COMPLETED'

# Example output of message:
#   goofy[1845]: Test generic:SMT.Update (123-456) starting
#   goofy[1845]: Test generic:SMT.Update (123-456) completed: FAILED (reason)
_VAR_LOG_MSG_TEST_RUN_REGEX = (
    r'goofy\[\d+\]: Test (?P<testName>\S+) \((?P<testRunId>\S+)\) '
    r'(\S+: )?(?P<status>\S+)')


# TODO(phoebewang): Unify the status in StationTestRun and /var/log/messages
class StatusHandler(AbstractTestRunHandler):
  """Gets the test run status from the record.

  If record doesn't contain the test run status, returns
  `TestRunStatus.UNKNOWN`, else parses and returns the TestRunStatus.
  """

  def ParseGenericRecord(self, record: record_module.IRecord) -> TestRunStatus:
    return TestRunStatus.UNKNOWN

  def ParseSystemLogRecord(
      self, record: record_module.SystemLogRecord) -> TestRunStatus:
    match = re.search(_VAR_LOG_MSG_TEST_RUN_REGEX, record['message'])
    if match:
      status = match.group('status').strip()
      if status in ('starting', 'resuming'):
        return TestRunStatus.STARTED
      if status in ('FAILED', 'PASSED'):
        return TestRunStatus.COMPLETED

    return TestRunStatus.UNKNOWN

  def ParseTestlogRecord(self,
                         record: record_module.TestlogRecord) -> TestRunStatus:
    if 'status' not in record:
      return TestRunStatus.UNKNOWN

    status = record['status']
    if status == 'STARTING':
      return TestRunStatus.STARTED
    if status in ('FAIL', 'PASS'):
      return TestRunStatus.COMPLETED
    if status == 'RUNNING':
      return TestRunStatus.RUNNING

    return TestRunStatus.UNKNOWN

class TestRunNameHandler(AbstractTestRunHandler):
  """Gets the test name and test run id from the record.

  This information helps user identify which test is running.
  """

  def ParseGenericRecord(
      self,
      record: record_module.IRecord) -> Tuple[Optional[str], Optional[str]]:
    return None, None

  def ParseSystemLogRecord(
      self, record: record_module.SystemLogRecord
  ) -> Tuple[Optional[str], Optional[str]]:
    match = re.search(_VAR_LOG_MSG_TEST_RUN_REGEX, record['message'])
    if match:
      test_name = match.group('testName').strip()
      test_run_id = match.group('testRunId').strip()
      return test_name, test_run_id
    return None, None

  def ParseTestlogRecord(
      self, record: record_module.TestlogRecord
  ) -> Tuple[Optional[str], Optional[str]]:
    test_name = record['testName'] if 'testName' in record else None
    test_run_id = record['testRunId'] if 'testRunId' in record else None

    return test_name, test_run_id
