# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The abstraction of minimal functions needed to access a system."""

import glob
import logging
import pipes
import shutil
import subprocess
import tempfile
from typing import IO, Any, List, Optional, Union, overload

from . import file_utils
from . import process_utils


# Use process_utils.CalledProcessError for invocation exceptions.
CalledProcessError = process_utils.CalledProcessError


def CommandsToShell(command: Union[str, List[str]]) -> str:
  """Joins commands to a shell command.

  Args:
    command: See the description of command of SystemInterface.Popen.
  """
  if isinstance(command, str):
    return command
  return ' '.join(map(pipes.quote, command))


class SystemInterface:
  """An interface for accessing a system."""

  def ReadFile(self, path: str, count: Optional[int] = None,
               skip: Optional[int] = None) -> str:
    """Returns file contents on target device.

    By default the "most-efficient" way of reading file will be used, which may
    not work for special files like device node or disk block file. Use
    ReadSpecialFile for those files instead.

    Meanwhile, if count or skip is specified, the file will also be fetched by
    ReadSpecialFile.

    Args:
      path: A string for file path on target device.
      count: Number of bytes to read. None to read whole file.
      skip: Number of bytes to skip before reading. None to read from beginning.

    Returns:
      A string as file contents.
    """
    if count is None and skip is None:
      return file_utils.ReadFile(path)
    return self.ReadSpecialFile(path, count=count, skip=skip)

  @overload
  def ReadSpecialFile(self, path: str, count: Optional[int],
                      skip: Optional[int], encoding: None) -> bytes:
    ...

  @overload
  def ReadSpecialFile(self, path: str, count: Optional[int] = None,
                      skip: Optional[int] = None,
                      encoding: str = 'utf-8') -> str:
    ...

  def ReadSpecialFile(self, path: str, count: Optional[int] = None,
                      skip: Optional[int] = None,
                      encoding: Optional[str] = 'utf-8'):
    """Returns contents of special file on target device.

    Reads special files (device node, disk block, or sys driver files) on device
    using the most portable approach.

    Args:
      path: A string for file path on target device.
      count: Number of bytes to read. None to read whole file.
      skip: Number of bytes to skip before reading. None to read from beginning.
      encoding: The encoding of the file content.

    Returns:
      A string or bytes as file contents.
    """
    with open(path, 'rb') as f:
      if skip:
        try:
          f.seek(skip)
        except IOError:
          f.read(skip)
      x = f.read() if count is None else f.read(count)
      return x.decode(encoding) if encoding else x

  def WriteFile(self, path: str, content: str) -> None:
    """Writes some content into file on target device.

    Args:
      path: A string for file path on target device.
      content: A string to be written into file.
    """
    file_utils.WriteFile(path, content)

  def WriteSpecialFile(self, path: str, content: str) -> None:
    """Writes some content into a special file on target device.

    Args:
      path: A string for file path on target device.
      content: A string to be written into file.
    """
    self.WriteFile(path, content)

  def SendDirectory(self, local: str, remote: str) -> None:
    """Copies a local directory to target device.

    `local` should be a local directory, and `remote` should be a non-existing
    file path on target device.

    Example::

     SendDirectory('/path/to/local/dir', '/remote/path/to/some_dir')

    Will create directory `some_dir` under `/remote/path/to` and copy
    files and directories under `/path/to/local/dir/` to `some_dir`.

    Args:
      local: A string for directory path in local.
      remote: A string for directory path on remote device.
    """
    shutil.copytree(local, remote)

  def SendFile(self, local: str, remote: str) -> None:
    """Copies a local file to target device.

    Args:
      local: A string for file path in local.
      remote: A string for file path on remote device.
    """
    shutil.copy(local, remote)

  def Popen(self, command: Union[str, List[str]], stdin: Union[None, int,
                                                               IO[Any]] = None,
            stdout: Union[None, int, IO[Any]] = None,
            stderr: Union[None, int, IO[Any]] = None, cwd: Optional[str] = None,
            log=False, encoding: Optional[str] = 'utf-8') -> subprocess.Popen:
    """Executes a command on target device using subprocess.Popen convention.

    Compare to `subprocess.Popen`, the argument `shell=True/False` is not
    available for this function.  When `command` is a list, it treats each
    item as a command to be invoked.  When `command` is a string, it treats
    the string as a shell script to invoke.

    Args:
      command: A string or a list of strings for command to execute.
      stdin: A file object to override standard input.
      stdout: A file object to override standard output.
      stderr: A file object to override standard error.
      cwd: The working directory for the command.
      log: True (for logging.info) or a logger object to keep logs before
          running the command.
      encoding: Same as subprocess.Popen, we will use `utf-8` as default to make
          it output str type.

    Returns:
      An object similar to subprocess.Popen.
    """
    command = CommandsToShell(command)
    if log:
      logger = logging.info if log is True else log
      logger('%s Running: %r', type(self), command)
    return process_utils.Spawn(command, cwd=cwd, shell=True, stdin=stdin,
                               stdout=stdout, stderr=stderr, encoding=encoding)

  def Call(self, *args, **kargs) -> int:
    """Executes a command on target device, using subprocess.call convention.

    The arguments are explained in Popen.

    Do not override this function. The behavior of this function depends on the
    underlying device (e.g. SSH-connected device or local device), which has
    been well-handled by Popen.

    Returns:
      Exit code from executed command.
    """
    process = self.Popen(*args, **kargs)
    process.wait()
    return process.returncode

  def CheckCall(self, command: Union[str,
                                     List[str]], stdin: Union[None, int,
                                                              IO[Any]] = None,
                stdout: Union[None, int,
                              IO[Any]] = None, stderr: Union[None, int,
                                                             IO[Any]] = None,
                cwd: Optional[str] = None, log=False) -> int:
    """Executes a command on device, using subprocess.check_call convention.

    Do not override this function. The behavior of this function depends on the
    underlying device (e.g. SSH-connected device or local device), which has
    been well-handled by Popen.

    Args:
      command: A string or a list of strings for command to execute.
      stdin: A file object to override standard input.
      stdout: A file object to override standard output.
      stderr: A file object to override standard error.
      cwd: The working directory for the command.
      log: True (for logging.info) or a logger object to keep logs before
          running the command.

    Returns:
      Exit code from executed command, which is always 0.

    Raises:
      CalledProcessError if the exit code is non-zero.
    """
    exit_code = self.Call(command, stdin=stdin, stdout=stdout, stderr=stderr,
                          cwd=cwd, log=log)
    if exit_code != 0:
      raise CalledProcessError(returncode=exit_code, cmd=command)
    return 0

  @overload
  def CheckOutput(self, command: Union[str,
                                       List[str]], stdin: Union[None, int,
                                                                IO[Any]] = None,
                  stderr: Union[None, int,
                                IO[Any]] = None, cwd: Optional[str] = None,
                  log=False, encoding: None = None) -> bytes:
    ...

  @overload
  def CheckOutput(self, command: Union[str,
                                       List[str]], stdin: Union[None, int,
                                                                IO[Any]] = None,
                  stderr: Union[None, int,
                                IO[Any]] = None, cwd: Optional[str] = None,
                  log=False, encoding: str = 'utf-8') -> str:
    ...

  def CheckOutput(self, command: Union[str, List[str]],
                  stdin: Union[None, int,
                               IO[Any]] = None, stderr: Union[None, int,
                                                              IO[Any]] = None,
                  cwd: Optional[str] = None, log=False,
                  encoding: Optional[str] = 'utf-8') -> Union[str, bytes]:
    """Executes a command on device, using subprocess.check_output convention.

    Do not override this function. The behavior of this function depends on the
    underlying device (e.g. SSH-connected device or local device), which has
    been well-handled by Popen.

    Args:
      command: A string or a list of strings for command to execute.
      stdin: A file object to override standard input.
      stderr: A file object to override standard error.
      cwd: The working directory for the command.
      log: True (for logging.info) or a logger object to keep logs before
          running the command.
      encoding: The name of the encoding used to decode the command's output.
          Set to ``None`` to read as byte.

    Returns:
      The output on STDOUT from executed command.

    Raises:
      CalledProcessError if the exit code is non-zero.
    """
    mode = 'w+b' if encoding is None else 'w+'
    with tempfile.TemporaryFile(mode, encoding=encoding) as stdout:
      exit_code = self.Call(command, stdin=stdin, stdout=stdout, stderr=stderr,
                            cwd=cwd, log=log, encoding=encoding)
      stdout.flush()
      stdout.seek(0)
      output = stdout.read()
    if exit_code != 0:
      raise CalledProcessError(returncode=exit_code, cmd=command, output=output)
    return output

  def CallOutput(self, *args, **kargs) -> Union[None, bytes, str]:
    """Runs the command on device and returns standard output if success.

    Do not override this function. The behavior of this function depends on the
    underlying device (e.g. SSH-connected device or local device), which has
    been well-handled by Popen.

    Returns:
      If command exits with zero (success), return the standard output;
      otherwise None. If the command didn't output anything then the result is
      empty string.
    """
    try:
      return self.CheckOutput(*args, **kargs)
    except CalledProcessError:
      return None

  def Glob(self, pattern: str) -> List[str]:
    """Finds files on target device by pattern, similar to glob.glob.

    Args:
      pattern: A file path pattern (allows wild-card '*' and '?).

    Returns:
      A list of files matching pattern on target device.
    """
    return glob.glob(pattern)
