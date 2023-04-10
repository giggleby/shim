# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import unittest

from cros.factory.device import device_utils
from cros.factory.test.env import paths
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


class OfflineTestError(Exception):
  pass

class OfflineTest(unittest.TestCase):

  class Shutdown(str, enum.Enum):
    REBOOT = 'REBOOT'
    POWEROFF = 'POWEROFF'
    NO_ACTION = 'NO_ACTION'

    def __str__(self):
      return self.name

  class Action(str, enum.Enum):
    DEPLOY = 'DEPLOY'

    def __str__(self):
      return self.name

  DEPLOY_ARGS = [
      Arg(
          'shutdown', Shutdown, 'What to do after tests are deployed (One of '
          f'{list(Shutdown.__members__)})'),
      Arg('test_spec_file', str,
          'A JSON file to specify which tests are running'),
      Arg('start_up_service', bool, 'Do you want to run the tests on start up?',
          default=True)
  ]

  ARGS = [Arg('action', Action, f'one of {list(Action.__members__)}')
         ] + DEPLOY_ARGS

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def SetUpEnvironment(self):
    """Pack and send every thing under factory/py"""
    if self.dut.link.IsLocal():
      # DUT is current machine, so the factory environment is already here
      return

    root = paths.FACTORY_DIR

    # make tar (tar command should be available on chromebooks and android
    # devices)
    with file_utils.UnopenedTemporaryFile(suffix='.tar') as tarfile:
      included_paths = ['py', 'py_pkg', 'third_party', 'bin']
      process_utils.Spawn(
          ['tar', '-cf', tarfile, '--force', '--exclude', '*.pyc'] +
          ['-C', root] + included_paths,
          check_call=True)

      uploaded_file = '/tmp/factory.tar'
      # push to dut
      self.dut.link.Push(tarfile, uploaded_file)

    dut_root = self.dut.storage.GetFactoryRoot()
    # make sure dut_root is writable
    if not self.dut.storage.Remount(dut_root):
      raise OfflineTestError(f'failed to make dut:{dut_root} writable')

    self.dut.Call(['rm', '-rf', dut_root])
    self.dut.CheckCall(['mkdir', '-p', dut_root])
    self.dut.CheckCall(['tar', '-xf', uploaded_file, '-C', dut_root])

  def runTest(self):
    if self.args.action == self.Action.DEPLOY:
      self.SetUpEnvironment()
