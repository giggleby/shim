# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Checks and updates touch device firmware."""


import glob
import logging
import os
import unittest

from cros.factory.test import session
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


FIRMWARE_UPDATER = '/opt/google/touch/scripts/chromeos-touch-firmware-update.sh'
CONFIG_UPDATER = '/opt/google/touch/scripts/chromeos-touch-config-update.sh'


class UpdateTouchDeviceFWTest(unittest.TestCase):
  ARGS = [
      Arg('device_name', str, 'Name of the touch device as in'
          '/sys/bus/i2c/devices/\\*/name)'),
      Arg('fw_name', str, 'Expected firmware file name (in /lib/firmware)'),
      Arg('fw_version', str, 'Expected firmware version'),
  ]

  def run_updater_command(self, command):
    session.console.info('Running: %s', command)
    updater = process_utils.Spawn(command,
                                  log=True, read_stdout=True, shell=True)
    updater.wait()
    if updater.returncode != 0:
      error_message = f'Touch device {self.args.device_name} update failed.'
      logging.error(error_message)
      logging.error('  stdout: %s', updater.stdout_data)
      logging.error('  stderr: %s', updater.stderr_data)
      raise ValueError(error_message)

  def runTest(self):
    # Find the appropriate device sysfs file.
    devices = [
        x for x in glob.glob('/sys/bus/i2c/devices/*/name')
        if file_utils.ReadFile(x).strip() == self.args.device_name
    ]
    self.assertEqual(1, len(devices),
                     f'Expected to find one device but found {devices}')
    device_path = os.path.dirname(devices[0])

    expected_ver = getattr(self.args, 'fw_version')
    actual_ver = file_utils.ReadFile(os.path.join(device_path,
                                                  'fw_version')).strip()
    if expected_ver != actual_ver:
      logging.info('Updating firmware from version %s to version %s',
                   actual_ver, expected_ver)
      firmware_updater_cmd = (
          f'{FIRMWARE_UPDATER} -f -d {self.args.device_name} -n '
          f'{self.args.fw_name}')
      self.run_updater_command(firmware_updater_cmd)

    # Always force-update the device configuration
    logging.info('Updating device configuration.')
    config_updater_cmd = f'{CONFIG_UPDATER} -f -d {self.args.device_name}'
    self.run_updater_command(config_updater_cmd)
