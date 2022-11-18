#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Factory Display Manager

Control display from command line. The target device must run with
factory toolkit enabled.
"""

import argparse
import logging
import sys
from typing import Optional

from cros.factory.goofy.plugins import display_manager
from cros.factory.goofy.plugins import plugin_controller
from cros.factory.utils import json_utils


EXAMPLES = """Examples:
> display_manager list
  List all display.

> display_manager set_mirror_mode
  Enable mirror mode.

> display_manager set_mirror_mode --off
  Disable mirror mode.

> display_manager set_main_display 12345678910
  Set display with id 12345678910 to main display.

> display_manager --dut-ip 192.168.30.100 list
  List all display with ip 192.168.30.100.
"""
TIMEOUT_DESCRIPTION = (
    'maximum number of seconds to wait, -1 means nonblocking.')


def ListDisplayInfo(manager: display_manager.DisplayManager, pretty: bool,
                    verbose: bool, **unused_kwargs):
  """Lists current display info in Chrome System Display API."""
  display_info = manager.ListDisplayInfo(verbose)
  print(json_utils.DumpStr(display_info, pretty, sort_keys=True))


def SetMirrorMode(manager: display_manager.DisplayManager, mode: str,
                  timeout: Optional[int], **unused_kwargs):
  """Sets mirror mode."""
  manager.SetMirrorMode(mode, timeout)


def SetMainDisplay(manager: display_manager.DisplayManager, display_id: str,
                   timeout: Optional[int], **unused_kwargs):
  """Sets main display."""
  manager.SetMainDisplay(display_id, timeout)


def ParseArgument():
  parser = argparse.ArgumentParser(
      description=__doc__, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--dut-ip', type=str, default='localhost')
  parser.add_argument('--dut-port', type=str, default='4012')

  subparsers = parser.add_subparsers(title='subcommands', dest='subcommand')
  subparsers.required = True

  subparser = subparsers.add_parser('list', help=ListDisplayInfo.__doc__)
  subparser.set_defaults(subcommand=ListDisplayInfo)
  subparser.add_argument('--no-pretty', dest='pretty', action='store_false',
                         help='Do not format the output.')
  subparser.add_argument('--verbose', action='store_true',
                         help='Show full information.')

  subparser = subparsers.add_parser('set_mirror_mode',
                                    help=SetMirrorMode.__doc__)
  subparser.set_defaults(subcommand=SetMirrorMode)
  subparser.add_argument('--timeout', type=int, default=10,
                         help=TIMEOUT_DESCRIPTION)
  subparser.add_argument(
      '--mode', choices=[mode.name for mode in display_manager.MirrorMode],
      default=display_manager.MirrorMode.normal.name)

  subparser = subparsers.add_parser('set_main_display',
                                    help=SetMainDisplay.__doc__)
  subparser.set_defaults(subcommand=SetMainDisplay)
  subparser.add_argument('--timeout', type=int, default=10,
                         help=TIMEOUT_DESCRIPTION)
  subparser.add_argument('display_id', type=str)

  return parser.parse_args()


def main():
  args = ParseArgument()

  plugin_name = 'display_manager'
  manager: display_manager.DisplayManager = (
      plugin_controller.GetPluginRPCProxy(plugin_name, args.dut_ip,
                                          args.dut_port))
  if not manager:
    logging.error('%r plugin is off.', plugin_name)
    sys.exit(1)

  args.subcommand(manager, **args.__dict__)


if __name__ == '__main__':
  main()
