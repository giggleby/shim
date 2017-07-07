#!/usr/bin/python -u
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
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

import factory_common  # pylint: disable=unused-import
from cros.factory.hwid.v3 import common as hwid_common
from cros.factory.test.e2e_test.common import AutomationMode
from cros.factory.test.env import paths
from cros.factory.test.test_lists import test_lists
from cros.factory.tools import build_board
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils.ssh_utils import SpawnRsyncToDUT
from cros.factory.utils.ssh_utils import SpawnSSHToDUT
from cros.factory.utils.sync_utils import Retry
from cros.factory.utils.sys_utils import InChroot


SRCROOT = os.environ.get('CROS_WORKON_SRCROOT')

DEVICE_TAG = 'run_goofy_device'
PRESENTER_TAG = 'run_goofy_presenter'
HOST_BASED_ROLES = {'device': [DEVICE_TAG],
                    'presenter': [PRESENTER_TAG],
                    'both': [DEVICE_TAG, PRESENTER_TAG]}


class GoofyRemoteException(Exception):
  """Goofy remote exception."""
  pass


def GetBoard(host):
  logging.info('Checking release board on %s...', host)
  release = SpawnSSHToDUT([host, 'cat /etc/lsb-release'],
                          check_output=True, log=True).stdout_data
  match = re.search(r'^CHROMEOS_RELEASE_BOARD=(.+)', release, re.MULTILINE)
  if not match:
    logging.warn('Unable to determine release board')
    return None
  return match.group(1)


def TweakTestLists(args):
  """Tweaks new-style test lists as required by the arguments.

  Note that this runs *on the target DUT*, not locally.

  Args:
    args: The arguments from argparse.
  """
  for path in glob.glob(os.path.join(test_lists.TEST_LISTS_PATH, '*.py')):
    with open(path) as f:
      data = f.read()

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
      with open(path, 'w') as f:
        logging.info('Modified %s', path)
        f.write(new_data)

  if args.test_list:
    test_lists.SetActiveTestList(args.test_list)
  else:
    file_utils.TryUnlink(test_lists.ACTIVE_PATH)

  if args.ignore_test_lists:
    test_lists.SetIgnoredTestListModules(args.ignore_test_lists.split(','))
  else:
    file_utils.TryUnlink(test_lists.IGNORE_PATH)


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
  parser.add_argument('--role', dest='role',
                      help=('Set the role of the device. Must be one of: ' +
                            ', '.join(HOST_BASED_ROLES)))
  parser.add_argument('--automation-mode',
                      choices=[m.lower() for m in AutomationMode],
                      default='none', help='Factory test automation mode.')
  parser.add_argument('--no-auto-run-on-start', dest='auto_run_on_start',
                      action='store_false', default=True,
                      help=('do not automatically run the test list on goofy '
                            'start; this is only valid when factory test '
                            'automation is enabled'))
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
  parser.add_argument('--ignore_test_lists',
                      help='Comma-separated list of test lists to ignore '
                           '(defaults to empty)')
  parser.add_argument('--local', action='store_true',
                      help=('Rather than syncing the source tree, only '
                            'perform test list modifications locally. '
                            'This must be run only on the target device.'))
  args = parser.parse_args()

  logging.basicConfig(level=logging.INFO)

  if args.role and args.role not in HOST_BASED_ROLES:
    sys.exit('--role must be one of ' + ', '.join(HOST_BASED_ROLES))

  def RunLocallyOrRemotely(cmds):
    if args.local:
      Spawn(cmds, check_call=True, log=True)
    else:
      SpawnSSHToDUT([args.host] + cmds, check_call=True, log=True)

  def SetHostBasedRole():
    if args.role:
      for tag in [DEVICE_TAG, PRESENTER_TAG]:
        if tag in HOST_BASED_ROLES[args.role]:
          RunLocallyOrRemotely(['touch', '/usr/local/factory/init/%s' % tag])
        else:
          RunLocallyOrRemotely(
              ['rm', '--force', '/usr/local/factory/init/%s' % tag])

  if args.local:
    if InChroot():
      sys.exit('--local must be used only on the target device')
    TweakTestLists(args)
    SetHostBasedRole()
    return

  if not SRCROOT:
    sys.exit('goofy_remote must be run from within the chroot')

  if not args.auto_run_on_start and args.automation_mode == 'none':
    sys.exit('--no-auto-run-on-start must be used only when factory test '
             'automation is enabled')

  Spawn(['make', '--quiet'], cwd=paths.FACTORY_DIR,
        check_call=True, log=True)
  board = args.board or GetBoard(args.host)

  # We need to rsync the public factory repo first to set up goofy symlink.
  # We need --force to remove the original goofy directory if it's not a
  # symlink, -l for re-creating the symlink on DUT, -K for following the symlink
  # on DUT.
  SpawnRsyncToDUT(
      ['-azlKC', '--force', '--exclude', '*.pyc'] +
      filter(os.path.exists,
             [os.path.join(paths.FACTORY_DIR, x)
              for x in ('bin', 'py', 'py_pkg', 'sh', 'third_party', 'init')]) +
      ['%s:/usr/local/factory' % args.host],
      check_call=True, log=True)

  Spawn(['make', 'par-overlay-%s' % board], cwd=paths.FACTORY_DIR,
        check_call=True, log=True)

  SpawnRsyncToDUT(
      ['-az', 'overlay-%s/build/par/factory.par' % board,
       '%s:/usr/local/factory/' % args.host],
      cwd=paths.FACTORY_DIR, check_call=True, log=True)
  SetHostBasedRole()

  private_path = build_board.GetChromeOSFactoryBoardPath(board)
  if private_path:
    SpawnRsyncToDUT(
        ['-azlKC', '--exclude', 'bundle'] +
        [private_path + '/', '%s:/usr/local/factory/' % args.host],
        check_call=True, log=True)

  # Call goofy_remote on the remote host, allowing it to tweak test lists.
  SpawnSSHToDUT([args.host, 'goofy_remote', '--local'] +
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
    Spawn(['./create_bundle', '--version', '3', project.upper()],
          cwd=chromeos_hwid_path, check_call=True, log=True)
    SpawnSSHToDUT([args.host, 'bash'],
                  stdin=open(os.path.join(
                      chromeos_hwid_path,
                      hwid_common.GetHWIDBundleName(project))),
                  check_call=True, log=True)

  # Make sure all the directories and files have correct permissions.  This is
  # essential for Chrome to load the factory test extension.
  SpawnSSHToDUT([args.host, 'find', '/usr/local/factory', '-type', 'd',
                 '-exec', 'chmod 755 {} +'], check_call=True, log=True)
  SpawnSSHToDUT([args.host, 'find', '/usr/local/factory', '-type', 'f',
                 '-exec', 'chmod go+r {} +'], check_call=True, log=True)

  if args.restart:
    SpawnSSHToDUT([args.host, '/usr/local/factory/bin/factory_restart'] +
                  (['-a'] if args.clear_state else []) +
                  ['--automation-mode', '%s' % args.automation_mode] +
                  ([] if args.auto_run_on_start
                   else ['--no-auto-run-on-start']),
                  check_call=True, log=True)

  if args.run_test:
    def GoofyRpcRunTest():
      return SpawnSSHToDUT(
          [args.host, 'goofy_rpc', r'RunTest\(\"%s\"\)' % args.run_test],
          check_call=True, log=True)
    Retry(max_retry_times=10, interval=5, callback=None, target=GoofyRpcRunTest)

if __name__ == '__main__':
  main()
