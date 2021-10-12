# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Update vendor plugin firmware using fwupdtool.

Description
-----------
This test updates the vendor plugin firmware by calling fwupdtool. User has to
specify the path to firmware and also the name of the plugin to be updated.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

1. Firstly, this test will create a DUT link.
2. If the firmware image is from the station, the image would be sent to DUT.
3. If the firmware image is in release partition, the test mounts the release
   partition to get the image.
4. If the firmware image is in test partition, the test mounts the test
   partition to get the image.

Dependency
----------
- DUT link must be ready before running this test.
- `fwupdtool` on DUT.

Examples
--------
To update the nvme firmware with the image in DUT release partition,
add this in test list::

  {
    "pytest_name": "update_plugin_firmware",
    "args": {
      "firmware_file": "/path/to/firmware/file/image.cab",
      "plugin": "nvme"
    }
  }

To update the nvme firmware with the image in DUT test partition,
and allow downgrading the firmware version, add this in test list::

  {
    "pytest_name": "update_plugin_firmware",
    "args": {
      "allow_older": true,
      "firmware_file": "/path/to/firmware/file/image.cab",
      "from_release": false,
      "plugin": "nvme"
    }
  }
"""

import logging

from cros.factory.device import device_utils
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sys_utils


FWUPDTOOL = 'fwupdtool'


class UpdateUsingFwUpdTest(test_case.TestCase):

  ARGS = [
      Arg('allow_older', bool, 'Allow downgrading the firmware.',
          default=False),
      Arg('firmware_file', str, 'Name of the firmware binary file (.cab).'),
      Arg('from_release', bool, 'Get the firmware file from release rootfs.',
          default=True),
      Arg('plugin', str, 'Specify the name of the plugin.'),
  ]

  ui_class = test_ui.ScrollableLogUI

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._allow_older = self.args.allow_older
    self._firmware_file = None
    self._from_release = self.args.from_release
    self._plugin = self.args.plugin

  def runTest(self):
    if self.args.from_release:
      logging.info('Get firmware from release rootfs...')
      with sys_utils.MountPartition(self._dut.partitions.RELEASE_ROOTFS.path,
                                    dut=self._dut) as root:
        self._firmware_file = self._dut.path.join(root,
                                                  self.args.firmware_file[1:])
        self.UpdatePlugin()
    else:
      if self._dut.link.IsLocal():
        self._firmware_file = self.args.firmware_file
        self.UpdatePlugin()
      else:
        with self._dut.temp.TempFile() as dut_temp_file:
          self._dut.SendFile(self.args.firmware_file, dut_temp_file)
          self._firmware_file = dut_temp_file
          self.UpdatePlugin()

  def UpdatePlugin(self):
    # Skip reboot prompt by adding `--no-reboot-check`.
    update_command = [FWUPDTOOL, 'install', '--no-reboot-check']

    # We add `nocheck` in the comment to skip the blocked_term checking.
    # In older version of fwupdtool, the option `--plugins` is called
    # `--plugin-whitelist`. nocheck
    support_plugins = self._dut.CallOutput(
        '%s --help | grep -- --plugins' % FWUPDTOOL)

    if support_plugins:
      update_command += ['--plugins', self._plugin]
    else:
      update_command += ['--plugin-whitelist', self._plugin]  # nocheck

    if self._allow_older:
      update_command += ['--allow-older']
      logging.warning('Allow downgrading plugin %s firmware.', self._plugin)

    update_command += [self._firmware_file]
    logging.info('Update plugins: %s', update_command)
    returncode = self.ui.PipeProcessOutputToUI(update_command)

    self.assertEqual(returncode, 0, 'Firmware update failed: %d.' % returncode)
