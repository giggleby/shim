# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A plugin that shows the QR code on the UI.

This plugin is used to show the QR code on the UI. User should use the command
line interface under `py/tools/qrcode_manager.py` to interact with the plugin.

Examples
--------
To start the plugin and set default the arguments, add this to
`goofy_plugin_chromeos.json`::

  {
    "qrcode_manager.qrcode_manager": {
      "args": {
        "pos": [[100, 200], [300, 400]],
        "size": [200, 300],
        "content": "Hello ChromeOS!"
      }
    }
  }

"""

import base64
from io import BytesIO

from cros.factory.goofy.plugins import plugin
from cros.factory.test import event
from cros.factory.utils import schema
from cros.factory.utils import type_utils

from cros.factory.external.py_lib import qrcode

_POS_SCHEMA = schema.JSONSchemaDict(
    'position schema object',
    {
        'type': 'array',
        'items': {
            'type': 'array',
            'minItems': 2,
            'maxItems': 2
        }
    },
)


class QRCodeManager(plugin.Plugin):
  """A plugin which is used to show the QR codes in the front end.

  Properties:
    _default_pos: A list of list which specifies the top left x, y position of
      a list of QR codes. (Unit: px)
    _default_size: A list which specifies the size of the QR codes. (Unit: px)
    _default_content: A string which specifies the content of the QR code.
    _qrcode_info: A dictionary which stores the current QR code information,
      including the positions, sizes, content and the base64 string of the QR
      code.
  """

  def __init__(self, goofy, pos: list, size: list, content: str):
    super().__init__(goofy)
    _POS_SCHEMA.Validate(pos)
    self._CheckSizeEqual(pos, size)
    self._default_pos = pos
    self._default_size = size
    self._default_content = content
    self._qrcode_info = None

  def _CheckSizeEqual(self, pos, size):
    if len(pos) != len(size):
      raise Exception('The length of pos and size must match!'
                      'pos: %r, size: %r' % (pos, size))

  def _GenerateQRCode(self, content):
    """Generates a base64 qrcode string."""
    if not isinstance(content, str):
      raise Exception(
          'QR code content must be a string! (current: %r)' % content)

    img = qrcode.make(content)

    buffered = BytesIO()
    img.save(buffered, format='PNG')
    img_base64_str = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return 'data:image/png;base64,' + img_base64_str

  def _PostEvent(self, message):
    """Sends `UPDATE_QRCODE` event to goofy."""
    event.PostNewEvent(event.Event.Type.UPDATE_QRCODE,
                       js='updateQRCode(message)', message=message)

  @plugin.RPCFunction
  def GetQRCodeInfo(self):
    """Gets the qrcode information."""
    return self._qrcode_info

  @plugin.RPCFunction
  def ShowQRCode(self, pos=None, size=None, qrcode_content=None):
    """Shows the QR code at the front end.

    If arguments are set to `None`, this function will use the default values
    defined by the plugin.

    Args:
      pos: A list of list which specifies the top left x, y position of a list
        of QR codes. (Unit: px)
      size: A list which specifies the size of the QR codes. (Unit: px)
      qrcode_content: A string which specifies the content of the QR code.
    """
    if not pos:
      pos = self._default_pos
    if not size:
      size = self._default_size
    if not qrcode_content:
      qrcode_content = self._default_content

    _POS_SCHEMA.Validate(pos)
    self._CheckSizeEqual(pos, size)
    qrcode_str = self._GenerateQRCode(qrcode_content)

    args = {
        'pos': pos,
        'size': size,
        'qrcode_content': qrcode_content,
        'qrcode': qrcode_str
    }

    message = {
        'showQRcode': True,
        'args': args
    }

    self._qrcode_info = args
    self._PostEvent(message)

  @plugin.RPCFunction
  def StopShowingQRCode(self):
    """Stops showing the QR code at the front end."""
    if not self._qrcode_info:
      return

    message = {
        'showQRcode': False
    }
    self._qrcode_info = None
    self._PostEvent(message)

  @type_utils.Overrides
  def GetUILocation(self):
    return 'goofy-fullscreen'
