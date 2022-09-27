#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json

from cros.factory.device import device_utils
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


# TODO (phoebewang): add an option to filter the sensitive VPD
def PrintSystemInfo(output_file):
  if sys_utils.InChroot():
    raise RuntimeError('This command can only be run on DUT!')

  dut_info = device_utils.CreateStationInterface().info
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
      'vpd': dut_info.vpd_info,
      'wp': dut_info.wp_info,
  }
  serialized_system_info = json.dumps(system_info, indent=4, sort_keys=True)

  if output_file is None:
    print(serialized_system_info)
  else:
    file_utils.WriteFile(output_file, serialized_system_info)


def ParseArgument():
  parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('target', choices=('system', 'test'))
  parser.add_argument(
      '--output', '-o', type=str, default=None, metavar='path',
      help=('Path to store the summary file. '
            'Print to stdout if not set.'))

  return parser.parse_args()


def main():
  args = ParseArgument()
  if args.target == 'system':
    PrintSystemInfo(args.output)
    return
  if args.target == 'test':
    PrintTestInfo()


if __name__ == '__main__':
  main()
