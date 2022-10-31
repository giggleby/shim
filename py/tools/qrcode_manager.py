#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json

from cros.factory.goofy.plugins import plugin_controller


DESCRIPTION = 'Factory QR Code Manager'
EXAMPLES = """
  This is a command line interface which interacts with the `qrcode_manager`
  plugin. User has to enable the `qrcode_manager` plugin before using this
  tool.

  Examples:
  > qrcode_manager --position='[[100, 200], [500, 600]]' --size='[100, 100]'
      --qrcode="model#touchscreen"
    Displaying QR codes at the front end...

  > qrcode_manager --status
    QR codes are displayed at the front end.
    Positions: [[100, 200], [500, 600]]
    Sizes: [100, 100]
    QR code information: "model#touchscreen"
    QR code base64 string: ...

  # This will use the default position, size and qrcode content defined in the
  # plugin.
  > qrcode_manager
    Displaying QR codes at the front end...

  > qrcode_manager --stop

  > qrcode_manager --status
    QR codes are not displayed.
"""


class QRCodeManager:

  def __init__(self):
    self._qrcode_manager = plugin_controller.GetPluginRPCProxy(
        'qrcode_manager.qrcode_manager')
    if not self._qrcode_manager:
      raise Exception('qrcode_manager.qrcode_manager plugin is not running!')

  def DisplayStatus(self):
    info = self._qrcode_manager.GetQRCodeInfo()
    if info:
      print('QR codes are displayed at the front end.')
      print(f"Positions: {info['pos']}")
      print(f"Sizes: {info['size']}")
      print(f"QR code content: {info['qrcode_content']}")
      print(f"QR code base64 string: {info['qrcode']}")
    else:
      print('QR codes are not displayed.')

  def StopShowingQRCode(self):
    self._qrcode_manager.StopShowingQRCode()

  def ShowQRCode(self, coords=None, sizes=None, qrcode=None):
    # Removes the existing QR code if it exists.
    self.StopShowingQRCode()
    self._qrcode_manager.ShowQRCode(coords, sizes, qrcode)
    self.DisplayStatus()


def ParseArgument():
  parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument(
      '--position', '-p', type=json.loads, default=None,
      metavar='\'[[x1, y1], [x2, y2]...]\'',
      help=('The top left x, y positions of the QR code. (Unit: px) None to '
            'use the default value defined by the plugin.'))
  parser.add_argument(
      '--size', '-s', type=json.loads, default=None,
      metavar='\'[size1, size2...]\'',
      help=('The size of the QR code. (Unit: px) None to use '
            'the default value defined by the plugin.'))
  parser.add_argument(
      '--qrcode', '-q', type=str, default=None, metavar="QR_code_content",
      help=('The string used to generate the QR code. None to '
            'use the default value defined by the plugin.'))
  group = parser.add_mutually_exclusive_group()
  group.add_argument('--stop', action='store_true',
                     help=('Stop displaying QR code.'))
  group.add_argument('--status', action='store_true',
                     help=('Get current status of the plugin qrcode_manager.'))

  return parser.parse_args()


def main():
  args = ParseArgument()
  qrcode_manager = QRCodeManager()
  if args.status:
    qrcode_manager.DisplayStatus()
  elif args.stop:
    qrcode_manager.StopShowingQRCode()
  else:
    qrcode_manager.ShowQRCode(args.position, args.size, args.qrcode)


if __name__ == '__main__':
  main()
