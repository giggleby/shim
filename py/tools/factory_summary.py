#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json
import logging
import os
import re
from typing import IO, Dict, Optional, Union

from cros.factory.gooftool.common import Util
from cros.factory.log_extractor.file_utils import ExtractLogsAndWriteRecord
from cros.factory.log_extractor.file_utils import LogExtractorFileReader
import cros.factory.log_extractor.record as record_module
from cros.factory.tools.factory_log_parser import FactoryLogParser
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sys_utils


DESCRIPTION = """
  This is a tool to generate the factory system and test summary files.
"""
EXAMPLES = """
  Examples:

  To generate the system summary file and print to stdout:
  > factory_summary system
    {
      "cbi": {
        "board_version": 0,
        "fw_config": "0x1234",
        "sku_id": "0x1234"
      },
      "device": {
        ...
      },
      ...
    }

  To generate test summary on DUT:
  > factory_summary test
  # /var/factory/log/testlog.json and /var/log/messages will be extracted based
  # on test run to `/var/log/factory/{test_name}-{test_run_id}/summary/`.
  INFO:root:Root: /, TimeZone: -07:00
  INFO:root:Parse /var/log/messages and output to ...
  INFO:root:Matching log file with GenericSysLogParser.
  INFO:root:Extract logs based on test run to /var/factory/tests
  ...

  To generate test summary on workstation:
  > factory_summary test --root=<extracted_factory_bug> --timezone="+09:00"

"""

FACTORY_SUMMARY_REL_PATH = 'factory_system_summary'

VAR_LOG_MSG_REL_PATH = 'var/log/messages'
FACTORY_LOG_DIR_REL_PATH = 'var/factory'
FACTORY_TESTLOG_REL_PATH = f'{FACTORY_LOG_DIR_REL_PATH}/log/testlog.json'
FACTORY_TESTS_DIR_REL_PATH = f'{FACTORY_LOG_DIR_REL_PATH}/tests'
FACTORY_TEST_SUMMARY_PATH = f'{FACTORY_LOG_DIR_REL_PATH}/factory_test_summary'
FACTORY_TEST_STATUS_PATH = f'{FACTORY_LOG_DIR_REL_PATH}/factory_test_status'

FACTORY_SYSTEM_INFO = (
    'cbi',
    'crosid',
    'device',
    'factory',
    'fw',
    'gsc',
    'hw',
    'image',
    'modem_status',
    'system',
    'vpd',
    'wp',
)

def _GetTimeZone(root: str) -> str:
  if sys_utils.InCrOSDevice():
    return process_utils.CheckOutput(['date', '+%:z']).strip()
  system_summary = os.path.join(root, FACTORY_SUMMARY_REL_PATH)
  if not os.path.exists(system_summary):
    raise RuntimeError('Please specify the argument `timezone`!')
  timezone = None
  try:
    content = file_utils.ReadFile(system_summary)
    system_summary_dict = json.loads(content)
    timezone = system_summary_dict['device']['system_timezone']['offset']
  except Exception as e:
    raise RuntimeError(
        f'Failed to get timezone from factory_summary_system: {e!r}') from None
  return timezone


def _GetRoot() -> str:
  if sys_utils.InCrOSDevice():
    return '/'
  raise RuntimeError('Please specify the argument `root`!')


# TODO(phoebewang): Include AC info
def _GenerateTestSummary(summary_path: str, factory_log_path: str,
                         test_status: Optional[str]):
  """Generates the test summary.

  The test summary should contain:
  - Failed test items and the failed reason.
  - The start and end time of all tests.
  - Goofy start event.

  Args:
    summary_path: The output path of the factory summary.
    factory_log_path: Path to the factory log.
    test_status: A string which contains test status of all tests.
  """

  def ParseTestStatus(test_status: str) -> str:
    """Parses the tests' status and only returns the status of tested items.

    Test status format:
      - Tested test items: `generic_main:RunIn.BadBlocks: PASSED`
      - Untested test items: `generic_main:FFT.LidSwitch`
    Tested test items contain an extra test status field.
    """
    TESTED_ITEM_REGEX = (
        r'\S+: (ACTIVE|PASSED|FAILED|FAILED_AND_WAIVED|SKIPPED)')
    run_tests = ''
    for line in test_status.split('\n'):
      if re.match(TESTED_ITEM_REGEX, line):
        run_tests += f'{line}\n'

    return run_tests

  def PrintTestSummaryHeader(fd: IO, test_status: Optional[str]):
    fd.write(f"{'=' * 14} Factory Test Summary {'=' * 14}\n")
    if test_status:
      run_tests = ParseTestStatus(test_status)
      fd.write(f'Tests that have been run:\n{run_tests}')

  reader = LogExtractorFileReader(factory_log_path,
                                  record_module.TestlogRecord.FromJSON)
  with open(summary_path, 'w', encoding='utf-8') as summary_f:
    PrintTestSummaryHeader(summary_f, test_status)
    for record in reader.YieldByEventType(['station.init', 'station.test_run']):
      if record.GetEventType() == 'station.init':
        summary_f.write(f"\n{'=' * 19} Goofy Init {'=' * 19}\n")
      summary_f.write(f'{str(record)}\n')


def _GetTestStatus(root: str) -> Optional[str]:
  if sys_utils.InCrOSDevice():
    return process_utils.CheckOutput(['factory', 'tests', '--status']).strip()
  test_status = os.path.join(root, FACTORY_TEST_STATUS_PATH)
  if os.path.exists(test_status):
    return file_utils.ReadFile(test_status)
  return None


# TODO(phoebewang): Provide an argument to extract from system logs.
def ExtractTestInfo(root: Optional[str], timezone: Optional[str],
                    factory_test_summary_path: Optional[str]):
  if root is None:
    root = _GetRoot()
  if timezone is None:
    timezone = _GetTimeZone(root)

  logging.info('Root: %s, TimeZone: %s', root, timezone)
  factory_testlog_path = os.path.join(root, FACTORY_TESTLOG_REL_PATH)
  factory_tests_path = os.path.join(root, FACTORY_TESTS_DIR_REL_PATH)
  var_log_msg_path = os.path.join(root, VAR_LOG_MSG_REL_PATH)

  with file_utils.TempDirectory(prefix='factory_summary_test') as temp:
    # Parse /var/log/messages to a json file.
    parsed_var_log_msg_path = os.path.join(temp, 'parsed_var_log_msg.json')
    logging.info('Parse %s and output to %s ...', var_log_msg_path,
                 parsed_var_log_msg_path)
    FactoryLogParser(var_log_msg_path, parsed_var_log_msg_path, timezone,
                     True).Parse()

    logging.info('Extract logs based on test run to %s', factory_tests_path)
    # The extracted logs will be written to
    #   `factory_test_path/{test_name}-{test_run_id}/summary/`.
    ExtractLogsAndWriteRecord(factory_tests_path, factory_testlog_path,
                              parsed_var_log_msg_path)

  if factory_test_summary_path is None:
    factory_test_summary_path = os.path.join(root, FACTORY_TEST_SUMMARY_PATH)
  logging.info('Generate test summary to %s', factory_test_summary_path)
  _GenerateTestSummary(factory_test_summary_path, factory_testlog_path,
                       _GetTestStatus(root))


def GetSystemSummary(
    filter_vpd: bool = False
) -> Dict[str, Optional[Union[Dict, bool, int, str]]]:
  """See common.Util.GetSystemInfo()"""
  return Util().GetSystemInfo(filter_vpd, FACTORY_SYSTEM_INFO)


def PrintSystemSummary(filter_vpd: bool = False,
                       output_file: Optional[str] = None) -> None:
  """Prints or writes the result of GetSystemSummary() in json format."""
  if sys_utils.InChroot():
    raise RuntimeError('This command can only be run on DUT!')

  system_summary = GetSystemSummary(filter_vpd)
  serialized_system_summary = json.dumps(system_summary, indent=4,
                                         sort_keys=True)

  if output_file is None:
    print(serialized_system_summary)
  else:
    file_utils.WriteFile(output_file, serialized_system_summary)


def ParseArgument():
  parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  subparsers = parser.add_subparsers(dest='subcommand')
  subparsers.required = True
  system_parser = subparsers.add_parser('system',
                                        help='Collect system summary.')
  system_parser.add_argument('--filter_vpd', action='store_true',
                             help=('Filter out sensitive VPD values.'))
  system_parser.add_argument(
      '--output', '-o', type=str, default=None, metavar='path',
      help=('Path to store the system summary file. '
            'Print to stdout if not set.'))
  test_parser = subparsers.add_parser('test', help='Collect test summary.')
  test_parser.add_argument(
      '--root', '-r', type=str, default=None, metavar='path',
      help=('Root of the device. Should be `/` if the '
            'program runs on DUT and should be path to '
            'the extracted factory_bug if the program '
            'runs on workstation.'))
  test_parser.add_argument(
      '--timezone', '-t', default=None, metavar='(+|-)HH:MM', type=str,
      help=('Time zone differences to UTC. If the value is set to None, it '
            'will be inferred using `date +%%:z` if the program is running on '
            'DUT and read from `factory_summary_system` if the program is '
            'running on workstation.'))
  test_parser.add_argument(
      '--output', '-o', type=str, default=None, metavar='path',
      help=('Path to store the test summary file. If set to None, Store to'
            f'<root>/{FACTORY_TEST_SUMMARY_PATH}.'))

  return parser


def main():
  logging.basicConfig(level=logging.INFO)
  parser = ParseArgument()
  args = parser.parse_args()
  if args.subcommand == 'system':
    PrintSystemSummary(args.filter_vpd, args.output)
  elif args.subcommand == 'test':
    ExtractTestInfo(args.root, args.timezone, args.output)


if __name__ == '__main__':
  main()
