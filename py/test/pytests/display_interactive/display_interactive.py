# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test display functionality with interactive mode.

Description
-----------
This test runs in interactive mode.

A host (test station) connects to this test via xml-rpc client. The test
supports the following functions that can be called by the host:

- GetSerialNumber: Retrieves the DUT device serial number.
- ShowPattern: Displays a pattern defined in css, multiple patterns can be shown
  and the previous pattern will be hidden after the new one is displayed.
- ShowImage: Displays a local image on the DUT. Multiple images can be shown,
  and the previous image will be hidden after the new one is displayed.
- SetDisplayBrightness: Sets the brightness level of the display.
- SetKeyboardBacklight: Sets the brightness level of the keyboard backlight.
- tearDown: Closes the XML-RPC server and ends the test with a "PASS" result.
- FailTest: Fails the test with the given reason.

Test Procedure
--------------
At the beginning, if the argument ``autostart`` is set, the DUT will display a
white screen without calling any functions; otherwise it will wait for the space
key to be pressed before starting the test. Additionally, the test will wait for
the XML-RPC client to connect and then call the functions defined above to
control the DUT.

When the ``ShowImage`` function is invoked, we verify if the file is present in
the static folder located at ``py/test/pytests/display_interactive/static/``.
The test fails if the image is not found, or else it will be displayed in
fullscreen mode. Moreover, if a pattern or image was previously displayed by the
``ShowImage`` function, it will first be hidden before displaying a new image.

Dependency
----------
- This test uses javascript to control the display.
- This test uses an XML-RPC server to receive commands from the test station.

Examples
--------
To test display functionality, add this into test list::

  {
    "pytest_name": "display_interactive.display_interactive",
    "args": {
      "port": 5566,
      "autostart": true
    }
  }

"""

import logging
import os
import socketserver
import xmlrpc.server

from cros.factory.device import device_utils
from cros.factory.test import device_data
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils


class ThreadXMLRPCServer(socketserver.ThreadingMixIn,
                         xmlrpc.server.SimpleXMLRPCServer):
  """A threaded XML-RPC server."""


class DisplayInteractiveTest(test_case.TestCase):
  ARGS = [
      Arg('port', type=int, help='Port of the XML-RPC server', default=5566),
      Arg('autostart', type=bool, help='Auto start the test', default=True)
  ]

  def __init__(self):
    super().__init__()
    self.server = None

  def setUp(self):
    """Initialize the test."""
    self.dut = device_utils.CreateDUTInterface()
    self.static_dir = self.ui.GetStaticDirectoryPath()

    self.frontend_proxy = self.ui.InitJSTestObject('DisplayInteractiveTest', '')

    # Set firewall rules to allow xml-rpc server listen on port.
    process_utils.Spawn([
        'iptables', '-A', 'INPUT', '-p', 'tcp', '--dport',
        str(self.args.port), '-j', 'ACCEPT'
    ], check_call=True)
    self.ui.BindStandardFailKeys()

  def runTest(self):
    if not self.args.autostart:
      self.ui.SetInstruction('Press space to start the test')
      self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    self.SetDisplayBrightness(1.0)
    # Automatically toggle fullscreen.
    self.frontend_proxy.ToggleFullscreen()

    self.RunAsServer()

  def RunAsServer(self):
    """Run the XML-RPC server."""
    self.server = ThreadXMLRPCServer(('0.0.0.0', self.args.port),
                                     allow_none=True)
    self.server.register_introspection_functions()
    self.server.register_instance(self)
    logging.info('Starting XML-RPC server on %d', self.args.port)
    self.server.serve_forever()

  def ServerClose(self):
    self.server.shutdown()
    self.server.server_close()
    logging.info('XML-RPC server closed.')

  def tearDown(self):
    self.SetDisplayBrightness(0.5)
    self.ServerClose()

  @classmethod
  def GetSerialNumber(cls) -> str:
    """Returns the serial number of the device."""
    return device_data.GetSerialNumber('serial_number')

  def ShowPattern(self, pattern: str):
    """Shows the pattern defined in css."""
    logging.info('Showing pattern %s', pattern)
    self.frontend_proxy.ShowPattern(pattern)

  def ShowImage(self, image: str):
    """Shows the local image."""
    if not os.path.exists(os.path.join(self.static_dir, image + '.png')):
      self.FailTest(f'Image file {image}.png does not exist.')

    logging.info('Showing the local image: %s', image)
    self.frontend_proxy.ShowImage(image)

  def FailTest(self, reason: str):
    """Fails test with the given reason."""
    self.frontend_proxy.FailTest(reason)

  def SetDisplayBrightness(self, brightness: float):
    """Sets the display backlight brightness, between 0.0 and 1.0."""
    self.dut.display.SetBacklightBrightness(brightness)
