# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Update Cr50 firmware."""

import logging
import os
import subprocess
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sys_utils

_TEST_TITLE = i18n_test_ui.MakeI18nLabel('Update Firmware')
_CSS = '#state { text-align: left; }'

TRUNKS_SEND = '/usr/sbin/trunks_send'
FIRMWARE_RELATIVE_PATH = '/opt/google/cr50/firmware/cr50.bin.prod'


class UpdateCr50FirmwareTest(unittest.TestCase):
  ARGS = [
      Arg('firmware_file', str, 'The full path of the firmware.',
          optional=True),
      Arg('from_release', bool, 'Find the firmware from release rootfs.',
          optional=True, default=True),
      Arg('force', bool, 'Force update',
          optional=True, default=False),
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self._ui = test_ui.UI()
    self._template = ui_templates.OneScrollableSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    self._ui.AppendCSS(_CSS)

  def UpdateCr50Firmware(self):
    """Update Cr50 firmware."""
    self.assertEqual(
        1, len(filter(None, [self.args.firmware_file, self.args.from_release])),
        'Must specify exactly one of "firmware_file" or "from_release".')
    if self.args.firmware_file:
      if self.dut.link.IsLocal():
        self._UpdateCr50Firmware(self.args.firmware_file)
      else:
        with self.dut.temp.TempFile() as dut_temp_file:
          self.dut.SendFile(self.args.firmware_file, dut_temp_file)
          self._UpdateCr50Firmware(dut_temp_file)
    elif self.args.from_release:
      with sys_utils.MountPartition(
          self.dut.partitions.RELEASE_ROOTFS.path, dut=self.dut) as root:
        firmware_path = os.path.join(root, FIRMWARE_RELATIVE_PATH)
        self._UpdateCr50Firmware(firmware_path)

  def _UpdateCr50Firmware(self, firmware_file):
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
