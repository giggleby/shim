# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Display interactive test utils.

This module contains the utils for the display interactive test.
"""

import logging
import os
import sys
import time
import xmlrpc.client

# TODO(b/275322979): Solve dependency issue.
from cros.factory.device.links import ssh
from cros.factory.utils import process_utils


# Setup logging level and format.
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')


class Communication:
  """XML-RPC client communication."""

  def __init__(self, ip: str, xmlrpc_port=5566, ssh_port=22):
    """Initialize the XML-RPC client.

    Args:
        ip: The DUT IP address.
        port: The DUT XML-RPC listening port.
    """
    self.proxy = xmlrpc.client.ServerProxy(f'http://{ip}:{xmlrpc_port}')
    self.ssh_link = ssh.SSHLink(host=ip, port=ssh_port, control_persist=300)

  def _IsPytestRunning(self, pytest_id: str) -> bool:
    """Check if a pytest is running.

    Args:
      pytest_id: The pytest ID.

    Returns:
        True if the test is running; otherwise False.
    """
    args = ['factory', 'run-status']
    process = self.ssh_link.Shell(args, stdout=process_utils.PIPE,
                                  stderr=process_utils.PIPE)
    output, errmsg = process.communicate()
    if process.returncode != 0:
      logging.error('Exit code %d from command: "%s"', process.returncode, args)
      raise process_utils.CalledProcessError(process.returncode, args, output,
                                             errmsg)

    assert isinstance(output, str)
    return 'RUNNING' in output and pytest_id in output and len(
        output.split(pytest_id.split('.')[0])) == 2

  def tearDown(self):
    """Tears down the test."""
    self.proxy.tearDown()

  def Init(self, pytest_id: str) -> None:
    """Initializes the DUT and runs a pytest if not yet running.

    Args:
      pytest_id: pytest ID
    """
    if self._IsPytestRunning(pytest_id):
      return

    args = ['factory', 'run', pytest_id]
    process = self.ssh_link.Shell(args)
    if process.wait() != 0:
      raise process_utils.CalledProcessError(
          process.returncode, args, process.stdout_data, process.stderr_data)
    time.sleep(0.3)

  def RunCommand(self, cmd: str) -> None:
    """Run a command on the DUT.

    Args:
      cmd: The command to run.
    """
    returncode = self.ssh_link.Shell(cmd).wait()
    sys.exit(returncode)

  def Push(self, src: str, dst: str) -> None:
    """Pushes a file or directory on local to the remote host.

    Args:
      src: The source file or directory.
      dst: The destination file or directory.
    """
    if os.path.isdir(src):
      self.ssh_link.PushDirectory(src, dst)
    else:
      self.ssh_link.Push(src, dst)

  def Pull(self, src: str, dst: str) -> None:
    """Pulls a file or directory from the remote host to local.

    Args:
      src: The source file or directory.
      dst: The destination file or directory.
    """
    logging.info('Pull %s to %s', src, dst)

    # Checks remote source is a file or a directory.
    returncode = self.ssh_link.Shell(f'[ -d "{src}" ]').wait()
    if returncode == 0:
      self.ssh_link.PullDirectory(src, dst)
    else:
      self.ssh_link.Pull(src, dst)

  def ShowPattern(self, pattern) -> None:
    """Shows the css pattern.

    Args:
        pattern: The pattern to show.
    """
    self.proxy.ShowPattern(pattern)

  def GetSerialNumber(self) -> None:
    """Gets the DUT serial number.

    Returns:
        The DUT device data serial number.
    """
    serial_number = self.proxy.GetSerialNumber()
    print(serial_number)

  def FailTest(self, reason: str) -> None:
    """Fails the pytest.

    Args:
        reason: The reason to fail the pytest.
    """
    self.proxy.FailTest(reason)

  def ShowImage(self, image: str) -> None:
    """Shows an image.

    Args:
        image: The image name to display on the DUT.
    """
    self.proxy.ShowImage(image)

  def SetDisplayBrightness(self, arg_brightness: str) -> None:
    """Sets the display backlight brightness.

    The brightness should be in the range from  0.0 to 1.0. Default value for
    DUTs is 0.5.

    Args:
        brightness: The brightness to set.
    """
    brightness = float(arg_brightness)
    if brightness < 0.0 or brightness > 1.0:
      raise ValueError('Brightness must be in range [0.0, 1.0].')
    self.proxy.SetDisplayBrightness(brightness)

  def SetKeyboardBacklight(self, arg_brightness: str) -> None:
    """Sets the keyboard backlight brightness.

    The brightness should be an integer in the range from  0 to 100. Default
    value for DUTs is 0.

    Args:
        brightness: The brightness to set.
    """
    try:
      brightness = int(arg_brightness)
    except ValueError:
      raise ValueError('Brightness must be an integer.') from None
    if brightness < 0 or brightness > 100:
      raise ValueError('Brightness must be in range [0, 100].')
    # TODO(wdzeng, cyueh): Use XMLRPC method.
    self.ssh_link.Shell(['ectool', 'pwmsetkblight', str(brightness)])
