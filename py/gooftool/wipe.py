# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Transition to release state directly without reboot."""

import json
import logging
import os
import re
import resource
import shutil
import signal
import socket
import tempfile
import textwrap
import time

from cros.factory.gooftool import chroot
from cros.factory.gooftool.common import ExecFactoryPar
from cros.factory.gooftool.common import Shell
from cros.factory.gooftool.common import Util
from cros.factory.test.env import paths
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import sys_utils


CUTOFF_SCRIPT_DIR = '/usr/local/factory/sh/cutoff'
"""Directory of scripts for device cut-off"""

WIPE_IN_RAMFS_LOG = 'wipe_in_ramfs.log'

STATEFUL_PARTITION_PATH = '/mnt/stateful_partition/'

WIPE_MARK_FILE = 'wipe_mark_file'

_CROS_PAYLOADS_PATH = 'dev_image/opt/cros_payloads'

_USER_RMAD = 'rmad'
_SHIMLESS_DATA_PATH = '/mnt/stateful_partition/unencrypted/rma-data'
_SHIMLESS_STATE_FILE_PATH = f'{_SHIMLESS_DATA_PATH}/state'

CRX_CACHE_PAYLOAD_NAME = f'{_CROS_PAYLOADS_PATH}/release_image.crx_cache'
CRX_CACHE_TAR_PATH = '/tmp/crx_cache.tar'

DLC_CACHE_PAYLOAD_NAME = (
    f'{_CROS_PAYLOADS_PATH}/release_image.dlc_factory_cache')
DLC_CACHE_TAR_PATH = '/tmp/dlc_cache.tar'

# Some upstart jobs have multiple instances and we need to specify the name of
# the instance to stop a job.
# For example, to stop `ml-service` and `timberslide`, we need to run
# `stop ml-service TASK=<task_name>` and `stop timberslide LOG_PATH=<path>`.
# Since we cannot get the instance key from `initctl`, we record the
# mapping here.
JOB_TO_INSTANCE_KEY = {
    'ml-service': 'TASK',
    'timberslide': 'LOG_PATH',
    'timberslide-watcher': 'LOG_PATH',
}


def GetLogicalStateful(state_dev, log_message=None):
  """Get the logical stateful partition from the physical one.

  Args:
    state_dev: Path to physical stateful partition.
    log_message: Log message if logical stateful partition is LVM format.

  Returns:
    Path to logical stateful partition.
  """
  lvm_stateful = Util().GetLVMStateful(state_dev)
  if lvm_stateful:
    if log_message:
      logging.info(log_message)
    return lvm_stateful
  return state_dev


class WipeError(Exception):
  """Failed to complete wiping."""


def _CopyLogFileToStateDev(state_dev, logfile):
  with sys_utils.MountPartition(state_dev, rw=True,
                                fstype='ext4') as mount_point:
    shutil.copyfile(logfile, os.path.join(mount_point,
                                          os.path.basename(logfile)))


def _OnError(ip, port, token, state_dev, wipe_in_ramfs_log=None,
             wipe_init_log=None):
  state_dev = GetLogicalStateful(state_dev)
  if wipe_in_ramfs_log:
    _CopyLogFileToStateDev(state_dev, wipe_in_ramfs_log)
  if wipe_init_log:
    _CopyLogFileToStateDev(state_dev, wipe_init_log)
  _InformStation(ip, port, token, wipe_in_ramfs_log=wipe_in_ramfs_log,
                 wipe_init_log=wipe_init_log, success=False)


def Daemonize(logfile=None):
  """Starts a daemon process and terminates current process.

  A daemon process will be started, and continue executing the following codes.
  The original process that calls this function will be terminated.

  Example::

    def DaemonFunc():
      Daemonize()
      # the process calling DaemonFunc is terminated.
      # the following codes will be executed in a daemon process
      ...

  If you would like to keep the original process alive, you could fork a child
  process and let child process start the daemon.
  """
  # fork from parent process
  if os.fork():
    # stop parent process
    os._exit(0)  # pylint: disable=protected-access

  # decouple from parent process
  os.chdir('/')
  os.umask(0)
  os.setsid()

  # fork again
  if os.fork():
    os._exit(0)  # pylint: disable=protected-access

  maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
  if maxfd == resource.RLIM_INFINITY:
    maxfd = 1024

  for fd in range(maxfd):
    try:
      os.close(fd)
    except OSError:
      pass

  # Reopen fd 0 (stdin), 1 (stdout), 2 (stderr) to prevent errors from reading
  # or writing to these files.
  # Since we have closed all file descriptors, os.open should open a file with
  # file descriptor equals to 0
  os.open('/dev/null', os.O_RDWR)
  if logfile is None:
    os.dup2(0, 1)  # stdout
    os.dup2(0, 2)  # stderr
  else:
    os.open(logfile, os.O_RDWR | os.O_CREAT)
    os.dup2(1, 2)  # stderr

  # Set the default umask.
  os.umask(0o022)


def ResetLog(logfile=None):
  if logging.getLogger().handlers:
    for handler in logging.getLogger().handlers:
      logging.getLogger().removeHandler(handler)
  log_format = '[%(asctime)-15s] %(levelname)s:%(name)s:%(message)s'
  # logging.NOTSET is the lowerest level.
  logging.basicConfig(filename=logfile, level=logging.NOTSET, format=log_format)


def WipeInRamFs(is_fast=None, shopfloor_url=None, station_ip=None,
                station_port=None, wipe_finish_token=None,
                keep_developer_mode_flag=False, boot_to_shimless=False,
                test_umount=False):
  """Prepare to wipe by pivot root to ram and unmount stateful partition.

  Args:
    is_fast: whether or not to apply fast wipe.
    shopfloor_url: for inform_shopfloor.sh
    boot_to_shimless: Whether or not to boot to Shimless RMA process.
  """

  def _CheckBug78323428():
    # b/78323428: Check if dhcpcd is locking /var/run. If dhcpcd is locking
    # /var/run, unmount will fail. Need CL:1021611 to use /run instead.
    for pid in Shell('pgrep dhcpcd').stdout.splitlines():
      lock_result = Shell(f'ls -al /proc/{pid}/fd | grep /var/run')
      if lock_result.stdout:
        raise WipeError(
            'dhcpcd is still locking on /var/run. Please use a newer ChromeOS '
            f'image with CL:1021611 included. Lock info: "{lock_result.stdout}'
            '"')

  _CheckBug78323428()

  Daemonize()

  logfile = os.path.join('/tmp', WIPE_IN_RAMFS_LOG)
  ResetLog(logfile)

  factory_par = paths.GetFactoryPythonArchivePath()

  new_root = tempfile.mkdtemp(prefix='ramfs.')
  binary_deps = [
      'activate_date', 'backlight_tool', 'bash', 'busybox', 'cgpt', 'cgpt.bin',
      'clobber-log', 'clobber-state', 'coreutils', 'crossystem', 'dd',
      'pvdisplay', 'display_boot_message', 'dumpe2fs', 'ectool', 'flashrom',
      'halt', 'initctl', 'mkfs.ext4', 'mktemp', 'mosys', 'mount',
      'mount-encrypted', 'od', 'pango-view', 'pkill', 'pv', 'python', 'reboot',
      'setterm', 'sh', 'shutdown', 'stop', 'umount', 'vpd', 'curl', 'lsof',
      'jq', '/sbin/frecon', 'stressapptest', 'fuser', 'login', 'factory_ufs',
      'ufs-utils'
  ]

  etc_issue = textwrap.dedent("""
    You are now in tmp file system created for in-place wiping.

    For debugging wiping fails, see log files under
    /tmp
    /mnt/stateful_partition/unencrypted

    The log file name should be
    - wipe_in_ramfs.log
    - wipe_init.log

    You can also run scripts under /usr/local/factory/sh for wiping process.
    """)

  util = Util()

  root_disk = util.GetPrimaryDevicePath()
  release_rootfs = util.GetReleaseRootPartitionPath()
  state_dev = util.GetPrimaryDevicePath(1)
  wipe_args = 'factory' + (' fast' if is_fast else '')

  logging.debug('state_dev: %s', state_dev)
  logging.debug('factory_par: %s', factory_par)

  old_root = 'old_root'

  try:
    with chroot.TmpChroot(
        new_root,
        file_dir_list=[
            # Basic rootfs.
            '/bin',
            '/etc',
            '/lib',
            '/lib64',
            '/root',
            '/sbin',
            '/usr/sbin',
            '/usr/bin',
            '/usr/lib',
            '/usr/lib64',
            # Factory related scripts.
            factory_par,
            '/usr/local/factory/sh',
            # Factory config files
            '/usr/local/factory/py/config',
            '/usr/share/fonts/notocjk',
            '/usr/share/cache/fontconfig',
            '/usr/share/chromeos-assets/images',
            '/usr/share/chromeos-assets/text/boot_messages',
            '/usr/share/misc/chromeos-common.sh',
            # File required for enable ssh connection.
            '/mnt/stateful_partition/etc/ssh',
            '/root/.ssh',
            '/usr/share/chromeos-ssh-config',
            # /mnt/empty is required by openssh server.
            '/mnt/empty',
        ],
        binary_list=binary_deps,
        etc_issue=etc_issue).PivotRoot(old_root):
      logging.debug('ps -aux: %s', process_utils.SpawnOutput(['ps', '-aux']))
      logging.debug(
          'lsof: %s',
          process_utils.SpawnOutput(f'lsof -p {os.getpid()}', shell=True))

      # Modify display_wipe_message so we have shells in VT2.
      # --dev-mode provides shell with etc-issue.
      # --enable-vt1 allows drawing escapes (OSC) on VT1 but it'll also display
      # etc-issue and login prompt.
      # For now we only want login prompts on VT2+.
      process_utils.Spawn([
          'sed', '-i', 's/--no-login/--dev-mode/g;s/--enable-vt1//g',
          '/usr/sbin/display_boot_message'
      ], call=True)

      # Restart gooftool under new root. Since current gooftool might be using
      # some resource under stateful partition, restarting gooftool ensures that
      # everything new gooftool is using comes from ramfs and we can safely
      # unmount stateful partition.
      args = []
      if wipe_args:
        args += ['--wipe_args', wipe_args]
      if shopfloor_url:
        args += ['--shopfloor_url', shopfloor_url]
      if station_ip:
        args += ['--station_ip', station_ip]
      if station_port:
        args += ['--station_port', station_port]
      if wipe_finish_token:
        args += ['--wipe_finish_token', wipe_finish_token]
      if boot_to_shimless:
        args += ['--boot_to_shimless']
      if test_umount:
        args += ['--test_umount']
      args += ['--state_dev', state_dev]
      args += ['--release_rootfs', release_rootfs]
      args += ['--root_disk', root_disk]
      args += ['--old_root', old_root]
      if keep_developer_mode_flag:
        args += ['--keep_developer_mode_flag_after_clobber_state']

      ExecFactoryPar('gooftool', 'wipe_init', *args)
      raise WipeError('Should not reach here')
  except Exception:
    logging.exception('wipe_in_place failed')
    _OnError(station_ip, station_port, wipe_finish_token, state_dev,
             wipe_in_ramfs_log=logfile, wipe_init_log=None)
    raise


def _GetToStopServiceList(exclude_list):
  # There may be `instance` optional parameter for an upstart job, and the
  # initctl output may be different. The possible outputs:
  #   "service_name start/running"
  #   "service_name ($instance) start/running"
  initctl_output = process_utils.SpawnOutput(['initctl', 'list']).splitlines()

  running_service_list = []
  for line in initctl_output:
    if 'start/running' not in line:
      continue

    service_name = line.split()[0]
    instance_val = line.split()[1][1:-1] if '(' in line.split()[1] else ''
    running_service_list.append((service_name, instance_val))

  logging.info('Running services (service_name, instance): %r',
               running_service_list)

  return [
      service for service in running_service_list
      if not (service[0] in exclude_list or service[0].startswith('console-'))
  ]


def _StopAllUpstartJobs(exclude_list=None):
  logging.debug('stopping upstart jobs')

  if exclude_list is None:
    exclude_list = []

  # Try three times to stop running services because some service will respawn
  # one time after being stopped, e.g. shill_respawn. Two times should be enough
  # to stop shill. Adding one more try for safety.
  for unused_tries in range(3):
    to_stop_service_list = _GetToStopServiceList(exclude_list)
    logging.info('Going to stop services (service_name, instance): %r',
                 to_stop_service_list)

    for service, instance_val in to_stop_service_list:
      stop_cmd = ['stop', service]
      if instance_val:
        instance_key = JOB_TO_INSTANCE_KEY.get(service)
        if instance_key is None:
          raise WipeError(
              f'Fail to get the instance key of service {service} ('
              f'{instance_val}). Please read {service}.conf and add the key to '
              '`JOB_TO_INSTANCE_KEY`.')
        stop_cmd += [f'{instance_key}={instance_val}']
      process_utils.Spawn(stop_cmd, log=True, log_stderr_on_error=True)

  to_stop_service_list = _GetToStopServiceList(exclude_list)

  if to_stop_service_list:
    raise WipeError(
        'Fail to stop services (service_name, instance): '
        f'{to_stop_service_list!r}.\nPlease check the upstart config or check '
        'with the service owner.')


def _CollectMountPointsToUmount(state_dev):
  # Find mount points on stateful partition.
  mount_output = process_utils.SpawnOutput(['mount'], log=True)

  mount_point_list = []
  namespace_list = []
  for line in mount_output.splitlines():
    fields = line.split()
    if fields[0] == state_dev or re.match(r'\/dev\/mapper\/', fields[0]):
      mount_point_list.append(fields[2])
    if fields[0] == 'nsfs':
      namespace_list.append(fields[2])
    # Mount type of mount namespace is 'proc' for some kernel versions. Make
    # sure to unmount mount namespaces to successfully unmount stateful
    # partition.
    if fields[0] == 'proc' and fields[2].find('/run/namespaces/mnt_') != -1:
      namespace_list.append(fields[2])

  logging.debug('stateful partitions mounted on: %s', mount_point_list)
  logging.debug('namespace mounted on: %s', namespace_list)

  return mount_point_list, namespace_list


def _UnmountStatefulPartition(root, state_dev, test_umount):

  def _BackupIfExist(path_to_file, path_to_backup):
    if os.path.exists(path_to_file):
      logging.info('Backup file %s to %s.', path_to_file, path_to_backup)
      shutil.copyfile(path_to_file, path_to_backup)

  logging.debug('Unmount stateful partition.')

  # Expected stateful partition mount point.
  state_dir = os.path.join(root, STATEFUL_PARTITION_PATH.strip(os.path.sep))

  # If not in testing mode, touch a mark file so we can check if the stateful
  # partition is wiped successfully.
  if not test_umount:
    file_utils.WriteFile(os.path.join(state_dir, WIPE_MARK_FILE), '')

  # Backup extension cache (crx_cache) and dlc image cache (dlc_factory_cache)
  # if available (will be restored after wiping by clobber-state).
  crx_cache_path = os.path.join(state_dir, CRX_CACHE_PAYLOAD_NAME)
  dlc_cache_path = os.path.join(state_dir, DLC_CACHE_PAYLOAD_NAME)
  _BackupIfExist(crx_cache_path, CRX_CACHE_TAR_PATH)
  _BackupIfExist(dlc_cache_path, DLC_CACHE_TAR_PATH)

  state_dev = GetLogicalStateful(state_dev,
                                 'Wiping using LVM stateful partition...')

  mount_point_list, namespace_list = _CollectMountPointsToUmount(state_dev)

  def _ListProcOpening(path_list):
    lsof_cmd = ['lsof', '-t'] + path_list
    return [
        int(line) for line in process_utils.SpawnOutput(lsof_cmd).splitlines()
    ]

  def _ListMinijail():
    # Not sure why, but if we use 'minijail0', then we can't find processes that
    # starts with /sbin/minijail0.
    list_cmd = ['pgrep', 'minijail']
    return [
        int(line) for line in process_utils.SpawnOutput(list_cmd).splitlines()
    ]

  # Find processes that are using stateful partitions.
  proc_list = _ListProcOpening(mount_point_list)

  if os.getpid() in proc_list:
    logging.error('wipe_init itself is using stateful partition')
    logging.error(
        'lsof: %s',
        process_utils.SpawnOutput(f'lsof -p {os.getpid()}', shell=True))
    raise WipeError('wipe_init itself is using stateful partition')

  @sync_utils.RetryDecorator(max_attempt_count=10, interval_sec=0.1,
                             target_condition=bool)
  def _KillOpeningBySignal(sig):
    for mount_point in mount_point_list:
      cmd = ['fuser', '-k', f'-{int(sig)}', '-m', mount_point]
      process_utils.Spawn(cmd, call=True, log=True)
    proc_list = _ListProcOpening(mount_point_list)
    if not proc_list:
      return True  # we are done
    for pid in proc_list:
      try:
        os.kill(pid, sig)
      except Exception:
        logging.exception('killing process %d failed', pid)
    return False  # need to check again

  # Try to kill processes using stateful partition gracefully.
  _KillOpeningBySignal(signal.SIGTERM)
  _KillOpeningBySignal(signal.SIGKILL)

  proc_list = _ListProcOpening(mount_point_list)
  assert not proc_list, f"processes using stateful partition: {proc_list}"

  def _Unmount(mount_point, critical):
    logging.info('try to unmount %s', mount_point)
    for unused_i in range(10):
      output = process_utils.Spawn(['umount', '-n', '-R', mount_point],
                                   log=True,
                                   log_stderr_on_error=True).stderr_data
      # some mount points need to be unmounted multiple times.
      if (output.endswith(': not mounted\n') or
          output.endswith(': not found\n')):
        return
      time.sleep(0.5)
    logging.error('failed to unmount %s', mount_point)
    if critical:
      raise WipeError(f'Unmounting {mount_point} is critical. Stop.')

  def _UnmountAll(critical):
    # Remove all mounted namespace to release stateful partition.
    for ns_mount_point in namespace_list:
      _Unmount(ns_mount_point, critical)

    # Doing what 'mount-encrypted umount' should do.
    for mount_point in mount_point_list:
      _Unmount(mount_point, critical)
    _Unmount(os.path.join(root, 'var'), critical)

  if os.path.exists(os.path.join(root, 'dev', 'mapper', 'encstateful')):
    _UnmountAll(critical=False)
    # minijail will make encstateful busy, but usually we can't just kill them.
    # Need to list the processes and solve each-by-each.
    proc_list = _ListMinijail()
    assert not proc_list, (
        "processes still using minijail: "
        f"{process_utils.SpawnOutput(['pgrep', '-al', 'minijail'])}")

    process_utils.Spawn(
        ['dmsetup', 'remove', 'encstateful', '--noudevrules', '--noudevsync'],
        check_call=True)
    process_utils.Spawn(['losetup', '-D'], check_call=True)

  _UnmountAll(critical=True)
  process_utils.Spawn(['sync'], call=True)

  mount_point_list, namespace_list = _CollectMountPointsToUmount(state_dev)

  if mount_point_list or namespace_list:
    error_message = ('Mount points are not cleared. '
                     f'mount_point_list: {mount_point_list} '
                     f'namespace_list: {namespace_list}')
    raise WipeError(error_message)

  # Check if the stateful partition is unmounted successfully.
  if _IsStateDevMounted(state_dev):
    raise WipeError('Failed to unmount stateful_partition')


def _IsStateDevMounted(state_dev):
  try:
    output = process_utils.CheckOutput(['df', state_dev])
    return output.splitlines()[-1].split()[0] == state_dev
  except Exception:
    return False


def _InformStation(ip, port, token, wipe_init_log=None, wipe_in_ramfs_log=None,
                   success=True):
  if not ip:
    return
  port = int(port)

  logging.debug('inform station %s:%d', ip, port)

  try:
    sync_utils.WaitFor(
        lambda: process_utils.Spawn(['ping', '-w1', '-c1', ip], call=True).
        returncode == 0, timeout_secs=180, poll_interval=1)
  except Exception:
    logging.exception('cannot get network connection...')
  else:
    sock = socket.socket()
    sock.connect((ip, port))

    response = dict(token=token, success=success)

    if wipe_init_log:
      response['wipe_init_log'] = file_utils.ReadFile(wipe_init_log)

    if wipe_in_ramfs_log:
      response['wipe_in_ramfs_log'] = file_utils.ReadFile(wipe_in_ramfs_log)

    sock.sendall(json.dumps(response) + '\n')
    sock.close()


def _WipeStateDev(release_rootfs, root_disk, wipe_args, state_dev,
                  keep_developer_mode_flag, boot_to_shimless):

  def _RestoreIfExist(path_to_file):
    logging.info('Checking %s...', path_to_file)
    if os.path.exists(path_to_file):
      logging.info('Restoring %s...', path_to_file)
      process_utils.Spawn(
          ['tar', '-xpvf', path_to_file, '-C', STATEFUL_PARTITION_PATH],
          check_call=True, log=True, log_stderr_on_error=True)

  clobber_state_env = os.environ.copy()
  clobber_state_env.update(ROOT_DEV=release_rootfs, ROOT_DISK=root_disk)
  logging.debug('clobber-state: root_dev=%s, root_disk=%s', release_rootfs,
                root_disk)

  process_utils.Spawn(['clobber-state', wipe_args], env=clobber_state_env,
                      check_call=True, log=True, log_stderr_on_error=True)

  # clobber-state will build LVM stateful partition if
  # `USE_LVM_STATEFUL_PARTITION=1` in `chromeos_startup`.
  state_dev = GetLogicalStateful(state_dev,
                                 'Switching to LVM stateful partition...')
  logging.info('Checking if stateful partition (%s) is mounted...', state_dev)
  # Check if the stateful partition is wiped.
  if not _IsStateDevMounted(state_dev):
    process_utils.Spawn(['mount', state_dev, STATEFUL_PARTITION_PATH],
                        check_call=True, log=True)

  logging.info('Checking wipe mark file %s...', WIPE_MARK_FILE)
  if os.path.exists(os.path.join(STATEFUL_PARTITION_PATH, WIPE_MARK_FILE)):
    raise WipeError(WIPE_MARK_FILE + ' still exists')

  # Restore CRX and DLC cache.
  _RestoreIfExist(CRX_CACHE_TAR_PATH)
  _RestoreIfExist(DLC_CACHE_TAR_PATH)

  if boot_to_shimless:
    logging.info('Preparing Shimless RMA environment...')

    # Add Shimless RMA file.
    process_utils.Spawn(['mkdir', '-p', _SHIMLESS_DATA_PATH], check_call=True,
                        log=True)

    # TODO(jeffulin): It would be better to make the Shimless RMA directly in
    # rework flow.
    process_utils.Spawn(['touch', _SHIMLESS_STATE_FILE_PATH], check_call=True,
                        log=True)
    process_utils.Spawn(
        ['chown', f'{_USER_RMAD}:{_USER_RMAD}', _SHIMLESS_STATE_FILE_PATH],
        check_call=True, log=True)

  try:
    if not keep_developer_mode_flag:
      # Remove developer flag, which is created by clobber-state after wiping.
      os.unlink(os.path.join(STATEFUL_PARTITION_PATH, '.developer_mode'))
    # Otherwise we don't care.
  except OSError:
    pass

  process_utils.Spawn(['umount', STATEFUL_PARTITION_PATH], call=True)
  # Make sure that everything is synced.
  process_utils.Spawn(['sync'], call=True)
  time.sleep(3)


def EnableReleasePartition(release_rootfs):
  """Enables a release image partition on disk."""
  logging.debug('enable release partition: %s', release_rootfs)
  Util().EnableReleasePartition(release_rootfs)
  logging.debug('Device will boot from %s after reboot.', release_rootfs)


def _InformShopfloor(shopfloor_url):
  if shopfloor_url:
    logging.debug('inform shopfloor %s', shopfloor_url)
    proc = process_utils.Spawn([
        os.path.join(CUTOFF_SCRIPT_DIR, 'inform_shopfloor.sh'), shopfloor_url,
        'factory_wipe'
    ], read_stdout=True, read_stderr=True)
    logging.debug('stdout: %s', proc.stdout_data)
    logging.debug('stderr: %s', proc.stderr_data)
    if proc.returncode != 0:
      raise RuntimeError('InformShopfloor failed.')


def _Cutoff():
  logging.debug('cutoff')
  cutoff_script = os.path.join(CUTOFF_SCRIPT_DIR, 'cutoff.sh')
  process_utils.Spawn([cutoff_script], check_call=True)


def WipeInit(wipe_args, shopfloor_url, state_dev, release_rootfs, root_disk,
             old_root, station_ip, station_port, finish_token,
             keep_developer_mode_flag, boot_to_shimless, test_umount):
  Daemonize()
  logfile = '/tmp/wipe_init.log'
  ResetLog(logfile)
  wipe_in_ramfs_log = os.path.join(old_root, 'tmp', WIPE_IN_RAMFS_LOG)

  logging.debug('wipe_args: %s', wipe_args)
  logging.debug('shopfloor_url: %s', shopfloor_url)
  logging.debug('state_dev: %s', state_dev)
  logging.debug('release_rootfs: %s', release_rootfs)
  logging.debug('root_disk: %s', root_disk)
  logging.debug('old_root: %s', old_root)
  logging.debug('boot_to_shimless: %s', boot_to_shimless)
  logging.debug('test_umount: %s', test_umount)

  try:
    # Enable upstart log under /var/log/upstart.log for Tast.
    process_utils.Spawn(['initctl', 'log-priority', 'info'], log=True,
                        log_stderr_on_error=True)

    _StopAllUpstartJobs(exclude_list=[
        # Milestone marker that use to determine the running of other services.
        'boot-services',
        'system-services',
        'failsafe',
        # Keep dbus to make sure we can shutdown the device.
        'dbus',
        # Keep shill for connecting to shopfloor or stations.
        'shill',
        # Keep wpasupplicant since shopfloor may connect over WiFi.
        'wpasupplicant',
        # Keep openssh-server for debugging purpose.
        'openssh-server',
        # sslh is a service in ARC++ for muxing between ssh and adb.
        'sslh'
    ])
    _UnmountStatefulPartition(old_root, state_dev, test_umount)

    # When testing, stop the wiping process with no error. In normal
    # process, this function will run forever until reboot.
    if test_umount:
      logging.info('Finished unmount, stop wiping process because test_umount '
                   'is set.')
      return

    # The following code could not be executed when factory is not installed
    # due to lacking of CUTOFF_SCRIPT_DIR.
    process_utils.Spawn(
        [os.path.join(CUTOFF_SCRIPT_DIR, 'display_wipe_message.sh'), 'wipe'],
        call=True)

    try:
      _WipeStateDev(release_rootfs, root_disk, wipe_args, state_dev,
                    keep_developer_mode_flag, boot_to_shimless)
    except Exception:
      process_utils.Spawn([
          os.path.join(CUTOFF_SCRIPT_DIR, 'display_wipe_message.sh'),
          'wipe_failed'
      ], call=True)
      raise

    EnableReleasePartition(release_rootfs)

    _InformShopfloor(shopfloor_url)

    _InformStation(station_ip, station_port, finish_token,
                   wipe_init_log=logfile, wipe_in_ramfs_log=wipe_in_ramfs_log,
                   success=True)

    # Sleep 1 second for waiting PDO switching, see b/278804761.
    time.sleep(1)
    _Cutoff()

    # should not reach here
    logging.info('Going to sleep forever!')
    time.sleep(1e8)
  except Exception:
    # This error message is used to detect error in Factory.Finalize Tast test.
    # Keep sync if changed this.
    logging.exception('wipe_init failed')
    _OnError(station_ip, station_port, finish_token, state_dev,
             wipe_in_ramfs_log=wipe_in_ramfs_log, wipe_init_log=logfile)
    raise
