# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum
import logging
import re
from typing import Optional, Type

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


# TODO(phoebewang): Add TestRunNameHandler to parse test run name.
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
      if status == 'starting':
        return TestRunStatus.STARTED
      if status == 'resuming':
        return TestRunStatus.RUNNING
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


class ShutdownStatus(enum.Enum):
  """The possible shutdown tag name is defined in py/goofy/invocation.py."""
  PRE_SHUTDOWN = 'pre-shutdown'
  POST_SHUTDOWN = 'post-shutdown'


class ShutdownStatusHandler(StatusHandler):
  """Specialized handler for parsing shutdown event."""

  def ParseTestlogRecord(self,
                         record: record_module.TestlogRecord) -> TestRunStatus:
    """Modify test status according to shutdown state.

    Most of the tests start with `status` STARTING and end with `status` PASS
    FAIL. However, for shutdown test, the test status looks like:
      STARTING (pre-shutdown) -> FAIL (pre-shutdown) -> (DUT reboots) ->
      STARTING (post-shutdown)-> PASS/FAIL (post-shutdown)
    which contains two starting (STARTING) and two ending (PASS/FAIL) events.
    Change the second and third test events to RUNNING so that it is easier to
    understand the test run status.
    """
    try:
      shutdown_status = ShutdownStatus(
          record['parameters']['tag']['data'][0]['textValue'])
    except Exception as err:
      logging.warning('Failed to get shutdown status. (reason: %r).', err)
      return super().ParseTestlogRecord(record)

    status = record['status']
    # Change `FAIL (pre-shutdown)` and `STARTING (post-shutdown)` to RUNNING.
    if ((status == 'FAIL' and shutdown_status == ShutdownStatus.PRE_SHUTDOWN) or
        (status == 'STARTING' and
         shutdown_status == ShutdownStatus.POST_SHUTDOWN)):
      return TestRunStatus.RUNNING

    return super().ParseTestlogRecord(record)


class TestTypeHandler(AbstractTestRunHandler):
  """Handler to get the test type info."""

  def ParseGenericRecord(self, record: record_module.IRecord) -> Optional[str]:
    return None

  def ParseSystemLogRecord(
      self, record: record_module.SystemLogRecord) -> Optional[str]:
    return None

  def ParseTestlogRecord(self,
                         record: record_module.TestlogRecord) -> Optional[str]:
    if 'testType' in record:
      return record['testType']
    return None


def DetermineStatusHandlerType(
    record: record_module.TestlogRecord) -> Type['StatusHandler']:
  """Determines the status handler type according to the data in record."""
  if TestTypeHandler().Parse(record) == 'shutdown':
    return ShutdownStatusHandler
  return StatusHandler


def ParseStatus(record: record_module.TestlogRecord) -> TestRunStatus:
  """Determines the status handler type and parses the record."""
  return DetermineStatusHandlerType(record)().Parse(record)
