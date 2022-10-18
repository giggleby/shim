# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Test display functionality with interactive mode.

Description
-----------
This test runs in interactive mode.
A host (test station) connects to this test via xml-rpc client. The test
supports the following functions can be called by the host:
- GetSerialNumber: Get the DUT device data serial number.

- ShowPattern: Show the pattern defined in css, This function can be called
  multiple times to show different patterns, the previous pattern will be hidden
  after the new pattern is shown.

- ShowImage: Show the DUT local image. The image file needs to be placed in the
  static directory. This function can be called multiple times to show different
  images, the previous image will be hidden after the new image is shown.

- SetDisplayBrightness: Set the display brightness.
- tearDown: Close the XML-RPC server and end the test with the PASS result.
- FailTest: Fail the test with the given reason.

Test Procedure
--------------
In the beginning,  if autostart is set to true, white screen is shown on the
DUT, no function is called, if autostart is set to false, the device waits space
key to start the test, the test will wait for the xml-rpc client to connect, and
call the functions defined above to control the DUT.

When the ``ShowImage`` function is called, we check if the file is available in
the static folder (``...factory/py/test/pytests/display_interactive/static/``).
If the file doesn't exist, the test will fail. Otherwise, the image file will be
displayed in fullscreen mode.  If there is an image shown by the previous
``ShowImage`` function, the previous pattern/image will be hidden first.

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

  @staticmethod
  def GetSerialNumber():
    """Returns the serial number of the device."""
    return device_data.GetSerialNumber('serial_number')

  def ShowPattern(self, pattern):
    """Show the pattern defined in css."""
    logging.info('Showing pattern %s', pattern)
    self.frontend_proxy.ShowPattern(pattern)

  def ShowImage(self, image):
    """Shows the local image."""
    if not os.path.exists(os.path.join(self.static_dir, image + '.png')):
      self.FailTest(f'Image file {image}.png does not exist.')

    logging.info('Showing the local image: %s', image)
    self.frontend_proxy.ShowImage(image)

  def FailTest(self, reason):
    """Fail test with the given reason."""
    self.frontend_proxy.FailTest(reason)

  def SetDisplayBrightness(self, brightness):
    """Set the display backlight brightness, between 0.0 and 1.0."""
    self.dut.display.SetBacklightBrightness(brightness)
