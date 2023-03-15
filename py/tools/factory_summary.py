#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json
from typing import Dict, Optional, Union

from cros.factory.gooftool.common import Util
from cros.factory.utils import file_utils
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
"""


def PrintTestSummary():
  print('This command has not been implemented.')


def GetSystemSummary(
    filter_vpd: bool = False
) -> Dict[str, Optional[Union[Dict, bool, int, str]]]:
  """See common.Util.GetSystemInfo()"""
  return Util().GetSystemInfo(filter_vpd)


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
  parser.add_argument(
      '--output', '-o', type=str, default=None, metavar='path',
      help=('Path to store the summary file. '
            'Print to stdout if not set.'))
  system_parser = subparsers.add_parser('system',
                                        help='Collect system summary.')
  system_parser.add_argument('--filter_vpd', action='store_true',
                             help=('Filter out sensitive VPD values.'))
  subparsers.add_parser('test', help='Collect test summary.')

  return parser


def main():
  parser = ParseArgument()
  args = parser.parse_args()
  if args.subcommand == 'system':
    PrintSystemSummary(args.filter_vpd, args.output)
  elif args.subcommand == 'test':
    PrintTestSummary()


if __name__ == '__main__':
  main()
