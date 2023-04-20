# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implementation of cros.factory.device.device_types.DeviceLink using ADB."""

import logging
import os
import pipes
import subprocess
import tempfile
from typing import IO, Any, Optional, Sequence, Union
import uuid

from cros.factory.device import device_types
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


class LegacyADBProcess:
  """Wrapper for devices and clients with version < Android N."""

  def __init__(self, proxy_object, session_id):
    self._proxy_object = proxy_object
    self._session_id = session_id
    self._exit_code = None

  def __getattr__(self, name):
    if name == 'returncode':
      return self._get_dut_returncode()
    return getattr(self._proxy_object, name)

  def _get_dut_returncode(self):
    # The returncode will only be 0 if ADB channel was created and then closed
    # successfully, not the real status of remote process.
    if self._proxy_object.returncode != 0:
      return self._proxy_object.returncode

    # Use cached exit code if possible.
    if self._exit_code is not None:
      return self._exit_code

    # To get real exit code, we want to find out using logcat (see
    # implementation in ADBLink).
    result = process_utils.CheckOutput(
        f'adb logcat -d -b main -s {self._session_id}', shell=True).strip()
    logging.debug('%s: Exit Results = %s', type(self), result)

    # Format: I/session_id(PID): EXITCODE
    # Example: I/64eeb606-fdcf-11e4-b63f-80c16efb89a5( 3439): 0
    self._exit_code = int(result.rpartition(':')[2].strip())
    return self._exit_code


def RawADBProcess(proxy_object, session_id):
  """A dummy wrapper to return first input (process) argument directly.

  Similar to LegacyADBProcess. Can be used if both ADB client and DUT Android
  devices are >= Android N.
  """
  del session_id  # Unused
  return proxy_object


class ADBLink(device_types.DeviceLink):
  """A device that is connected via ADB interface.

  Args:
    temp_dir: A string for temp folder, usually /data/local/tmp on Android.
    exit_code_hack: Boolean to indicate if we should enable the hack to get
        command execution exit code. Set to True if either your ADB client or
        Android device are using a version smaller than N release.
  """

  def __init__(self, temp_dir='/data/local/tmp', exit_code_hack=True):
    self._temp_dir = temp_dir
    self._exit_code_hack = exit_code_hack

  @type_utils.Overrides
  def Push(self, local: str, remote: str) -> None:
    """See DeviceLink.Push"""
    subprocess.check_output(['adb', 'push', local, remote],
                            stderr=subprocess.STDOUT)

  @type_utils.Overrides
  def PushDirectory(self, local: str, remote: str) -> None:
    """See DeviceLink.PushDirectory"""
    return self.Push(local, remote)

  @type_utils.Overrides
  def Pull(self, remote: str, local: Optional[str] = None):
    """See DeviceLink.Pull"""
    if local is None:
      with file_utils.UnopenedTemporaryFile() as path:
        self.Pull(remote, path)
        return file_utils.ReadFile(path)

    subprocess.check_output(['adb', 'pull', remote, local],
                            stderr=subprocess.STDOUT)
    return None

  @type_utils.Overrides
  def PullDirectory(self, remote: str, local: str) -> None:
    # TODO(wdzeng): implementation
    raise NotImplementedError

  @type_utils.Overrides
  def Shell(self, command: Union[str,
                                 Sequence[str]], stdin: Union[None, int,
                                                              IO[Any]] = None,
            stdout: Union[None, int,
                          IO[Any]] = None, stderr: Union[None, int,
                                                         IO[Any]] = None,
            cwd: Optional[str] = None, encoding: Optional[str] = 'utf-8'):
    """See DeviceLink.Shell"""
    # ADB shell does not provide interactive shell, which means we are not
    # able to send stdin data in an interactive way (
    # https://code.google.com/p/android/issues/detail?id=74856). As described
    # in the issue, this and the above exit code bugs will be fixed in the
    # future build. Now we use a temp file and print warning message when use
    # PIPE to avoid unexpected bug.

    session_id = str(uuid.uuid1())

    # Convert list-style commands to single string because we need to run
    # multiple commands in same session (and needs shell=True).
    if not isinstance(command, str):
      command = ' '.join(pipes.quote(param) for param in command)
    if cwd:
      command = f'cd {pipes.quote(cwd)} ; {command}'

    # ADB protocol currently mixes stderr and stdout in same channel (i.e., the
    # stdout by adb command has both stderr and stdout from device) so we do
    # want to make them different.
    redirections = ''
    if stderr is None:
      redirections += '2>/dev/null'
    elif stderr == subprocess.STDOUT:
      pass  # No need to redirect because that's the default behavior.
    else:
      # TODO(hungte) Create a temp file remotely and store contents there, or
      # figure out a way to return by logcat.
      redirections += '2>/dev/null'
      logging.warning('%s: stderr redirection is not supported yet.',
                      type(self).__name__)

    delete_tmps = ''
    if stdin is not None:
      if stdin == subprocess.PIPE:
        logging.warning('%s: stdin PIPE is not supported yet.',
                        type(self).__name__)
      else:
        with tempfile.NamedTemporaryFile() as tmp_file:
          data: bytes
          if isinstance(stdin, int):
            # 256 MiB should be enough.
            data = os.read(stdin, 256 * 1024 * 1024)
          else:
            data = stdin.read()
          tmp_file.write(data)
          tmp_file.flush()

          filename = os.path.basename(tmp_file.name)

          # We don't know the correct way to create true tmp file on the device
          # since it differs from board to board. Use session_id in the
          # filename to avoid collision as much as possible.
          target_tmp_file = os.path.join(self._temp_dir,
                                         f'{session_id}.{filename}')

          self.Push(tmp_file.name, target_tmp_file)
          redirections += f' <{target_tmp_file}'
          delete_tmps = f'rm -f {target_tmp_file}'

    if self._exit_code_hack:
      # ADB shell has a bug that exit code is not correctly returned (
      #  https://code.google.com/p/android/issues/detail?id=3254 ). Many public
      # implementations work around that by adding an echo and then parsing the
      # execution results. To avoid problems in redirection, we do this slightly
      # different by using the log service and "logcat" ADB feature.
      command = [
          'adb', 'shell',
          f'( {command} ) {redirections}; log -t {session_id} $?; {delete_tmps}'
      ]
      wrapper = LegacyADBProcess
    else:
      command = ['adb', 'shell', f'( {command} ) {redirections}; {delete_tmps}']
      wrapper = RawADBProcess

    logging.debug('ADBLink: Run %r', command)
    return wrapper(
        subprocess.Popen(command, shell=False, close_fds=True, stdin=stdin,
                         stdout=stdout, stderr=stderr, encoding=encoding),
        session_id)

  @type_utils.Overrides
  def IsReady(self) -> bool:
    """See DeviceLink.IsReady"""
    return process_utils.CheckOutput(['adb', 'get-state']).strip() == 'device'

  @type_utils.Overrides
  def IsLocal(self) -> bool:
    """See DeviceLink.IsLocal"""
    return False
