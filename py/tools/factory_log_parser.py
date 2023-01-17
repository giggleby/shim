#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import functools
import json
import logging
import re
import sys

from cros.factory.utils import process_utils
from cros.factory.utils import sys_utils


DESCRIPTION = """

Best effort log parser for logs collected with factory_bug

Currently 5 types of logs are supported:

Generic syslog format -> /var/log/messages
Firmware event log format -> firmware_eventlog
Cros EC log format -> /var/log/cros_ec.log
Clobber-state log format -> /var/log/clobber.log
Goofy.d MiniJail log format -> /var/log/minijail0.log

This tool will try to match with log lines according to above mentioned orders.

Please be noted that for factory generated logs, since they are already
piped to TestLog and stored in JSON format, this tool will not try to parse it.


"""

EXAMPLES = """Examples:

Parsing /var/log/messages to stdout:
factory_log_parser --log_path=path/to/factory_bug/var/log/messages

Saving output to certain file:
factory_log_parser --log_path=/var/log/messages --output_file=path/to/output

If the log is logged with timestamps ending with Z, this tool will regard
this timestamp as UTC+0 zero timezone. Otherwise, this tool will try to convert
it with timezone information. Also for clobber.log the UTC is specified
directly in its timestamp.

On DUT, this tool will automatically try to query Linux command date +%:z to
get timezone information so we could leave --timezone_offset unset.
However, if it's not on DUT, please provide it as input argument:
factory_log_parser --log_path=var/log/factory.log --timezone_offset=-08:00

In cases where the given assumption of timestamp ending with Z is equivalent
to UTC+0 should break, it is possible to force timezone overrides with
--override_timezone argument:
factory_log_parser --log_path=path --override_timezone --timezone_offset=-08:00

The log level will be mapped to python logging levels for later query usages.

Example output of the tool will be:

{
  "filePath": "root_factory_bug/var/log/messages",
  "lineNumber": 5
  “logLevel”: “DEBUG”,
  “message”: “kernel: [    0.000015]   0 base 000000000000 mask 3FFF80000000”,
  “originalTimestamp”: “2022-09-21T14:41:59.927893Z”,
  “time”: 1673252376,
}

"""

_SYSLOG_TO_PYTHON_LEVELS = {
    ('EMERG', 'PANIC', 'ALERT', 'CRIT'): 'CRITICAL',
    ('ERR', 'ERROR'): 'ERROR',
    ('WARNING', 'WARN', 'NOTICE'): 'WARNING',
    ('INFO', ): 'INFO',
    ('DEBUG', ): 'DEBUG'
}

_SYSLOG_LEVEL_PATTERN = r'|'.join([
    level_alias for level in _SYSLOG_TO_PYTHON_LEVELS for level_alias in level
])

_ISO_UTC_TIMESTAMP_PATTERN = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z'
_ISO_UTC_STRFTIME_PATTERN = '%Y-%m-%dT%H:%M:%S.%fZ'

_FIRMWARE_EVENTLOG_TIMESTAMP_PATTERN = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
_FIRMWARE_EVENTLOG_STRFTIME_PATTERN = '%Y-%m-%d %H:%M:%S'

_CLOBBER_UTC_TIMESTAMP_PATTERN = r'\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2} UTC'
_CLOBBER_STRFTIME_PATTERN = '%Y/%m/%d %H:%M:%S UTC'

_GOOFY_MINIJAIL_TIMESTAMP_PATTERN = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+'
_GOOFY_MINIJAIL_STRFTIME_PATTERN = '%Y-%m-%d %H:%M:%S.%f'


@functools.lru_cache(maxsize=None)
def NormalizeLogLevel(log_level):
  for log_level_groups, python_log_level in _SYSLOG_TO_PYTHON_LEVELS.items():
    if log_level in log_level_groups:
      return python_log_level
  return log_level


class FactoryLogParserError(Exception):
  """All exceptions when parsing factory logs."""


class LogLineParser:
  """Helper class to extract raw information from given log line.

  Attributes:
    is_timestamp_utc:
      Specify if the originalTimestamp acquired is regarded as UTC+0.
    strftime_str:
      The strftime pattern for the acquired originalTimestamp.
    _line_pattern:
      Compiled regex pattern for given log line.
  """

  def __init__(self):
    self.is_timestamp_utc = False
    self.strftime_str = None
    self._line_pattern = None

  def GetMatchedRawData(self, line):
    """Extracting the matched raw data from given input log line.

    Validation on timestamps will not be done when parsing.

    Args:
      Input log line string.

    Returns:
      A dict with 3 keys: logLevel, message and originalTimestamp.
      The value correspond to these keys is stored as string.

    Raises:
      KeyError: If no timestamp found in matched groupdict of log line.
    """
    match = self._line_pattern.match(line)
    if match:
      return {
          'logLevel': match.groupdict().get('log_level', 'INFO'),
          'message': match.groupdict().get('message', ''),
          'originalTimestamp': match.groupdict()['timestamp']
      }
    return None

  def IsMatched(self, line):
    return self._line_pattern.match(line)


class GenericSysLogParser(LogLineParser):
  """
  2022-09-26T17:59:21.672937Z INFO powerd: [main.cc(460)] System uptime: 5s
  """

  _regex_template = r'(?P<timestamp>{}) (?P<log_level>{}) (?P<message>.*)'

  def __init__(self):
    super().__init__()
    self.is_timestamp_utc = True
    self.strftime_str = _ISO_UTC_STRFTIME_PATTERN
    self._line_pattern = re.compile(
        self._regex_template.format(_ISO_UTC_TIMESTAMP_PATTERN,
                                    _SYSLOG_LEVEL_PATTERN))


class CrosECLogParser(LogLineParser):
  """
  2022-09-26T17:59:18.236000Z [90251.139016 charge_request(12568mV, 0mA)]
  """

  _regex_template = r'(?P<timestamp>{}) (?P<message>.*)'

  def __init__(self):
    super().__init__()
    self.strftime_str = _ISO_UTC_STRFTIME_PATTERN
    self._line_pattern = re.compile(
        self._regex_template.format(_ISO_UTC_TIMESTAMP_PATTERN))


class FirmwareEventLogParser(LogLineParser):
  """
  16 | 2022-08-08 06:46:18 | System Reset
  """

  _regex_template = r'([0-9]+) \| (?P<timestamp>{}) \| (?P<message>.*)'

  def __init__(self):
    super().__init__()
    self.strftime_str = _FIRMWARE_EVENTLOG_STRFTIME_PATTERN
    self._line_pattern = re.compile(
        self._regex_template.format(_FIRMWARE_EVENTLOG_TIMESTAMP_PATTERN))


class GoofyMiniJailLogParser(LogLineParser):
  # pylint: disable=line-too-long
  """
  [ERROR] 2022-09-25 23:19:06.436 argument: ['/sbin/minijail0', '-i', '-u', 'pciguard', '-g', 'pciguard', '-c', '2', '-l', '-N', '-p', '--uts', '-n', '--config', '/usr/share/minijail/pciguard.conf', '-S', '/usr/share/policy/pciguard-seccomp.policy', '/usr/sbin/pciguard']
  """

  _regex_template = r'(\[(?P<log_level>{})\]) (?P<timestamp>{}) (?P<message>.*)'

  def __init__(self):
    super().__init__()
    self.strftime_str = _GOOFY_MINIJAIL_STRFTIME_PATTERN
    self._line_pattern = re.compile(
        self._regex_template.format(_SYSLOG_LEVEL_PATTERN,
                                    _GOOFY_MINIJAIL_TIMESTAMP_PATTERN))


class ClobberLogParser(LogLineParser):
  """
  2022/09/25 23:16:36 UTC Failed mounting var and home/chronos; re-created.
  """

  _regex_template = r'(?P<timestamp>{}) (?P<message>.*)'

  def __init__(self):
    super().__init__()
    self.is_timestamp_utc = True
    self.strftime_str = _CLOBBER_STRFTIME_PATTERN
    self._line_pattern = re.compile(
        self._regex_template.format(_CLOBBER_UTC_TIMESTAMP_PATTERN))


_PARSERS = [
    GenericSysLogParser(),
    FirmwareEventLogParser(),
    CrosECLogParser(),
    ClobberLogParser(),
    GoofyMiniJailLogParser()
]


class FactoryLogParser:
  """Best effort log parser supporting logs collected with factory_bug."""

  _TIMEZONE_OFFSET_PATTERN = re.compile(
      r'(?P<sign>\+|-)(?P<hours>\d{2}):(?P<minutes>\d{2})')

  def __del__(self):
    self._file.close()
    if self._output_file != sys.stdout:
      self._output_file.close()

  def __init__(self, log_path, output_path, timezone_offset, override_utc):
    """Initializes the instance with the file path of input log.

    Args:
      log_path: Input log path (required).
      output_path: Output path of parsed JSON line objects, by default stdout.
      timezone_offset: Time offset string of the log, formatted in (+|-)HH:MM.
      override_utc: Set this as True so as to override UTC+0 timestamps.
        In this case timezone_offset should be required. If timezone_offset
        is provided but override_utc is False or None, the parser would only
        convert time with regards to timezone_offset when the timestamp
        is not specified as UTC+0. This is designed for possible batch
        parsing for all logs collected by factory_bug.
    """
    self._file = open(log_path, 'r', encoding='utf-8')  # pylint: disable=consider-using-with
    self._output_file = sys.stdout
    if output_path:
      self._output_file = open(output_path, 'w', encoding='utf-8')  # pylint: disable=consider-using-with
    self._parser = None
    self._override_utc = override_utc

    self._DetermineParserWithFirstLine()

    # If timezone_offset is not provided and the program is running on DUT,
    # date +%:z command will be invoked to get the offset.
    if sys_utils.InCrOSDevice() and not timezone_offset:
      timezone_offset = process_utils.CheckOutput(['date', '+%:z']).strip()
      logging.info('Current timezone offset collected: %s.', timezone_offset)

    if override_utc and not timezone_offset:
      raise FactoryLogParserError('Please add timezone_offset to override.')

    if not self._parser.is_timestamp_utc and not timezone_offset:
      raise FactoryLogParserError(('The log is matching with system timezone, '
                                   'please provide timezone information.'))

    if timezone_offset:
      time_pattern_match = self._TIMEZONE_OFFSET_PATTERN.match(timezone_offset)
      if not time_pattern_match:
        raise FactoryLogParserError(
            'Unknown time zone pattern, please formatted with (+|-)HH:MM')

      multiplier = -1 if time_pattern_match.groupdict()['sign'] == '+' else 1
      self._time_diff_hours = int(
          time_pattern_match.groupdict()['hours']) * multiplier
      self._time_diff_minutes = int(
          time_pattern_match.groupdict()['minutes']) * multiplier

  def _TimeStampToEpoch(self, timestamp):
    datetime_fmt = datetime.strptime(timestamp, self._parser.strftime_str)
    if not self._parser.is_timestamp_utc or self._override_utc:
      datetime_fmt += timedelta(hours=self._time_diff_hours,
                                minutes=self._time_diff_minutes)
    return datetime_fmt.replace(tzinfo=timezone.utc).timestamp()

  def _DetermineParserWithFirstLine(self):
    line = self._file.readline()
    self._file.seek(0)
    for parser in _PARSERS:
      if parser.IsMatched(line):
        self._parser = parser
        logging.info('Matching log file with %s.', parser.__class__.__name__)
        return
    raise FactoryLogParserError(
        f'Could not match any log line pattern with first line:\n{line}')

  def _FlushDataAsLineJson(self, buffered_data, buffered_line_number):
    buffered_data['logLevel'] = NormalizeLogLevel(buffered_data['logLevel'])
    buffered_data['time'] = self._TimeStampToEpoch(
        buffered_data['originalTimestamp'])
    buffered_data.update({
        'lineNumber': buffered_line_number,
        'filePath': self._file.name
    })
    if buffered_data['message'].endswith('\n'):
      buffered_data['message'] = buffered_data['message'][:-1]
    self._output_file.write(json.dumps(buffered_data, sort_keys=True) + '\n')
    self._output_file.flush()

  def Parse(self):
    """Parse input log file to JSON objects.

    By leveraging LogLineParser to get the raw output of log lines, additional
    information such as line number, epoch time of the log event and file path
    of the input log will be processed and added to the final output JSON.

    We need to buffer line data to cope with multi-line logs.
    e.g. powerd logs. Flush when we see new line of matched data.

    Raises:
      ValueError: Raised when converting invalid originalTimestamp to epoch.
    """
    buffered_data = {}
    buffered_line_number = None
    for line_number, line in enumerate(self._file, start=1):
      regex_matched_data = self._parser.GetMatchedRawData(line)
      if regex_matched_data:
        if buffered_data:
          self._FlushDataAsLineJson(buffered_data, buffered_line_number)
        # This is to pre-append newline for possible multi-line logs
        # Will be removed when flushing.
        regex_matched_data['message'] += '\n'
        buffered_data = regex_matched_data
        buffered_line_number = line_number
      else:
        buffered_data['message'] += line
    self._FlushDataAsLineJson(buffered_data, buffered_line_number)


def ParseArgument():
  arg_parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  arg_parser.add_argument('--log_path', required=True, type=str,
                          help=('File path of the log to be parsed.'))
  arg_parser.add_argument(
      '--output_path', type=str,
      help=('File path for the parsed output to be stored.'))
  arg_parser.add_argument(
      '--timezone_offset', type=str,
      help=('Time zone differences to UTC, please format this in (+|-)HH:MM.'))
  arg_parser.add_argument(
      '--override_utc', action='store_true',
      help=(('By default timestamps ending with Z will be regarded as UTC+0, '
             'however in cases where this assumption break, '
             'we could force overriding it with provided timezone offset.')))
  return arg_parser.parse_args()


def main():
  logging.basicConfig(level=logging.INFO)
  args = ParseArgument()
  log_parser = FactoryLogParser(args.log_path, args.output_path,
                                args.timezone_offset, args.override_utc)
  log_parser.Parse()


if __name__ == '__main__':
  main()
