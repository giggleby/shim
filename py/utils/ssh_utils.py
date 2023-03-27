# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for ssh and rsync.

This module is intended to work with Chrome OS DUTs only as it uses Chrome OS
testing_rsa and partner_testing_rsa identities.
"""

import abc
import logging
import os
import pipes
import queue
import subprocess
import threading
import time
from typing import List, Optional, Tuple, Union  # pylint: disable=unused-import

from . import process_utils
from . import sync_utils
from . import type_utils


_SSHKEYS_DIR = os.path.realpath(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)), '../../misc/sshkeys'))


def _GetIdentityFiles() -> List[str]:
  """Fetches all paths of available private keys under misc/sshkeys."""

  identity_files = []
  for identity_file in os.listdir(_SSHKEYS_DIR):
    # Ignore public keys.
    if not identity_file.endswith('.pub'):
      identity_files.append(os.path.join(_SSHKEYS_DIR, identity_file))

  return identity_files


_STANDARD_SSH_OPTIONS = [
    '-o', 'UserKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR', '-o',
    'User=root', '-o', 'StrictHostKeyChecking=no', '-o', 'Protocol=2', '-o',
    'BatchMode=yes', '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=180',
    '-o', 'ServerAliveCountMax=3', '-o', 'ConnectionAttempts=4'
]


class ISSHRunner(abc.ABC):
  """An abstract class that runs a command via SSH on a target device."""

  @abc.abstractmethod
  def Spawn(self, command: Union[str, List[str]], **kwargs) -> subprocess.Popen:
    """Executes a command or a script in the device.

    Args:
      command: The script content if given as a string, or the command if given
               as a list of string.
      kwargs: See docstring of process_utils.Spawn.

    Returns: The SSH process.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def SpawnRsyncAndPush(self, src: str, dest: str,
                        **kwargs) -> subprocess.Popen:
    """Copies a file or directory from local to remote.

    Arguments `src` and `dest` are directly passed to rsync command, so make
    sure to check if a trailing slash is required.

    Args:
      src: The path of local file or directory.
      dest: The path of remote file or directory.
      kwargs: See docstring of Spawn.

    Returns: The rsync process.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def SpawnRsyncAndPull(self, src: str, dest: str,
                        **kwargs) -> subprocess.Popen:
    """Copies a file or directory from remote to local.

    Arguments `src` and `dest` are directly passed to rsync command, so make
    sure to check if a trailing slash is required.

    Args:
      src: The path of remote file or directory.
      dest: The path of local file or directory.
      kwargs: See docstring of Spawn.

    Returns: The rsync process.
    """
    raise NotImplementedError


class SSHRunner(ISSHRunner):
  """A class that implements `ISSHRunner`."""

  def __init__(self, host: str, user: Optional[str] = 'root',
               port: Optional[int] = None,
               identity_files: Optional[List[str]] = None):
    self.host = host
    self.user = user
    self.port = port
    self._identity_files = identity_files or _GetIdentityFiles()

  def _GetDeviceSignature(self, include_port=False) -> str:
    sig = f'{self.user}@{self.host}' if self.user else self.host
    if include_port and self.port:
      sig += f':{self.port}'
    return sig

  def _GetSSHOptions(self) -> List[str]:
    identity_args: List[str] = []
    for identity_file in self._identity_files:
      identity_args += ['-o', f'IdentityFile={identity_file}']

    port_args: List[str] = ['-p', str(self.port)] if self.port else []

    return port_args + identity_args + _STANDARD_SSH_OPTIONS

  def _GetSSHCommand(
      self, command: Union[None, str, List[str]],
      additional_ssh_options: Optional[List[str]] = None) -> List[str]:
    if additional_ssh_options is None:
      additional_ssh_options = []
    if isinstance(command, list):
      if len(command) == 0:
        raise ValueError('Command as a list must not be empty.')
      command = ' '.join(map(pipes.quote, command))

    sig = self._GetDeviceSignature()
    command = [command] if command is not None else []
    return ['ssh'
           ] + self._GetSSHOptions() + additional_ssh_options + [sig] + command

  def _BuildRsyncCommand(self, src: str, dest: str, is_push: bool) -> List[str]:
    if is_push:
      dest = f'{self._GetDeviceSignature()}:{dest}'
    else:
      src = f'{self._GetDeviceSignature()}:{src}'

    ssh_options = 'ssh ' + (' '.join(map(pipes.quote, self._GetSSHOptions())))
    return ['rsync', '-az', '-e', ssh_options, src, dest]

  @type_utils.Overrides
  def Spawn(self, command: Union[str, List[str]],
            **kwargs) -> process_utils.ExtendedPopen:
    """See ISSHRunner.Spawn."""
    ssh_command = self._GetSSHCommand(command)
    return process_utils.Spawn(ssh_command, **kwargs)

  @type_utils.Overrides
  def SpawnRsyncAndPush(self, src: str, dest: str,
                        **kwargs) -> subprocess.Popen:
    """See ISSHRunner.SpawnRsyncAndPush."""
    rsync_command = self._BuildRsyncCommand(src, dest, True)
    return process_utils.Spawn(rsync_command, **kwargs)

  @type_utils.Overrides
  def SpawnRsyncAndPull(self, src: str, dest: str,
                        **kwargs) -> subprocess.Popen:
    """See ISSHRunner.SpawnRsyncAndPull."""
    rsync_command = self._BuildRsyncCommand(src, dest, False)
    return process_utils.Spawn(rsync_command, **kwargs)


class ControlMasterSSHRunner(ISSHRunner):
  """A class that implements `ISSHRunner`.

  When running SSH and rsync commands, make use of the control master feature to
  decrease network traffic.
  """

  def __init__(self, host: str, user: Optional[str] = 'root',
               port: Optional[int] = None,
               identity_files: Optional[List[str]] = None):
    self._inner_ssh_runner = SSHRunner(host=host, user=user, port=port,
                                       identity_files=identity_files)
    self._watcher = _SSHControlMasterWatcher(self._inner_ssh_runner)

  def _MonitorProcess(self, proc: subprocess.Popen) -> None:
    self._watcher.Start()
    self._watcher.AddProcess(proc.pid, os.getpid())

  @type_utils.Overrides
  def Spawn(self, command: Union[str, List[str]], **kwargs) -> subprocess.Popen:
    """See ISSHRunner.Spawn."""
    ssh_process = self._inner_ssh_runner.Spawn(command, **kwargs)
    self._MonitorProcess(ssh_process)
    return ssh_process

  @type_utils.Overrides
  def SpawnRsyncAndPush(self, src: str, dest: str,
                        **kwargs) -> subprocess.Popen:
    """See ISSHRunner.SpawnRsyncAndPush."""
    rsync_process = self._inner_ssh_runner.SpawnRsyncAndPush(
        src, dest, **kwargs)
    self._MonitorProcess(rsync_process)
    return rsync_process

  @type_utils.Overrides
  def SpawnRsyncAndPull(self, src: str, dest: str,
                        **kwargs) -> subprocess.Popen:
    """See ISSHRunner.SpawnRsyncAndPull."""
    rsync_process = self._inner_ssh_runner.SpawnRsyncAndPull(
        src, dest, **kwargs)
    self._MonitorProcess(rsync_process)
    return rsync_process


class _SSHControlMasterWatcher:

  def __init__(self, ssh_runner: SSHRunner):
    self._ssh_runner = ssh_runner
    self._thread = threading.Thread(target=self._Run)
    self._proc_queue: 'queue.Queue[Tuple[int, Optional[int]]]' = queue.Queue()
    self._link_class_name = self._ssh_runner.__class__.__name__

  def IsRunning(self) -> bool:
    """Checks if the watcher is running."""
    if not self._thread:
      return False
    if not self._thread.is_alive():
      self._thread = None
      return False
    return True

  def Start(self) -> None:
    """Starts the watcher if it is not yet started."""
    if self.IsRunning():
      return

    self._thread = process_utils.StartDaemonThread(target=self._Run)

  def AddProcess(self, pid: int, ppid: Optional[int] = None) -> None:
    """Adds an SSH process to be monitored.

    If any of added SSH process is still running, the watcher will keep
    monitoring network connectivity. If network is down, control master will be
    killed.

    Args:
      pid: PID of process using SSH ppid: parent PID of given process
    """
    if not self.IsRunning():
      logging.warning('Watcher is not running, so %d is not added.', pid)
      return

    self._proc_queue.put((pid, ppid))

  def _Run(self):
    logging.debug('Start monitoring control master.')
    # pylint: disable=protected-access
    device_address = self._ssh_runner._GetDeviceSignature(include_port=False)

    def _IsControlMasterRunning() -> bool:
      # pylint: disable=protected-access
      ssh_command = self._ssh_runner._GetSSHCommand(
          command=None, additional_ssh_options=['-O', 'check'])
      return process_utils.Spawn(ssh_command, call=True).returncode == 0

    def _StopControlMaster() -> bool:
      # pylint: disable=protected-access
      ssh_command = self._ssh_runner._GetSSHCommand(
          command=None, additional_ssh_options=['-O', 'exit'])
      return process_utils.Spawn(ssh_command, call=True).returncode == 0

    def _CallTrue() -> bool:
      ssh_command = self._ssh_runner._GetSSHCommand(command='true')
      ssh_proc = process_utils.Spawn(ssh_command)
      time.sleep(1)
      returncode = ssh_proc.poll()
      if returncode != 0:
        ssh_proc.kill()
        return False
      return True

    def _PollingCallback(is_process_alive: bool) -> Union[bool, None]:
      if not is_process_alive:
        return True  # returns True to stop polling

      try:
        if not _IsControlMasterRunning():
          logging.info('Control master is not running, skipped.')
          return False

        if not _CallTrue():
          logging.info('Lost connection, stopping control master.')
          _StopControlMaster()

        return None

      except Exception:
        # TODO(wdzeng): when will this exception be raised?
        logging.info('Monitoring %s to %s', self._link_class_name,
                     device_address, exc_info=True)
        return False

    while True:
      # get a new process from queue to monitor
      # since queue.get will block if queue is empty, we don't need to sleep
      pid, ppid = self._proc_queue.get()
      logging.debug('start monitoring control master until %d terminates', pid)
      sync_utils.PollForCondition(
          lambda: process_utils.IsProcessAlive(pid, ppid),
          condition_method=_PollingCallback, timeout_secs=None,
          poll_interval_secs=1)
