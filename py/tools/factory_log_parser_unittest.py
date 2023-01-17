#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import unittest

from cros.factory.tools import factory_log_parser
from cros.factory.utils import file_utils


class TestLogLineParser(unittest.TestCase):

  def testGenericParser(self):
    line_content = ('2022-09-25T23:19:18.581542Z CRIT root[5416]: '
                    'No new logout-started signal received.')

    general_parser = factory_log_parser.GenericSysLogParser()
    data = general_parser.GetMatchedRawData(line_content)
    expected_output = {
        'originalTimestamp': '2022-09-25T23:19:18.581542Z',
        'logLevel': 'CRIT',
        'message': 'root[5416]: No new logout-started signal received.'
    }
    self.assertDictEqual(data, expected_output)

  def testECLogParser(self):
    line_content = ('2022-09-26T17:59:18.236000Z '
                    '[90251.139016 charge_request(12568mV, 0mA)]')

    ec_log_parser = factory_log_parser.CrosECLogParser()
    data = ec_log_parser.GetMatchedRawData(line_content)
    expected_output = {
        'originalTimestamp': '2022-09-26T17:59:18.236000Z',
        'logLevel': 'INFO',
        'message': '[90251.139016 charge_request(12568mV, 0mA)]'
    }
    self.assertDictEqual(data, expected_output)

  def testFirmwareEventLogParser(self):
    line_content = '0 | 2022-09-19 20:39:09 | System Reset'
    firmware_eventlog_parser = factory_log_parser.FirmwareEventLogParser()
    data = firmware_eventlog_parser.GetMatchedRawData(line_content)
    self.assertDictEqual(
        data, {
            'originalTimestamp': '2022-09-19 20:39:09',
            'logLevel': 'INFO',
            'message': 'System Reset'
        })

  def testGoofyMiniJailParser(self):
    line_content = \
        '[ERROR] 2022-09-25 23:19:06.436 arg: [\'/sbin/minijail0\', \'-i\']'

    minijail_log_parser = factory_log_parser.GoofyMiniJailLogParser()
    data = minijail_log_parser.GetMatchedRawData(line_content)
    expected_output = {
        'originalTimestamp': '2022-09-25 23:19:06.436',
        'logLevel': 'ERROR',
        'message': 'arg: [\'/sbin/minijail0\', \'-i\']'
    }
    self.assertDictEqual(data, expected_output)

  def testClobberLogParser(self):
    line_content = \
        '2022/09/25 23:12:57 UTC Failed mounting var and home/chronos'
    clobber_log_parser = factory_log_parser.ClobberLogParser()
    data = clobber_log_parser.GetMatchedRawData(line_content)
    expected_output = {
        'originalTimestamp': '2022/09/25 23:12:57 UTC',
        'logLevel': 'INFO',
        'message': 'Failed mounting var and home/chronos'
    }
    self.assertDictEqual(data, expected_output)


class TestFactoryLogParser(unittest.TestCase):

  def setUp(self):
    self.tmp_input_file = file_utils.CreateTemporaryFile()
    self.tmp_output_file = file_utils.CreateTemporaryFile()

  def tearDown(self):
    if os.path.isfile(self.tmp_input_file):
      os.remove(self.tmp_input_file)
    if os.path.isfile(self.tmp_output_file):
      os.remove(self.tmp_output_file)

  def _WriteLinesToInputFile(self, lines):
    with open(self.tmp_input_file, 'w', encoding='utf-8') as input_file:
      for line in lines:
        input_file.write(line + '\n')

  def _ReadOutputAsLineJSONList(self):
    with open(self.tmp_output_file, 'r', encoding='utf-8') as output_file:
      output_json_list = []
      for line in output_file:
        output_json_list += [json.loads(line)]
      return output_json_list

  def testNoMatchingFormat(self):
    lines = [
        'This is a log line that could not be matched by existing patterns.'
    ]
    self._WriteLinesToInputFile(lines)
    with self.assertRaises(factory_log_parser.FactoryLogParserError):
      _unused_parser = factory_log_parser.FactoryLogParser(
          self.tmp_input_file, self.tmp_output_file, timezone_offset=None,
          override_utc=None)

  def testMultiSingleLineLogs(self):
    lines = [('2022-09-26T17:59:21.813108Z INFO '
              'powerd: [input_watcher.cc(396)] Watching power button'),
             ('2022-09-26T17:59:21.813211Z INFO '
              'powerd: [suspend.cc(158)] Console during suspend is enabled')]
    self._WriteLinesToInputFile(lines)

    parser = factory_log_parser.FactoryLogParser(
        self.tmp_input_file, self.tmp_output_file, timezone_offset=None,
        override_utc=None)
    parser.Parse()

    output_json_list = self._ReadOutputAsLineJSONList()
    self.assertEqual(len(output_json_list), 2)

    self.assertDictEqual(
        output_json_list[0], {
            'lineNumber': 1,
            'filePath': self.tmp_input_file,
            'logLevel': 'INFO',
            'message': 'powerd: [input_watcher.cc(396)] Watching power button',
            'originalTimestamp': '2022-09-26T17:59:21.813108Z',
            'time': 1664215161.813108
        })

    self.assertDictEqual(
        output_json_list[1], {
            'lineNumber':
                2,
            'filePath':
                self.tmp_input_file,
            'logLevel':
                'INFO',
            'message':
                'powerd: [suspend.cc(158)] Console during suspend is enabled',
            'originalTimestamp':
                '2022-09-26T17:59:21.813211Z',
            'time':
                1664215161.813211
        })

  def testOneMultiLineLogs(self):
    lines = [('2022-09-26T17:59:23.082439Z WARNING '
              'powerd: [object.cc(263)] message_type: MESSAGE_METHOD_CALL'),
             'destination: org.chromium.PowerManager',
             'path: /org/chromium/PowerManager']
    expected_message = (
        'powerd: [object.cc(263)] message_type: MESSAGE_METHOD_CALL\n'
        'destination: org.chromium.PowerManager\n'
        'path: /org/chromium/PowerManager')

    self._WriteLinesToInputFile(lines)

    parser = factory_log_parser.FactoryLogParser(
        self.tmp_input_file, self.tmp_output_file, timezone_offset=None,
        override_utc=None)
    parser.Parse()

    output_json_list = self._ReadOutputAsLineJSONList()
    self.assertEqual(len(output_json_list), 1)
    self.assertDictEqual(
        output_json_list[0], {
            'lineNumber': 1,
            'filePath': self.tmp_input_file,
            'logLevel': 'WARNING',
            'message': expected_message,
            'originalTimestamp': '2022-09-26T17:59:23.082439Z',
            'time': 1664215163.082439
        })

  def testMixedSingleAndMultiLineLogs(self):
    lines = [
        ('2022-09-26T17:59:23.082439Z WARNING '
         'powerd: [exported_object.cc(263)] message_type: MESSAGE_METHOD_CALL'),
        'destination: org.chromium.PowerManager',
        'path: /org/chromium/PowerManager',
        ('2022-09-26T17:59:21.813108Z INFO '
         'powerd: [input_watcher.cc(396)] Watching power button')
    ]
    expected_message = (
        'powerd: [exported_object.cc(263)] message_type: MESSAGE_METHOD_CALL\n'
        'destination: org.chromium.PowerManager\n'
        'path: /org/chromium/PowerManager')

    self._WriteLinesToInputFile(lines)

    parser = factory_log_parser.FactoryLogParser(
        self.tmp_input_file, self.tmp_output_file, timezone_offset=None,
        override_utc=None)
    parser.Parse()

    output_json_list = self._ReadOutputAsLineJSONList()
    self.assertEqual(len(output_json_list), 2)
    self.assertDictEqual(
        output_json_list[0], {
            'lineNumber': 1,
            'filePath': self.tmp_input_file,
            'logLevel': 'WARNING',
            'message': expected_message,
            'originalTimestamp': '2022-09-26T17:59:23.082439Z',
            'time': 1664215163.082439
        })

    self.assertDictEqual(
        output_json_list[1], {
            'lineNumber': 4,
            'filePath': self.tmp_input_file,
            'logLevel': 'INFO',
            'message': 'powerd: [input_watcher.cc(396)] Watching power button',
            'originalTimestamp': '2022-09-26T17:59:21.813108Z',
            'time': 1664215161.813108
        })

  def testTimezoneOffsetTimestampUTCGivenOffsetConvertSuccess(self):
    lines = [('2022-09-26T17:59:21.813108Z INFO '
              'powerd: [input_watcher.cc(396)] Watching power button')]
    self._WriteLinesToInputFile(lines)

    parser = factory_log_parser.FactoryLogParser(
        self.tmp_input_file, self.tmp_output_file, timezone_offset='+01:00',
        override_utc=None)
    parser.Parse()

    output_json_list = self._ReadOutputAsLineJSONList()
    self.assertEqual(len(output_json_list), 1)
    self.assertDictEqual(
        output_json_list[0], {
            'lineNumber': 1,
            'filePath': self.tmp_input_file,
            'logLevel': 'INFO',
            'message': 'powerd: [input_watcher.cc(396)] Watching power button',
            'originalTimestamp': '2022-09-26T17:59:21.813108Z',
            'time': 1664215161.813108
        })

  def testTimezoneOffsetTimestampUTCOverrideWithoutOffset(self):
    lines = [('2022-09-26T17:59:21.813108Z INFO '
              'powerd: [input_watcher.cc(396)] Watching power button')]
    self._WriteLinesToInputFile(lines)

    with self.assertRaises(factory_log_parser.FactoryLogParserError):
      _unused_parser = factory_log_parser.FactoryLogParser(
          self.tmp_input_file, self.tmp_output_file, timezone_offset=None,
          override_utc=True)

  def testTimezoneOffsetInvalidTimeZoneOffset(self):
    lines = [('2022-09-26T17:59:21.813108Z INFO '
              'powerd: [input_watcher.cc(396)] Watching power button')]
    self._WriteLinesToInputFile(lines)

    with self.assertRaises(factory_log_parser.FactoryLogParserError):
      _unused_parser = factory_log_parser.FactoryLogParser(
          self.tmp_input_file, self.tmp_output_file, timezone_offset='+223:00',
          override_utc=True)

  def testTimezoneOffsetNonUTCWithoutTimeZoneOffset(self):
    lines = ['16 | 2022-08-08 06:46:18 | System Reset']
    self._WriteLinesToInputFile(lines)

    with self.assertRaises(factory_log_parser.FactoryLogParserError):
      _unused_parser = factory_log_parser.FactoryLogParser(
          self.tmp_input_file, self.tmp_output_file, timezone_offset=None,
          override_utc=None)

  def testTimezoneOffsetNonUTCConvertSuccess(self):
    lines = ['16 | 2022-08-08 06:46:18 | System Reset']
    self._WriteLinesToInputFile(lines)

    parser = factory_log_parser.FactoryLogParser(
        self.tmp_input_file, self.tmp_output_file, timezone_offset='+01:00',
        override_utc=None)
    parser.Parse()

    output_json_list = self._ReadOutputAsLineJSONList()
    self.assertEqual(len(output_json_list), 1)
    self.assertDictEqual(
        output_json_list[0], {
            'lineNumber': 1,
            'filePath': self.tmp_input_file,
            'logLevel': 'INFO',
            'message': 'System Reset',
            'originalTimestamp': '2022-08-08 06:46:18',
            'time': 1659937578
        })

  def testTimezoneOffsetUTCOverrideSuccess(self):
    lines = [('2022-09-26T17:59:23.082439Z WARNING '
              'powerd: [object.cc(263)] message_type: MESSAGE_METHOD_CALL')]
    self._WriteLinesToInputFile(lines)

    parser = factory_log_parser.FactoryLogParser(
        self.tmp_input_file, self.tmp_output_file, timezone_offset='+01:00',
        override_utc=True)
    parser.Parse()

    output_json_list = self._ReadOutputAsLineJSONList()
    self.assertEqual(len(output_json_list), 1)
    self.assertDictEqual(
        output_json_list[0], {
            'lineNumber':
                1,
            'filePath':
                self.tmp_input_file,
            'logLevel':
                'WARNING',
            'message':
                'powerd: [object.cc(263)] message_type: MESSAGE_METHOD_CALL',
            'originalTimestamp':
                '2022-09-26T17:59:23.082439Z',
            'time':
                1664211563.082439
        })

  def testLogLevelConversion_CRITICAL(self):
    SYSLOG_LEVELS_SHOULD_MAP_TO_CRITICAL = ['EMERG', 'PANIC', 'ALERT', 'CRIT']
    for level in SYSLOG_LEVELS_SHOULD_MAP_TO_CRITICAL:
      self.assertEqual(factory_log_parser.NormalizeLogLevel(level), 'CRITICAL')

  def testLogLevelConversion_ERROR(self):
    SYSLOG_LEVELS_SHOULD_MAP_TO_ERROR = ['ERR', 'ERROR']
    for level in SYSLOG_LEVELS_SHOULD_MAP_TO_ERROR:
      self.assertEqual(factory_log_parser.NormalizeLogLevel(level), 'ERROR')

  def testLogLevelConversion_WARNING(self):
    SYSLOG_LEVELS_SHOULD_MAP_TO_WARNING = ['WARNING', 'WARN', 'NOTICE']
    for level in SYSLOG_LEVELS_SHOULD_MAP_TO_WARNING:
      self.assertEqual(factory_log_parser.NormalizeLogLevel(level), 'WARNING')

  def testLogLevelConversion_INFO(self):
    SYSLOG_LEVELS_SHOULD_MAP_TO_INFO = ['INFO']
    for level in SYSLOG_LEVELS_SHOULD_MAP_TO_INFO:
      self.assertEqual(factory_log_parser.NormalizeLogLevel(level), 'INFO')

  def testLogLevelConversion_DEBUG(self):
    SYSLOG_LEVELS_SHOULD_MAP_TO_DEBUG = ['DEBUG']
    for level in SYSLOG_LEVELS_SHOULD_MAP_TO_DEBUG:
      self.assertEqual(factory_log_parser.NormalizeLogLevel(level), 'DEBUG')


if __name__ == '__main__':
  unittest.main()
