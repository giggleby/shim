#!/usr/bin/env python3
#
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Factory toolkit installer.

The factory toolkit is a self-extracting shellball containing factory test
related files and this installer. This installer is invoked when the toolkit
is deployed and is responsible for installing files.
"""

import argparse
from contextlib import contextmanager
import getpass
import glob
import os
import shutil
import sys
import tempfile
import time

from cros.factory.test.env import paths
from cros.factory.test.test_lists import test_list_common
from cros.factory.tools import install_symlinks
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils import sys_utils


PYTHONPATH = 'usr/local/factory/py_pkg'
INSTALLER_MODULE = 'cros.factory.toolkit.installer'
VERSION_PATH = 'usr/local/factory/TOOLKIT_VERSION'

# Short and sweet help header for the executable generated by makeself.
HELP_HEADER = """
Installs the factory toolkit, transforming a test image into a factory test
image. You can:

- Install the factory toolkit on a CrOS device that is running a test
  image.  To do this, copy install_factory_toolkit.run to the device and
  run it.  The factory tests will then come up on the next boot.

    rsync -a install_factory_toolkit.run crosdevice:/tmp
    ssh crosdevice '/tmp/install_factory_toolkit.run && sync && reboot'

- Modify a test image, turning it into a factory test image.  When you
  use the image on a device, the factory tests will come up.

    install_factory_toolkit.run chromiumos_test_image.bin
"""

HELP_HEADER_ADVANCED = """
- (advanced) Modify a mounted stateful partition, turning it into a factory
  test image.  This is equivalent to the previous command:

    mount_partition -rw chromiumos_test_image.bin 1 /mnt/stateful
    install_factory_toolkit.run /mnt/stateful
    umount /mnt/stateful

- (advanced) Unpack the factory toolkit, modify a file, and then repack it.

    # Unpack but don't actually install
    install_factory_toolkit.run --target /tmp/toolkit --noexec
    # Edit some files in /tmp/toolkit
    emacs /tmp/toolkit/whatever
    # Repack
    install_factory_toolkit.run -- --repack /tmp/toolkit \\
        --pack-into /path/to/new/install_factory_toolkit.run
"""

# The makeself-generated header comes next.  This is a little confusing,
# so explain.
HELP_HEADER_MAKESELF = """
For complete usage information and advanced operations, run
"install_factory_toolkit.run -- --help" (note the extra "--").

Following is the help message from makeself, which was used to create
this self-extracting archive.

-----
"""

SERVER_FILE_MASK = [
    # Exclude Umpire server but keep Umpire client
    '--include', 'py/umpire/__init__.*',
    '--include', 'py/umpire/common.*',
    '--include', 'py/umpire/client',
    '--include', 'py/umpire/client/**',
    '--exclude', 'py/umpire/**',
    '--exclude', 'bin/umpire',
    '--exclude', 'bin/umpired',
]


class FactoryToolkitInstaller:
  """Factory toolkit installer.

  Args:
    src: Source path containing usr/ and var/.
    dest: Installation destination path. Set this to the mount point of the
          stateful partition if patching a test image.
    no_enable: True to not install the tag file.
    system_root: The path to the root of the file system. This must be left
                 as its default value except for unit testing.
    apps: The list of apps to enable/disable under factory/init/main.d/.
    active_test_list: The id of active test list for Goofy.
  """

  # Whether to sudo when rsyncing; set to False for testing.
  _sudo = True

  def __init__(self, src, dest, no_enable, non_cros=False, system_root='/',
               apps=None, active_test_list=None):
    self._src = src
    self._system_root = system_root
    if dest == self._system_root:
      self._usr_local_dest = os.path.join(dest, 'usr', 'local')

      # Make sure we're on a CrOS device.
      if not non_cros and not sys_utils.InCrOSDevice():
        sys.stderr.write(
            "ERROR: You're not on a CrOS device (for more details, please\n"
            'check sys_utils.py:InCrOSDevice), so you must specify a test\n'
            'image or a mounted stateful partition on which to install the\n'
            'factory toolkit.  Please run\n'
            '\n'
            '  install_factory_toolkit.run -- --help\n'
            '\n'
            'for help.\n'
            '\n'
            'If you want to install on a non-CrOS host,\n'
            'please run\n'
            '\n'
            '  install_factory_toolkit.run -- --non-cros \n'
            '\n')
        sys.exit(1)
      if os.getuid() != 0:
        raise Exception('You must be root to install the factory toolkit on a '
                        'CrOS device.')
    else:
      self._usr_local_dest = os.path.join(dest, 'dev_image')
      if not os.path.exists(self._usr_local_dest):
        raise Exception(
            'The destination path %s is not a stateful partition!' % dest)

    self._dest = dest
    self._usr_local_src = os.path.join(src, 'usr', 'local')
    self._no_enable = no_enable
    self._tag_file = os.path.join(self._usr_local_dest, 'factory', 'enabled')

    self._apps = apps
    self._active_test_list = active_test_list

    if not os.path.exists(self._usr_local_src):
      raise Exception(
          'This installer must be run from within the factory toolkit!')

  def WarningMessage(self, target_test_image=None):
    ret = file_utils.ReadFile(os.path.join(self._src, VERSION_PATH))
    if target_test_image:
      ret += (
          '\n'
          '\n'
          '*** You are about to patch the factory toolkit into:\n'
          '***   %s\n'
          '***' % target_test_image)
    else:
      ret += (
          '\n'
          '\n'
          '*** You are about to install the factory toolkit to:\n'
          '***   %s\n'
          '***' % self._dest)
    if self._dest == self._system_root:
      if self._no_enable:
        ret += ('\n*** Factory tests will be disabled after this process is '
                'done, but\n*** you can enable them by creating the factory '
                'enabled tag:\n***   %s\n***' % self._tag_file)
      else:
        ret += ('\n*** After this process is done, your device will start '
                'factory\n*** tests on the next reboot.\n***\n*** Factory '
                'tests can be disabled by deleting the factory enabled\n*** '
                'tag:\n***   %s\n***' % self._tag_file)
    return ret

  def _SetTagFile(self, name, path, enabled):
    """Install or remove a tag file."""
    if enabled:
      print('*** Installing %s enabled tag...' % name)
      Spawn(['touch', path], sudo=True, log=True, check_call=True)
      Spawn(['chmod', 'go+r', path], sudo=True, log=True, check_call=True)
    else:
      print('*** Removing %s enabled tag...' % name)
      Spawn(['rm', '-f', path], sudo=True, log=True, check_call=True)

  def _SetActiveTestList(self):
    """Set the active test list for Goofy."""
    if self._active_test_list is not None:
      path = os.path.join(self._usr_local_dest, 'factory',
                          test_list_common.ACTIVE_TEST_LIST_CONFIG_RELPATH)
      json_utils.DumpFile(
          path,
          test_list_common.GenerateActiveTestListConfig(self._active_test_list))

  def _EnableApp(self, app, enabled):
    """Enable / disable @app.

    In factory/init/startup, a main app is considered disabled if and only:
      1. file "factory/init/main.d/disable-@app" exists OR
      2. file "factory/init/main.d/enable-@app" doesn't exist AND
        file "factory/init/main.d/@app.sh" is not executable.

    Therefore, we enable an app by removing file "disable-@app" and creating
    file "enable-@app", and vice versa.
    """
    app_enable = os.path.join(self._usr_local_dest,
                              'factory', 'init', 'main.d', 'enable-' + app)
    app_disable = os.path.join(self._usr_local_dest,
                               'factory', 'init', 'main.d', 'disable-' + app)
    if enabled:
      print('*** Enabling {app} ***'.format(app=app))
      Spawn(['rm', '-f', app_disable], sudo=self._sudo, log=True,
            check_call=True)
      Spawn(['touch', app_enable], sudo=self._sudo, log=True, check_call=True)
    else:
      print('*** Disabling {app} ***'.format(app=app))
      Spawn(['touch', app_disable], sudo=self._sudo, log=True, check_call=True)
      Spawn(['rm', '-f', app_enable], sudo=self._sudo, log=True,
            check_call=True)

  def _EnableApps(self):
    if not self._apps:
      return

    app_list = []
    for app in self._apps:
      if app[0] == '+':
        app_list.append((app[1:], True))
      elif app[0] == '-':
        app_list.append((app[1:], False))
      else:
        raise ValueError(
            'Use +{app} to enable and -{app} to disable'.format(app=app))

    for app, enabled in app_list:
      self._EnableApp(app, enabled)

  def InstallFactorySubDir(self, sub_dirs):
    """Install only the specified directories under factory folder."""

    def _InstallOneSubDir(sub_dir_name):
      sub_dir_dest = os.path.join(self._usr_local_dest, 'factory', sub_dir_name)
      sub_dir_src = os.path.join(self._src, 'usr', 'local', 'factory',
                                 sub_dir_name)
      try:
        Spawn(['mkdir', '-p', sub_dir_dest], sudo=True, log=True,
              check_call=True)
      except OSError as e:
        print(str(e))
        return

      Spawn(['rsync', '-a', '--force', '-v',
             sub_dir_src + '/', sub_dir_dest],
            sudo=self._sudo, log=True, check_call=True)
      Spawn(['chown', '-R', 'root', sub_dir_dest],
            sudo=self._sudo, log=True, check_call=True)
      Spawn(['chmod', '-R', 'go+rX', sub_dir_dest],
            sudo=self._sudo, log=True, check_call=True)

    for sub_dir_name in sub_dirs:
      _InstallOneSubDir(sub_dir_name)

    self._SetTagFile('factory', self._tag_file, not self._no_enable)
    self._EnableApps()

  def Install(self):
    print('*** Installing factory toolkit...')

    # --no-owner and --no-group will set owner/group to the current user/group
    # running the command. This is important if we're running with sudo, so
    # the destination will be changed to root/root instead of the user/group
    # before sudo (doesn't matter if sudo is not present). --force is also
    # necessary to allow goofy directory from prior toolkit installations to
    # be overwritten by the goofy symlink.
    print('***   %s -> %s' % (self._usr_local_src, self._usr_local_dest))
    Spawn(['rsync', '-a', '--no-owner', '--no-group', '--chmod=ugo+rX',
           '--force'] + SERVER_FILE_MASK + [self._usr_local_src + '/',
                                            self._usr_local_dest],
          sudo=self._sudo, log=True, check_output=True, cwd=self._usr_local_src)

    print('*** Ensure SSH keys file permission...')
    sshkeys_dir = os.path.join(self._usr_local_dest, 'factory/misc/sshkeys')
    sshkeys = glob.glob(os.path.join(sshkeys_dir, '*'))
    ssh_public_keys = glob.glob(os.path.join(sshkeys_dir, '*.pub'))
    ssh_private_keys = list(set(sshkeys) - set(ssh_public_keys))
    if ssh_private_keys:
      Spawn(['chmod', '600'] + ssh_private_keys, log=True, check_call=True,
            sudo=self._sudo)

    print('*** Installing symlinks...')
    install_symlinks.InstallSymlinks(
        '../factory/bin',
        os.path.join(self._usr_local_dest, 'bin'),
        install_symlinks.MODE_FULL,
        sudo=self._sudo)

    self._SetTagFile('factory', self._tag_file, not self._no_enable)

    self._SetActiveTestList()
    self._EnableApps()

    print('*** Installation completed.')


@contextmanager
def DummyContext(arg):
  """A context manager that simply yields its argument."""
  yield arg


def PrintBuildInfo(src_root):
  """Print build information."""
  info_file = os.path.join(src_root, 'REPO_STATUS')
  if not os.path.exists(info_file):
    raise OSError('Build info file not found!')
  print(file_utils.ReadFile(info_file))


def PackFactoryToolkit(src_root, output_path, initial_version, quiet=False):
  """Packs the files containing this script into a factory toolkit."""
  if initial_version is None:
    complete_version = '%s  repacked by %s@%s at %s\n' % (
        file_utils.ReadFile(os.path.join(src_root, VERSION_PATH)),
        getpass.getuser(), os.uname()[1], time.strftime('%Y-%m-%d %H:%M:%S'))
    initial_version = complete_version.splitlines()[0]
  else:
    complete_version = initial_version + '\n'
  modified_times = len(complete_version.splitlines()) - 1
  if modified_times == 0:
    modified_msg = ''
  else:
    modified_msg = ' (modified %d times)' % modified_times
  with tempfile.NamedTemporaryFile('w') as help_header:
    help_header.write(initial_version + '\n' +
                      HELP_HEADER + HELP_HEADER_MAKESELF)
    help_header.flush()
    build_option_args = ['--tar-format', 'gnu']
    cmd = [
        os.path.join(src_root, 'makeself.sh'),
        '--bzip2',
        '--nox11',
        *build_option_args,
        '--help-header',
        help_header.name,
        src_root,  # archive_dir
        output_path,  # file_name
        initial_version + modified_msg,  # label
        # startup script and args
        # We have to explicitly execute python instead of directly execute
        # INSTALLER_PATH because files under INSTALLER_PATH may not be
        # executable.
        'env',
        'PYTHONPATH=' + PYTHONPATH,
        'python3',
        '-m',
        INSTALLER_MODULE,
        '--in-exe'
    ]
    Spawn(cmd, check_call=True, log=True, read_stdout=quiet, read_stderr=quiet)
  with file_utils.TempDirectory() as tmp_dir:
    version_path = os.path.join(tmp_dir, VERSION_PATH)
    os.makedirs(os.path.dirname(version_path))
    file_utils.WriteFile(version_path, complete_version)
    Spawn([
        cmd[0], '--lsm', version_path, *build_option_args, '--append', tmp_dir,
        output_path
    ], check_call=True, log=True, read_stdout=quiet, read_stderr=quiet)
  print('\n'
        '  Factory toolkit generated at %s.\n'
        '\n'
        '  To install factory toolkit on a live device running a test image,\n'
        '  copy this to the device and execute it as root.\n'
        '\n'
        '  Alternatively, the factory toolkit can be used to patch a test\n'
        '  image. For more information, run:\n'
        '    %s --help\n'
        '\n' % (output_path, output_path))


def ExtractOverlord(src_root, output_dir):
  output_dir = os.path.join(output_dir, 'overlord')
  try:
    os.makedirs(output_dir)
  except OSError as e:
    print(str(e))
    return

  # Copy overlord binary and resource files
  shutil.copyfile(os.path.join(src_root, 'usr/bin/overlordd'),
                  os.path.join(output_dir, 'overlordd'))
  shutil.copytree(os.path.join(src_root, 'usr/share/overlord/app'),
                  os.path.join(output_dir, 'app'))

  # Give overlordd execution permission
  os.chmod(os.path.join(output_dir, 'overlordd'), 0o755)
  print("Extracted overlord under '%s'" % output_dir)


def main():
  import logging
  logging.basicConfig(level=logging.INFO)

  # In order to determine which usage message to show, first determine
  # whether we're in the self-extracting archive.  Do this first
  # because we need it to even parse the arguments.
  if '--in-exe' in sys.argv:
    sys.argv = [x for x in sys.argv if x != '--in-exe']
    in_archive = True
  else:
    in_archive = False

  parser = argparse.ArgumentParser(
      description=HELP_HEADER + HELP_HEADER_ADVANCED,
      usage=('install_factory_toolkit.run -- [options]' if in_archive
             else None),
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument(
      'dest', nargs='?', default='/',
      help='A test image or the mount point of the stateful partition. '
           "If omitted, install to live system, i.e. '/'.")
  parser.add_argument('--no-enable', '-n', action='store_true',
                      help="Don't enable factory tests after installing")
  parser.add_argument('--yes', '-y', action='store_true',
                      help="Don't ask for confirmation")
  parser.add_argument('--build-info', action='store_true',
                      help='Print build information and exit')
  parser.add_argument('--pack-into', metavar='NEW_TOOLKIT',
                      help='Pack the files into a new factory toolkit')
  parser.add_argument('--repack', metavar='UNPACKED_TOOLKIT',
                      help='Repack from previously unpacked toolkit')
  parser.add_argument('--version', metavar='VERSION',
                      help='String to write into TOOLKIT_VERSION when packing')

  parser.add_argument('--non-cros', dest='non_cros',
                      action='store_true',
                      help='Install on non-ChromeOS host.')


  parser.add_argument('--exe-path', dest='exe_path',
                      nargs='?', default=None,
                      help='Current self-extracting archive pathname')
  parser.add_argument('--extract-overlord', dest='extract_overlord',
                      metavar='OUTPUT_DIR', type=str, default=None,
                      help='Extract overlord from the toolkit')
  parser.add_argument('--install-dirs', nargs='+', default=None,
                      help=('Install only the specified directories under '
                            'factory folder. Can be used with --apps to '
                            'enable / disable some apps. Defaults to install '
                            'all folders.'))
  parser.add_argument('--apps', type=lambda s: s.split(','), default=None,
                      help=('Enable or disable some apps under '
                            'factory/init/main.d/. Use prefix "-" to disable, '
                            'prefix "+" to enable, and use "," to separate. '
                            'For example: --apps="-goofy,+whale_servo"'))
  parser.add_argument('--active-test-list', dest='active_test_list',
                      default=None,
                      help='Set the id of active test list for Goofy.')
  parser.add_argument('--quiet', action='store_true',
                      help='Do not output makeself.sh log when success.')

  args = parser.parse_args()

  src_root = paths.FACTORY_DIR
  for unused_i in range(3):
    src_root = os.path.dirname(src_root)

  if args.extract_overlord is not None:
    ExtractOverlord(src_root, args.extract_overlord)
    return

  # --pack-into may be called directly so this must be done before changing
  # working directory to OLDPWD.
  if args.pack_into and args.repack is None:
    PackFactoryToolkit(src_root, args.pack_into, args.version, args.quiet)
    return

  if not in_archive:
    # If you're not in the self-extracting archive, you're not allowed to
    # do anything except the above --pack-into call.
    parser.error('Not running from install_factory_toolkit.run; '
                 'only --pack-into (without --repack) is allowed')

  # Change to original working directory in case the user specifies
  # a relative path.
  # TODO: Use USER_PWD instead when makeself is upgraded
  os.chdir(os.environ['OLDPWD'])

  if args.repack:
    if args.pack_into is None:
      parser.error('Must specify --pack-into when using --repack.')
    env = dict(os.environ,
               PYTHONPATH=os.path.join(args.repack, PYTHONPATH))
    cmd = ['python3', '-m', INSTALLER_MODULE, '--pack-into', args.pack_into]
    if args.quiet:
      cmd.append('--quiet')
    Spawn(cmd, check_call=True, log=True, env=env)
    return

  if args.build_info:
    PrintBuildInfo(src_root)
    return

  if not os.path.exists(args.dest):
    parser.error('Destination %s does not exist!' % args.dest)

  patch_test_image = os.path.isfile(args.dest)

  with (sys_utils.MountPartition(args.dest, 1, rw=True) if patch_test_image
        else DummyContext(args.dest)) as dest:

    installer = FactoryToolkitInstaller(
        src=src_root, dest=dest, no_enable=args.no_enable,
        non_cros=args.non_cros, apps=args.apps,
        active_test_list=args.active_test_list)

    print(installer.WarningMessage(args.dest if patch_test_image else None))

    if not args.yes:
      answer = input('*** Continue? [y/N] ')
      if not answer or answer[0] not in 'yY':
        sys.exit('Aborting.')

    if args.install_dirs:
      installer.InstallFactorySubDir(args.install_dirs)
    else:
      installer.Install()

if __name__ == '__main__':
  # makself interprets "LICENSE" environment variable string as license text and
  # will prompt user to accept before installation. For factory toolkit, we
  # don't want any user interaction in installation and the license is already
  # covered by ebuild or download platform like CPFE.
  os.putenv('LICENSE', '')
  main()
