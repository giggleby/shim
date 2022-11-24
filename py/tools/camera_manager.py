#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse

from cros.factory.goofy.plugins.camera_manager import camera_manager
from cros.factory.goofy.plugins import plugin_controller


DESCRIPTION = """Factory Camera Manager

When a camera is enabled, it shows the captured video on goofy UI.

This is a command line interface which interacts with the `camera_manager`
plugin. User has to enable the `camera_manager` plugin before using this tool.
"""
EXAMPLES = """Examples:
> camera_manager front enable
  Enable the front camera.

> camera_manager rear enable
  Enable the rear camera.

> camera_manager front disable
  Disable the front camera.

> camera_manager rear disable
  Disable the rear camera.

> camera_manager --dut-ip 192.168.30.100 front enable
  Enable the front camera of device with ip 192.168.30.100.
"""


def ParseArgument():
  parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--dut-ip', type=str, default='localhost')
  parser.add_argument('--dut-port', type=str, default='4012')
  parser.add_argument('facing', choices=('front', 'rear'))
  parser.add_argument('--hidden', action='store_true', help='Hide the video.')
  parser.add_argument('subcommand', choices=('enable', 'disable'))

  return parser.parse_args()


def main():
  args = ParseArgument()
  plugin_name = 'camera_manager.camera_manager'
  manager: camera_manager.CameraManager = (
      plugin_controller.GetPluginRPCProxy(plugin_name, args.dut_ip,
                                          args.dut_port))
  if not manager:
    raise Exception(f'{plugin_name!r} plugin is not running!')

  if args.subcommand == 'enable':
    manager.EnableCamera(args.facing, args.hidden)
    return
  if args.subcommand == 'disable':
    manager.DisableCamera(args.facing)


if __name__ == '__main__':
  main()
