# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""rsyncs goofy and runs on a remote device."""

import argparse
import glob
import logging
import os
import pipes
import re
import sys

from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test.env import paths
from cros.factory.test.test_lists import manager
from cros.factory.test.test_lists import test_list_common
from cros.factory.utils import cros_board_utils
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import ssh_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import sys_utils


SRCROOT = os.environ.get('CROS_WORKON_SRCROOT')


class GoofyRemoteException(Exception):
  """Goofy remote exception."""


def GetBoard(host):
  logging.info('Checking release board on %s...', host)
  release = ssh_utils.SpawnSSHToDUT([host, 'cat /etc/lsb-release'],
                                    check_output=True, log=True).stdout_data
  match = re.search(r'^CHROMEOS_RELEASE_BOARD=(.+)', release, re.MULTILINE)
  if not match:
    logging.warning('Unable to determine release board')
    return None
  return match.group(1)


def TweakTestLists(args):
  """Tweaks new-style test lists as required by the arguments.

  Note that this runs *on the target DUT*, not locally.

  Args:
    args: The arguments from argparse.
  """
  for path in glob.glob(os.path.join(test_list_common.TEST_LISTS_PATH, '*.py')):
    data = file_utils.ReadFile(path)

    def SubLine(variable_re, new_value, string):
      """Replaces certain assignments in the test list with a new value.

      We'll replace any line that begins with the given variable name
      and an equal sign.

      Args:
        variable_re: A regular expression matching the names of variables whose
            value is to be replaced.
        new_value: The new value of the variable.  We wrap this in repr() before
            substituting.
        string: The original contents of the test list.
      """
      return re.sub(
          r'^(\s*' +      # Beginning of line
          variable_re +   # The name of the variable we're looking for
          r'\s*=\s*)' +
          r'.+',          # The old value

          # Keep everything but the value in the original string;
          # replace that with new_value.
          lambda match_obj: match_obj.group(1) + repr(new_value),
          string,
          flags=re.MULTILINE)

    new_data = data
    if args.clear_password:
      new_data = SubLine('options.engineering_password_sha1', None, new_data)
    if args.shopfloor_host:
      new_data = SubLine('(?:shop_floor_host|shopfloor_host)',
                         args.shopfloor_host, new_data)
    if args.shopfloor_port:
      new_data = SubLine('(?:shop_floor_port|shopfloor_port)',
                         args.shopfloor_port, new_data)

    # Write out the file if anything has changed.
    if new_data != data:
      logging.info('Modified %s', path)
      file_utils.WriteFile(path, new_data)

  if args.test_list:
    manager.Manager.SetActiveTestList(args.test_list)
  else:
    file_utils.TryUnlink(test_list_common.ACTIVE_TEST_LIST_CONFIG_PATH)


def main():
  parser = argparse.ArgumentParser(
      description='Rsync and run Goofy on a remote device.')
  parser.add_argument('host', metavar='HOST',
                      help='host to run on')
  parser.add_argument('-a', dest='clear_state', action='store_true',
                      help='clear Goofy state and logs on device')
  parser.add_argument('-p', dest='clear_password',
                      action='store_true',
                      help='remove password from test_list')
  parser.add_argument('-s', dest='shopfloor_host',
                      help='set shopfloor host')
  parser.add_argument('--shopfloor_port', dest='shopfloor_port', type=int,
                      default=None, help='set shopfloor port')
  parser.add_argument('--board', '-b', dest='board',
                      help='board to use (default: auto-detect)')
  parser.add_argument('--project', '-j', dest='project',
                      help='project name to use (default: auto-detect)')
  parser.add_argument('--norestart', dest='restart', action='store_false',
                      help="don't restart Goofy")
  parser.add_argument('--hwid', action='store_true',
                      help='update HWID bundle')
  parser.add_argument('--run', '-r', dest='run_test',
                      help='the test to run on device')
  parser.add_argument('--test_list',
                      help=('test list to activate (defaults to the main test '
                            'list)'))
  parser.add_argument('--local', action='store_true',
                      help=('Rather than syncing the source tree, only '
                            'perform test list modifications locally. '
                            'This must be run only on the target device.'))
  args = parser.parse_args()

  logging.basicConfig(level=logging.INFO)

  if args.local:
    if sys_utils.InChroot():
      sys.exit('--local must be used only on the target device')
    TweakTestLists(args)
    return

  if not SRCROOT:
    sys.exit('goofy_remote must be run from within the chroot')

  process_utils.Spawn(['make', '--quiet'], cwd=paths.FACTORY_DIR,
                      check_call=True, log=True)
  board = args.board or GetBoard(args.host)

  # We need to rsync the public factory repo first to set up goofy symlink.
  # We need --force to remove the original goofy directory if it's not a
  # symlink, -l for re-creating the symlink on DUT, -K for following the symlink
  # on DUT.
  ssh_utils.SpawnRsyncToDUT(['-azlKC', '--force', '--exclude', '*.pyc'] + list(
      filter(os.path.exists, [
          os.path.join(paths.FACTORY_DIR, x)
          for x in ('bin', 'py', 'py_pkg', 'sh', 'third_party', 'init')
      ])) + [f'{args.host}:/usr/local/factory'], check_call=True, log=True)

  process_utils.Spawn(['make', f'par-overlay-{board}'], cwd=paths.FACTORY_DIR,
                      check_call=True, log=True)

  ssh_utils.SpawnRsyncToDUT([
      '-az', f'overlay-{board}/build/par/factory.par',
      f'{args.host}:/usr/local/factory/'
  ], cwd=paths.FACTORY_DIR, check_call=True, log=True)

  private_path = cros_board_utils.GetChromeOSFactoryBoardPath(board)
  if private_path:
    ssh_utils.SpawnRsyncToDUT(
        ['-azlKC', '--exclude', 'bundle'] +
        [private_path + '/', f'{args.host}:/usr/local/factory/'],
        check_call=True, log=True)

  # Call goofy_remote on the remote host, allowing it to tweak test lists.
  ssh_utils.SpawnSSHToDUT([args.host, 'goofy_remote', '--local'] +
                          [pipes.quote(x) for x in sys.argv[1:]],
                          check_call=True, log=True)

  if args.hwid:
    project = args.project
    if not project:
      # TODO(yhong): Detect the real project name instead of board name.
      if board:
        project = board.split('_')[-1]
    if not project:
      sys.exit('Cannot update hwid without project name')
    chromeos_hwid_path = os.path.join(
        os.path.dirname(paths.FACTORY_DIR), 'chromeos-hwid')
    process_utils.Spawn(['./create_bundle', '--version', '3',
                         project.upper()], cwd=chromeos_hwid_path,
                        check_call=True, log=True)
    ssh_utils.SpawnSSHToDUT(
        [args.host, 'bash'],
        stdin=open(  # pylint: disable=consider-using-with
            os.path.join(chromeos_hwid_path,
                         hwid_utils.GetHWIDBundleName(project)),
            encoding='utf8'),
        check_call=True,
        log=True)

  # Make sure all the directories and files have correct permissions.  This is
  # essential for Chrome to load the factory test extension.
  ssh_utils.SpawnSSHToDUT([
      args.host, 'find', '/usr/local/factory', '-type', 'd', '-exec',
      'chmod 755 {} +'
  ], check_call=True, log=True)
  ssh_utils.SpawnSSHToDUT([
      args.host, 'find', '/usr/local/factory', '-type', 'f', '-exec',
      'chmod go+r {} +'
  ], check_call=True, log=True)

  if args.restart:
    ssh_utils.SpawnSSHToDUT(
        [args.host, '/usr/local/factory/bin/factory_restart'] +
        (['-a'] if args.clear_state else []), check_call=True, log=True)

  if args.run_test:

    @sync_utils.RetryDecorator(max_attempt_count=10, interval_sec=5,
                               timeout_sec=float('inf'))
    def GoofyRpcRunTest():
      return ssh_utils.SpawnSSHToDUT(
          [args.host, 'goofy_rpc', r'RunTest\(\"' + args.run_test + r'\"\)'],
          check_call=True, log=True)

    GoofyRpcRunTest()

if __name__ == '__main__':
  main()
