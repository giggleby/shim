# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Update Cr50 firmware.

Description
-----------
This test calls `trunks_send` on DUT to update Cr50 firmware. The Cr50 firmware
image to update is either from a given path in station or from the release
partition on DUT.

`trunks_send` is a program with ability to update Cr50 firmware. Notice that
some older factory branches might have only `usb_updater` but no `trunks_send`.

To prepare Cr50 firmware image on station, download the release image with
desired Cr50 firmware image and find the image in DEFAULT_FIRMWARE_PATH below.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

1. Firstly, this test will create a DUT link.
2. If Cr50 firmware image source is from station, the image would be sent to
   DUT. Else, the release partition on DUT will be mounted.
3. DUT runs `trunks_send` to update Cr50 firmware.

Dependency
----------
- DUT link must be ready before running this test.
- `trunks_send` on DUT.
- Cr50 firmware image must be prepared.

Examples
--------
To update Cr50 firmware with the Cr50 firmware image in DUT release partition,
add this in test list::

  {
    "pytest_name": "update_cr50_firmware"
  }

To update Cr50 firmware with the Cr50 firmware image in station::

  {
    "pytest_name": "update_cr50_firmware",
    "args": {
      "firmware_file": "/path/on/station/to/cr50.bin.prod",
      "from_release": false
    }
  }
"""

import logging
import os
import subprocess
import unittest
import re

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sys_utils

_CSS = 'test-template { text-align: left; }'

TRUNKS_SEND = '/usr/sbin/trunks_send'
GSCTOOL = '/usr/sbin/gsctool'
DEFAULT_FIRMWARE_PATH = '/opt/google/cr50/firmware/cr50.bin.prod'
BOARD_ID_FLAG_RE = re.compile(r'^RO_A:[^\[]*\[[0-9A-F]*:[0-9A-F]*:([01]*)\]',
                              re.MULTILINE)
PREPVT_FLAG_MASK = 0x7F


class UpdateCr50FirmwareTest(unittest.TestCase):
  ARGS = [
      Arg('firmware_file', str, 'The full path of the firmware.',
          optional=True),
      Arg('from_release', bool, 'Find the firmware from release rootfs.',
          optional=True, default=True),
      Arg('force', bool, 'Force update',
          optional=True, default=False),
      Arg('skip_prepvt_flag_check',
          bool, 'Skip prepvt flag check. For non-dogfood devcies, '
          'we should always use prod firmware, rather than prepvt one. '
          'A dogfood device can use prod firmware, as long as the board id'
          'setting is correct. The dogfood device will update to the prepvt '
          'firmware when first time boot to recovery image. '
          'http://crbug.com/802235',
          default=False)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self._ui = test_ui.UI(css=_CSS)
    self._template = ui_templates.OneScrollableSection(self._ui)

  def UpdateCr50Firmware(self):
    """Update Cr50 firmware."""
    if self.args.firmware_file is None:
      self.assertEqual(
          self.args.from_release, True,
          'Must set "from_release" to True if not specifiying firmware_file')
      self.args.firmware_file = DEFAULT_FIRMWARE_PATH

    self.assertEqual(self.args.firmware_file[0], '/',
                     'firmware_file should be a full path')

    if self.args.from_release:
      with sys_utils.MountPartition(
          self.dut.partitions.RELEASE_ROOTFS.path, dut=self.dut) as root:
        self._UpdateCr50Firmware(
            os.path.join(root, self.args.firmware_file[1:]))
    else:
      if self.dut.link.IsLocal():
        self._UpdateCr50Firmware(self.args.firmware_file)
      else:
        with self.dut.temp.TempFile() as dut_temp_file:
          self.dut.SendFile(self.args.firmware_file, dut_temp_file)
          self._UpdateCr50Firmware(dut_temp_file)

  def _IsPrePVTFirmware(self, firmware_file):
    p = self.dut.CheckOutput([GSCTOOL, '-b', firmware_file]).strip()
    board_id_flag = int(BOARD_ID_FLAG_RE.search(p).group(1), 16)
    logging.info('Cr50 firmware board ID flag: %s', hex(board_id_flag))
    testlog.LogParam(
        'cr50_firmware_file_info', p, description='Output of gsctool -b.')
    return board_id_flag & PREPVT_FLAG_MASK

  def _UpdateCr50Firmware(self, firmware_file):
    if not self.args.skip_prepvt_flag_check:
      if self._IsPrePVTFirmware(firmware_file):
        raise ValueError('Cr50 firmware board ID flag is PrePVT.')
    if self.args.force:
      cmd = [TRUNKS_SEND, '--force', '--update', firmware_file]
    else:
      cmd = [TRUNKS_SEND, '--update', firmware_file]
    p = self.dut.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, log=True)

    for line in iter(p.stdout.readline, ''):
      logging.info(line.strip())
      self._template.SetState(test_ui.Escape(line), append=True)

    if p.poll() != 0:
      self._ui.Fail('Cr50 firmware update failed: %d.' % p.returncode)
    else:
      self._ui.Pass()

  def runTest(self):
    self._ui.RunInBackground(self.UpdateCr50Firmware)
    self._ui.Run()
