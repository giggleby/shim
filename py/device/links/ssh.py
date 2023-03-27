# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implementation of cros.factory.device.device_types.DeviceLink using SSH."""

import collections
import enum
import logging
import pipes
import subprocess
import threading
from typing import IO, Any, List, Optional, Union

from cros.factory.device import device_types
from cros.factory.test import state
from cros.factory.test.utils import dhcp_utils
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import ssh_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


_DEVICE_DATA_KEY = 'DYNAMIC_SSH_TARGET_IP'


class ClientNotExistError(Exception):

  def __str__(self):
    return 'There is no DHCP client registered.'


class RsyncExitCode(int, enum.Enum):
  ERROR_SOCKET_IO = 10
  TIMEOUT_DATA_SEND_RECEIVE = 30
  TIMEOUT_DAEMON_CONNECTION = 35


class SSHLink(device_types.DeviceLink):
  """A DUT target that is connected via SSH interface.

  Attributes:
    host: A string for SSH host, if it's None, will get from shared data.
    user: A string for the user account to login. Defaults to 'root'.
    port: An integer for the SSH port on remote host.
    identity: A list of strings indicating paths to the identity files used.
    use_ping: A bool, whether using ping(8) to check connection with DUT or not.
              If it's False, will use ssh(1) instead. This is useful if DUT
              drops incoming ICMP packets.
    connect_timeout: An integer for ssh(1) connection timeout in seconds.
    control_persist: An integer for ssh(1) to keep master connection remain
              opened for given seconds, or None to not using master control.

  dut_options example:
    dut_options for fixed-IP:
      {
        'board_class': 'CoolBoard',
        'link_class': 'SSHLink',
        'host': '1.2.3.4',
        'identity': '/path/to/identity/file'
        'start_dhcp_server': False
      }
    dut_options for DHCP:
      {
        'board_class': 'CoolBoard',
        'link_class': 'SSHLink',
        'host': None,
        'identity': '/path/to/identity/file',
        'start_dhcp_server': True,
        'dhcp_server_args': {
          'lease_time': 3600,
          'interface_blocklist_file': '/path/to/blocklist/file',
          'exclude_ip_prefix': [('10.0.0.0', 24), ...],
          # the following three properties can only be set in python script,
          # not in environment variable (CROS_FACTORY_DUT_OPTIONS)
          'on_add': None,
          'on_old': None,
          'on_del': None,
        }
      }
  """

  def __init__(self, host: Optional[str] = None, user: Optional[str] = 'root',
               port: Optional[int] = 22, identity: Union[None, str,
                                                         List[str]] = None,
               use_ping=True, connect_timeout=1, control_persist=300):
    self._host = host
    self.user = user
    self.port = port
    self.identity = [identity] if isinstance(identity, str) else identity or []
    self._ssh_runner = ssh_utils.SSHRunner(host=self.host, user=self.user,
                                           port=self.port,
                                           identity_files=self.identity)
    self.use_ping = use_ping
    self.connect_timeout = connect_timeout
    self.control_persist = control_persist

    self._state = state.GetInstance()

  @property
  def host(self) -> str:
    if self._host is None:
      if not state.DataShelfHasKey(_DEVICE_DATA_KEY):
        raise ClientNotExistError
      return state.DataShelfGetValue(_DEVICE_DATA_KEY)  # type: ignore
    return self._host

  def _DoRsync(self, src: str, dst: str, is_push: bool) -> None:
    """Runs rsync given source and destination path and retries when failing."""

    def _TryOnce():
      if is_push:
        rsync_process = self._ssh_runner.SpawnRsyncAndPush(src, dst, call=True)
      else:
        rsync_process = self._ssh_runner.SpawnRsyncAndPull(src, dst, call=True)

      returncode = rsync_process.returncode
      exitcode_need_retry = [
          RsyncExitCode.ERROR_SOCKET_IO,
          RsyncExitCode.TIMEOUT_DAEMON_CONNECTION,
          RsyncExitCode.TIMEOUT_DATA_SEND_RECEIVE
      ]
      return False if returncode in exitcode_need_retry else (True, returncode)

    def _Callback(retry_time, max_retry_times):
      logging.info('rsync: src=%s, dst=%s (%d/%d)', src, dst, retry_time,
                   max_retry_times)

    result = sync_utils.Retry(3, 0.1, callback=_Callback, target=_TryOnce)
    returncode = result[1] if result else 255
    if returncode:
      raise subprocess.CalledProcessError(
          returncode, f'rsync failed: src={src}, dst={dst}')

  @type_utils.Overrides
  def Push(self, local: str, remote: str) -> None:
    """See DeviceLink.Push"""
    self._DoRsync(local, remote, True)

  @type_utils.Overrides
  def PushDirectory(self, local: str, remote: str) -> None:
    """See DeviceLink.PushDirectory"""
    # Copy the directory itself, so add a trailing slash.
    if not local.endswith('/'):
      local = local + '/'
    self._DoRsync(local, remote, True)

  @type_utils.Overrides
  def Pull(self, remote: str,
           local: Optional[str] = None) -> Union[None, str, bytes]:
    """See DeviceLink.Pull"""
    if local is None:
      with file_utils.UnopenedTemporaryFile() as path:
        self._DoRsync(remote, path, False)
        return file_utils.ReadFile(path)

    self._DoRsync(remote, local, False)
    return None

  @type_utils.Overrides
  def PullDirectory(self, remote: str, local: str) -> None:
    # Copy the directory itself, so add a trailing slash.
    if not remote.endswith('/'):
      remote = remote + '/'
    self._DoRsync(remote, local, is_push=False)

  @type_utils.Overrides
  def Shell(self, command: Union[str, List[str]], stdin: Union[None, int,
                                                               IO[Any]] = None,
            stdout: Union[None, int, IO[Any]] = None,
            stderr: Union[None, int, IO[Any]] = None, cwd: Optional[str] = None,
            encoding: Optional[str] = 'utf-8') -> process_utils.ExtendedPopen:
    """See DeviceLink.Shell"""
    if not isinstance(command, str):
      command = ' '.join(map(pipes.quote, command))

    if cwd:
      command = f'cd {pipes.quote(cwd)} ; {command}'

    logging.debug('SSHLink: Run [%r]', command)
    proc = self._ssh_runner.Spawn(command, shell=False, close_fds=True,
                                  stdin=stdin, stdout=stdout, stderr=stderr,
                                  encoding=encoding)
    return proc

  @type_utils.Overrides
  def IsReady(self) -> bool:
    """See DeviceLink.IsReady"""
    try:
      if self.use_ping:
        proc = process_utils.Spawn(['ping', '-w', '1', '-c', '1', self.host],
                                   call=True)
      else:
        proc = self._ssh_runner.Spawn('true', call=True)
      return proc.returncode == 0
    except Exception:
      return False

  _dhcp_manager = None
  _dhcp_manager_lock = threading.Lock()

  @type_utils.Overrides
  def IsLocal(self) -> bool:
    """See DeviceLink.IsLocal"""
    return False

  @classmethod
  def SetLinkIP(cls, ip):
    state.DataShelfSetValue(_DEVICE_DATA_KEY, ip)

  @classmethod
  def ResetLinkIP(cls):
    if state.DataShelfHasKey(_DEVICE_DATA_KEY):
      state.DataShelfDeleteKeys(_DEVICE_DATA_KEY)

  @classmethod
  def PrepareLink(cls, start_dhcp_server=True,
                  start_dhcp_server_after_ping=None, dhcp_server_args=None):
    """Prepare for SSHLink connection

    Arguments:
      start_dhcp_server (default: False):
        Start the default DHCP server or not
      start_dhcp_server_after_ping (default: None):
        Start the DHCP server only after a successfully ping to a target.
        This should be a dict like: {
          "host": "192.168.234.1",
          "timeout_secs": 30,
          "interval_secs": 1
        }, with the ``timeout_secs`` and ``interval_secs`` being optional.
      dhcp_server_args (default: None):
        If ``start_dhcp_server`` is True, this will be passed to the default
        DHCP server (ssh.LinkManager)
    """
    if not start_dhcp_server:
      return
    with cls._dhcp_manager_lock:
      if cls._dhcp_manager:
        return
      options = dict(lease_time=5)
      options.update(dhcp_server_args or {})

      wait_ping = start_dhcp_server_after_ping or {}
      cls._WaitPing(**wait_ping)

      cls._dhcp_manager = cls.LinkManager(**options)
      cls._dhcp_manager.Start()

  @classmethod
  def _WaitPing(cls, host=None, timeout_secs=30, interval_secs=1):
    if not host:
      return

    def ping():
      cmd = ['ping', '-w', '1', '-c', '1', host]
      return process_utils.Spawn(cmd, call=True).returncode == 0

    sync_utils.PollForCondition(ping, timeout_secs=timeout_secs,
                                poll_interval_secs=interval_secs)

  class LinkManager:

    def __init__(self, lease_time=3600, interface_blocklist_file=None,
                 exclude_ip_prefix=None, on_add=None, on_old=None, on_del=None):
      """
        A LinkManager will automatically start a DHCP server for each available
        network interfaces, if the interface is not default gateway or in the
        blocklist.

        This LinkManager will automatically save IP of the latest client in
        system-wise shared data, make it available to SSHLinks whose host is set
        to None.

        Options:
          lease_time:
            lease time of DHCP servers
          interface_blocklist_file:
            a path to the file of blocklist, each line represents an interface
            (e.g. eth0, wlan1, ...)
          exclude_ip_prefix:
            some IP range cannot be used because of system settings, this
            argument should be a list of tuple of (ip, prefix_bits).
          on_add, on_old, on_del:
            callback functions for DHCP servers.
      """
      self._lease_time = lease_time
      self._blocklist_file = interface_blocklist_file
      self._on_add = on_add
      self._on_old = on_old
      self._on_del = on_del
      self._dhcp_server = None
      self._exclude_ip_prefix = exclude_ip_prefix

      self._lock = threading.Lock()
      self._devices = collections.OrderedDict()

    def _SetLastDUT(self):
      with self._lock:
        if self._devices:
          last_dut = next(reversed(self._devices))
          SSHLink.SetLinkIP(last_dut[0])
        else:
          SSHLink.ResetLinkIP()

    def _OnDHCPAdd(self, ip, mac_address):
      # update last device
      if (ip, mac_address) not in self._devices:
        with self._lock:
          if (ip, mac_address) not in self._devices:
            self._devices[(ip, mac_address)] = None
      self._SetLastDUT()

      # invoke callback function
      if callable(self._on_add):
        self._on_add(ip, mac_address)

    def _OnDHCPOld(self, ip, mac_address):
      # update last device
      if (ip, mac_address) not in self._devices:
        with self._lock:
          if (ip, mac_address) not in self._devices:
            self._devices[(ip, mac_address)] = None
      self._SetLastDUT()

      # invoke callback function
      if callable(self._on_old):
        self._on_old(ip, mac_address)

    def _OnDHCPDel(self, ip, mac_address):
      # remove the device
      if (ip, mac_address) in self._devices:
        with self._lock:
          if (ip, mac_address) in self._devices:
            del self._devices[(ip, mac_address)]
      self._SetLastDUT()

      # invoke callback function
      if callable(self._on_del):
        self._on_del(ip, mac_address)

    def _StartDHCPServer(self):
      self._dhcp_server = dhcp_utils.StartDHCPManager(
          blocklist_file=self._blocklist_file,
          exclude_ip_prefix=self._exclude_ip_prefix,
          lease_time=self._lease_time, on_add=self._OnDHCPAdd,
          on_old=self._OnDHCPOld, on_del=self._OnDHCPDel)

    def Start(self):
      self._SetLastDUT()
      self._StartDHCPServer()

    def Stop(self):
      if self._dhcp_server:
        self._dhcp_server.StopDHCP()
