# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implementation of cros.factory.device.device_types.DeviceLink on local
system."""

import pipes
import shutil
import subprocess
from typing import IO, Any, List, Optional, Union

from cros.factory.device import device_types
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


class LocalLink(device_types.DeviceLink):
  """Runs locally on a device."""

  def __init__(self, shell_path: Optional[str] = None):
    """Link constructor.

    Args:
      shell_path: A string for the path of default shell.
    """
    self._shell_path = shell_path

  @type_utils.Overrides
  def Push(self, local: str, remote: str) -> None:
    """See DeviceLink.Push"""
    shutil.copy(local, remote)

  def PushDirectory(self, local: str, remote: str) -> None:
    """See DeviceLink.PushDirectory"""
    shutil.copytree(local, remote)

  @type_utils.Overrides
  def Pull(self, remote: str, local: Optional[str] = None):
    """See DeviceLink.Pull"""
    if local is None:
      return file_utils.ReadFile(remote)

    shutil.copy(remote, local)
    return None

  @type_utils.Overrides
  def PullDirectory(self, remote: str, local: str) -> None:
    shutil.copytree(remote, local)

  @type_utils.Overrides
  def Shell(self, command: Union[str, List[str]], stdin: Union[None, int,
                                                               IO[Any]] = None,
            stdout: Union[None, int, IO[Any]] = None,
            stderr: Union[None, int, IO[Any]] = None, cwd: Optional[str] = None,
            encoding: Optional[str] = 'utf-8') -> subprocess.Popen:
    """See DeviceLink.Shell"""

    # On most remote links, we always need to execute the commands via shell. To
    # unify the behavior we should always run the command using shell even on
    # local links. Ideally python should find the right shell interpreter for
    # us, however at least in Python 2.x, it was unfortunately hard-coded as
    # (['/bin/sh', '-c'] + args) when shell=True. In other words, if your
    # default shell is not sh or if it is in other location (for instance,
    # Android only has /system/bin/sh) then calling Popen may give you 'No such
    # file or directory' error.

    if not isinstance(command, str):
      command = ' '.join(pipes.quote(param) for param in command)

    if self._shell_path:
      # Shell path is specified and we have to quote explicitly.
      command = [self._shell_path, '-c', command]
      shell = False
    else:
      # Trust default path specified by Python runtime. Useful for non-POSIX
      # systems like Windows.
      shell = True
    return process_utils.Spawn(command, shell=shell, cwd=cwd, close_fds=True,
                               stdin=stdin, stdout=stdout, stderr=stderr,
                               encoding=encoding)

  @type_utils.Overrides
  def IsReady(self) -> bool:
    """See DeviceLink.IsReady"""
    return True

  @type_utils.Overrides
  def IsLocal(self) -> bool:
    """See DeviceLink.IsLocal"""
    return True
