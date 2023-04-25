# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import datetime
import json
from typing import Dict

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

  def GetEventType(self) -> str:
    return 'irecord'

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

  def GetEventType(self) -> str:
    return 'factory'

  def GetTime(self) -> float:
    return self['time']

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

  def GetEventType(self) -> str:
    return 'system'

  def __str__(self):
    return self._SYSLOG_TO_STR_TEMPLATE.format(
        log_level=self['logLevel'], file_path=self['filePath'],
        line_num=self['lineNumber'], time=self._GetFormattedUTCTime(),
        msg=self['message'])

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

  def GetEventType(self) -> str:
    return self._data.GetEventType()

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
      test_run = f"{self['testName']}-{self['testRunId']} {self['status']}"
      if self['testType'] == 'shutdown':
        test_run += f" ({self['parameters']['tag']['data'][0]['textValue']})"
      msg_list.append(test_run)
    if 'filePath' in self:
      msg_list.append(f"{self['filePath']}")
    msg_str = ' '.join(msg_list)
    if 'failures' in self:
      for failure in self['failures']:
        if failure['code'] == 'GoofyErrorMsg':
          msg_str += f"\n  Failed reason: {failure['details']}"

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
