#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json
from typing import Dict, Optional, Union

from cros.factory.device import device_utils
from cros.factory.test.rules.privacy import FilterDict
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


def PrintTestInfo():
  print('This command has not been implemented.')


def GetSystemInfo(filter_vpd: bool = False) -> Dict[
  str, Optional[Union[Dict, bool, int, str]]]:
  """Returns the system information in type of dict."""
  dut_info = device_utils.CreateStationInterface().info
  vpd = dut_info.vpd_info
  if filter_vpd:
    vpd = FilterDict(vpd)

  system_info = {
      'cbi': dut_info.cbi_info,
      'crosid': dut_info.crosid,
      'device': dut_info.device_info,
      'factory': dut_info.factory_info,
      'fw': dut_info.fw_info,
      'gsc': dut_info.gsc_info,
      'hw': dut_info.hw_info,
      'image': dut_info.image_info,
      'system': dut_info.system_info,
      'vpd': vpd,
      'wp': dut_info.wp_info,
  }
  return system_info


def PrintSystemInfo(filter_vpd: bool = False,
                    output_file: Optional[str] = None) -> None:
  """Prints or writes the result of GetSystemInfo() in json format."""
  if sys_utils.InChroot():
    raise RuntimeError('This command can only be run on DUT!')

  system_info = GetSystemInfo(filter_vpd)
  serialized_system_info = json.dumps(system_info, indent=4, sort_keys=True)

  if output_file is None:
    print(serialized_system_info)
  else:
    file_utils.WriteFile(output_file, serialized_system_info)


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
    PrintSystemInfo(args.filter_vpd, args.output)
  elif args.subcommand == 'test':
    PrintTestInfo()


if __name__ == '__main__':
  main()
