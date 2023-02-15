# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import datetime
import enum
import json
import re
from typing import Dict, Optional

from cros.factory.testlog import testlog
from cros.factory.utils.schema import FixedDict
from cros.factory.utils.schema import Scalar


class IRecord(abc.ABC):
  """A base class for holding dictionary-like data."""

  def __init__(self, data: Dict):
    self._data = data

  def __getitem__(self, key):
    return self._data[key]

  def __setitem__(self, key, val):
    self._data[key] = val

  def __contains__(self, item):
    return item in self._data

  def __eq__(self, other):
    if isinstance(other, self.__class__):
      return self._data == other._data
    return False

  def ToDict(self):
    return self._data

  @abc.abstractmethod
  def GetTime(self) -> float:
    """Returns the number of seconds passed since 1970/01/01 00:00:00."""
    raise NotImplementedError

  def _GetFormattedUTCTime(self):
    """Transforms time to a human-readable format."""
    return datetime.datetime.utcfromtimestamp(
        self.GetTime()).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

  def __lt__(self, other):
    return self.GetTime() < other.GetTime()


class TestRunStatus(enum.Enum):
  UNKNOWN = 'UNKNOWN'
  STARTED = 'STARTED'
  RUNNING = 'RUNNING'
  COMPLETED = 'COMPLETED'


class ShutdownStatus(enum.Enum):
  """The possible shutdown tag name is defined in py/goofy/invocation.py."""
  PRE_SHUTDOWN = 'pre-shutdown'
  POST_SHUTDOWN = 'post-shutdown'

class FactoryRecord(IRecord):
  _SCHEMA = FixedDict(
      'Factory record schema', items={
          'time':
              Scalar('Time in seconds since the epoch of the record.', float),
      }, allow_undefined_keys=True)

  @classmethod
  def FromJSON(cls, json_str: str, check_valid: bool = True):
    """Loads and validates the field of a JSON string to a dict-like object."""
    data = json.loads(json_str)
    if check_valid:
      cls._SCHEMA.Validate(data)

    return cls(data)

  def GetTime(self) -> float:
    return self['time']

  def GetTestRunName(self) -> Optional[str]:
    """Gets the test run name.

    The name should be in `<testName>-<testRunId>` format. This helps us
    identify which test is running.

    Returns:
      None if the record itself cannot infer which test is running.
    """
    return None

  def GetTestRunStatus(self) -> TestRunStatus:
    """Gets the test run status from the record.

    Returns:
      `TestRunStatus.UNKNOWN` if the record doesn't contain the test run status
      information. Else returns the TestRunStatus.
    """
    return TestRunStatus.UNKNOWN


class SystemLogRecord(FactoryRecord):
  _SCHEMA = FixedDict(
      'System log record schema', items={
          'filePath':
              Scalar('Path to the raw log file.', str),
          'lineNumber':
              Scalar(
                  'The line number of the raw log file where the record is '
                  'generated.', int),
          'logLevel':
              Scalar('The log level of the record.', str),
          'message':
              Scalar('Message text.', str),
          'time':
              Scalar('Time in seconds since the epoch of the record.', float),
      }, allow_undefined_keys=True)
  _SYSLOG_TO_STR_TEMPLATE = '[{log_level}] {time} {file_path}:{line_num} {msg}'

  def __str__(self):
    return self._SYSLOG_TO_STR_TEMPLATE.format(
        log_level=self['logLevel'], file_path=self['filePath'],
        line_num=self['lineNumber'], time=self._GetFormattedUTCTime(),
        msg=self['message'])


# TODO: Modify TestRunStatus based on shutdown event.
class VarLogMessageRecord(SystemLogRecord):
  # Example output of message:
  #   goofy[1845]: Test generic:SMT.Update (123-456) starting
  #   goofy[1845]: Test generic:SMT.Update (123-456) completed: FAILED (reason)
  _GOOFY_TEST_RUN_REGEX = (
      r'goofy\[\d+\]: Test (?P<testName>\S+) \((?P<testRunId>\S+)\) '
      r'(\S+: )?(?P<status>\S+)')

  def GetTestRunName(self) -> Optional[str]:
    match = re.search(self._GOOFY_TEST_RUN_REGEX, self['message'])
    if match:
      testName = match.group('testName').strip()
      testRunId = match.group('testRunId').strip()
      return f'{testName}-{testRunId}'
    return None

  def GetTestRunStatus(self) -> TestRunStatus:
    match = re.search(self._GOOFY_TEST_RUN_REGEX, self['message'])
    if match:
      status = match.group('status').strip()
      # TODO: Unify status such that it is the same as the status in testlog.
      if status == 'starting':
        return TestRunStatus.STARTED
      if status == 'resuming':
        return TestRunStatus.RUNNING
      if status in ('FAILED', 'PASSED'):
        return TestRunStatus.COMPLETED

    return TestRunStatus.UNKNOWN

class TestlogRecord(FactoryRecord):

  _STATION_TO_STR_TEMPLATE = '[{log_level}] {time} {msg}'

  def __init__(self, data: testlog.EventBase):
    super().__init__(data)
    self._time = self._data['time']
    if isinstance(self._data, testlog.StationTestRun):
      # The `time` field should store the timestamp that the event is generated.
      # However, there's an exception in testlog type `station.test_run`, where
      # we expect `time` be equal to `startTime` when the test starts, and be
      # equal to `endTime` when the test ends.
      # 'startTime' is required field for `station.test_run`, while `endTime`
      # only exists when a test completes.
      if 'endTime' in self:
        self._time = self['endTime']
      else:
        self._time = self['startTime']

  def GetTime(self) -> float:
    return self._time

  @classmethod
  def FromJSON(cls, json_str: str, check_valid: bool = True):
    data = testlog.EventBase.FromJSON(json_str, check_valid)

    return cls(data)

  def _IsShutdownEvent(self) -> bool:
    return self['testType'] == 'shutdown'

  def _GetShutdownStatus(self) -> ShutdownStatus:
    """Gets the shutdown status from parameters."""
    # Only shutdown type contains "tag".
    return ShutdownStatus(self['parameters']['tag']['data'][0]['textValue'])

  def GetTestRunStatus(self) -> TestRunStatus:
    if not isinstance(self._data, testlog.StationTestRun):
      return TestRunStatus.UNKNOWN
    status = self['status']
    if status == 'STARTING':
      # Most of the tests starts with `status` STARTING and end with `status`
      # PASS or FAIL. However, for shutdown test, the test status looks like:
      #   STARTING (pre-shutdown) -> FAIL (pre-shutdown) -> (DUT reboots) ->
      #   STARTING (post-shutdown)-> PASS/FAIL (post-shutdown)
      # which contains two starting (STARTING) and two ending (PASS/FAIL)
      # events. Change the second and third test events to RUNNING so that it
      # is easier to understand the test run status.
      if (self._IsShutdownEvent() and
          self._GetShutdownStatus() == ShutdownStatus.POST_SHUTDOWN):
        return TestRunStatus.RUNNING
      return TestRunStatus.STARTED
    if status in ('FAIL', 'PASS'):
      if (self._IsShutdownEvent() and
          self._GetShutdownStatus() == ShutdownStatus.PRE_SHUTDOWN):
        return TestRunStatus.RUNNING
      return TestRunStatus.COMPLETED
    if status == 'RUNNING':
      return TestRunStatus.RUNNING

    return TestRunStatus.UNKNOWN

  def GetTestRunName(self) -> Optional[str]:
    return f'{self["testName"]}-{self["testRunId"]}'

  def _BuildStrFromStationMessage(self) -> str:
    msg_list = []
    if 'filePath' in self and 'lineNumber' in self:
      msg_list.append(f"{self['filePath']}:{self['lineNumber']}")
    msg_list.append(self['message'])
    return ' '.join(msg_list)

  def _BuildStrFromStationInit(self):
    return (f"Goofy init count: {self['count']}, "
            f"success: {self['success']!r}")

  def _BuildStrFromStationStatus(self):
    msg_list = []
    # StationTestRun is a subclass of StationStatus.
    if isinstance(self._data, testlog.StationTestRun):
      msg_list.append(f"{self.GetTestRunName()} {self['status']}")
    if 'filePath' in self:
      msg_list.append(f"{self['filePath']}")
    msg_str = ' '.join(msg_list)
    if 'parameters' in self:
      param_to_str = json.dumps(self['parameters'], indent=2, sort_keys=True)
      msg_str += f'\nparameters:\n{param_to_str}'
    return msg_str

  def __str__(self):
    """Transforms a Testlog record to a reader-friendly format."""
    msg = ''
    if isinstance(self._data, testlog.StationMessage):
      msg = self._BuildStrFromStationMessage()
    elif isinstance(self._data, testlog.StationInit):
      msg = self._BuildStrFromStationInit()
    else:
      msg = self._BuildStrFromStationStatus()

    log_level = self['logLevel'] if 'logLevel' in self else 'INFO'
    return self._STATION_TO_STR_TEMPLATE.format(
        log_level=log_level, time=self._GetFormattedUTCTime(), msg=msg)
