# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Display interactive test utils.
This module contains the utils for the display interactive test.
"""
import logging
import os
import subprocess
import time
import xmlrpc.client


# Setup logging level and format.
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')


def SimpleCommandWithoutOutput(cmd):
  """Execute a command, return the return code."""
  try:
    ret = subprocess.call(cmd, shell=True, stdout=subprocess.DEVNULL,
                          stderr=subprocess.STDOUT)
    return ret
  except subprocess.CalledProcessError as e:
    return e.returncode


def SimpleCommand(cmd, print_output=False):
  """Execute a command and return the stdout."""
  try:
    with subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf-8',
    ) as proc:
      stdout, stderr = proc.communicate()
      ret = proc.returncode
      if ret:
        logging.warning('%s', stderr)
        return ret
      if print_output:
        logging.info('Output: %s', stdout)
      return stdout.strip()
  except subprocess.CalledProcessError as e:
    return e.returncode


def SetupSSHIdentityFile():
  """Setup the ssh identity file."""
  cmd = "curl 'https://chromium.googlesource.com/chromiumos/chromite/+/main" \
        "/ssh_keys/testing_rsa?format=TEXT'| base64 --decode > " \
        "~/.ssh/cros_testing_rsa"
  file_path = os.path.join(os.path.expanduser("~"), '.ssh', 'cros_testing_rsa')
  if not os.path.exists(file_path):
    logging.info('Missing identity file, start setup ssh identity file.')
    SimpleCommand(cmd)
  if oct(os.stat(file_path).st_mode)[-3:] != '600':
    os.chmod(file_path, 0o600)


def PingIsSuccessful(ip):
  """Ping a host and return True if successful."""
  cmd = f'ping -c 1 -W 1 {ip}'
  return SimpleCommandWithoutOutput(cmd) == 0


class SSHClient:
  """Utility class for SSH and SCP.
  Default settings for the ssh and scp commands are:
    Host: 192.168.0.* or any.
    User: root
    UserKnownHostsFile: /dev/null
    IdentityFile: ~/.ssh/cros_testing_rsa
    StrictHostKeyChecking: no
    ProxyCommand: none
    LogLevel: ERROR # to suppress warnings
    ConnectTimeout: 10
  """
  # Setup the fixed options.
  _fixed_options = [
      '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
      '-o', 'ConnectTimeout=10', '-o', 'ProxyCommand=none', '-o', 'User=root',
      '-o', 'LogLevel=ERROR', '-o', 'IdentityFile=~/.ssh/cros_testing_rsa'
  ]

  def __init__(self, host):
    self._host = host

  def SSHCommand(self, cmd):
    """Build the ssh command using the fixed options."""
    return f"ssh {' '.join(self._fixed_options)} {self._host} {cmd}"

  def SCPPushCommand(self, src, dst):
    """Build the scp push command using the fixed options."""
    return (
        f"scp -r {' '.join(self._fixed_options)} {src} root@{self._host}:{dst}")

  def SCPPullCommand(self, src, dst):
    """Build the scp pull command using the fixed options."""
    return (
        f"scp -r {' '.join(self._fixed_options)} root@{self._host}:{src} {dst}")


class Communication:
  """XML-RPC client communication."""

  def __init__(self, ip, port=5566):
    """Initialize the XML-RPC client.
    Args:
        ip: The DUT IP address.
        port: The DUT XML-RPC listening port.
    """
    self._ip = ip
    self._port = port
    self.proxy = xmlrpc.client.ServerProxy(f'http://{ip}:{port}')
    self.ssh_client = SSHClient(ip)

  def ItemIsRunning(self, item):
    """Check if the test is running.
    Args:
      item: The test item name.
    Returns:
        True if the test is running, False otherwise.
    """
    if not PingIsSuccessful(self._ip):
      logging.error('%s is not reachable.', self._ip)
      return False
    output = SimpleCommand(
        self.ssh_client.SSHCommand('factory run-status'), print_output=False)
    return 'RUNNING' in output and item in output and len(
        output.split(item.split('.')[0])) == 2

  def tearDown(self):
    """Tear down the test."""
    self.proxy.tearDown()

  def Init(self, item):
    """Initialize the DUT for the test, if the test is not running, start it."""
    if not self.ItemIsRunning(item):
      SimpleCommand(
          self.ssh_client.SSHCommand(f'factory run {item}'), print_output=False)
      time.sleep(0.3)

  @staticmethod
  def SetupSSHIdentity():
    """Setup ssh access."""
    SetupSSHIdentityFile()

  def RunCommand(self, cmd):
    """Run a command on the DUT.
    Args:
        cmd: The command to run.
    Returns:
        The output of the command if print_output is True, otherwise the return
        code of the command.
    """
    return SimpleCommand(self.ssh_client.SSHCommand(cmd), print_output=True)

  def RunCommandWithoutOutput(self, cmd):
    """Run a command on the remote host and return the return code."""
    return SimpleCommandWithoutOutput(self.ssh_client.SSHCommand(cmd))

  def Push(self, src, dst):
    """Push a file or directory to the remote host.
    Args:
      src: The source file or directory.
      dst: The destination file or directory.
    """
    return SimpleCommand(self.ssh_client.SCPPushCommand(src, dst))

  def Pull(self, src, dst):
    """Pull a file or directory from the remote host.
    Args:
      src: The source file or directory.
      dst: The destination file or directory.
    """
    logging.info('Pull %s to %s', src, dst)
    return SimpleCommand(self.ssh_client.SCPPullCommand(src, dst))

  def ShowPattern(self, pattern):
    """Show the css pattern.
    Args:
        pattern: The pattern to show.
    """
    self.proxy.ShowPattern(pattern)

  def GetSerialNumber(self):
    """Get the DUT serial number.
    Returns:
        The DUT device data serial number.
    """
    print(f'Serial Number: {self.proxy.GetSerialNumber()}')
    self.proxy.GetSerialNumber()

  def FailTest(self, reason):
    """Fail the test.
    Args:
        reason: The reason to fail the test.
    """
    self.proxy.FailTest(reason)

  def ShowImage(self, image):
    """Show the image.
    Args:
        image: The image name to display on the DUT.
    """
    self.proxy.ShowImage(image)

  def SetDisplayBrightness(self, brightness):
    """Set the display backlight brightness, 0.0 to 1.0, DUT default is 0.5.
    Args:
        brightness: The brightness to set.
    """
    self.proxy.SetDisplayBrightness(float(brightness))

  def SetKeyboardBacklight(self, brightness):
    """Set the keyboard backlight brightness, 0 to 100, DUT default is 0.
    Args:
        brightness: The brightness to set.
    """
    self.RunCommand(f'ectool pwmsetkblight {brightness}')
