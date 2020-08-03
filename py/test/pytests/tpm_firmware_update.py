# Copyright (c) 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Updates TPM firmware if needed"""

import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.device import device_utils
from cros.factory.utils import sync_utils
from cros.factory.utils.arg_utils import Arg


class TPMFirmwareUpdate(unittest.TestCase):
  ARGS = [
      Arg('tpm_update_supported_version', str, 'Check tpm_version needs to be updated or not',
          default=None),
      Arg('tpm_tool_dir', str, 'The directory for tpm tool', default=''),
      Arg('tpm_tool', str, 'TPM tool filename', default='TPMFactoryUpd'),
      Arg('tpm_firmware_bin', str, 'TPM firmware binary filename', default='')
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def runTest(self):
    if not self.args.tpm_update_supported_version:
      return

    output = self.dut.CheckOutput(['tpm_version'], log=True)

    # Check tpm_version on DUT equals to given tpm_update_supported_version or not. If
    # yes, needs to update firmware.
    if self.args.tpm_update_supported_version in output:

      tpm_tool_path = self.dut.path.join(self.args.tpm_tool_dir, self.args.tpm_tool)
      tpm_firmware_bin_path = self.dut.path.join(self.args.tpm_tool_dir, self.args.tpm_firmware_bin)

      self.assertTrue(self.dut.path.exists(tpm_tool_path))
      self.assertTrue(self.dut.path.exists(tpm_firmware_bin_path))

      self.dut.CheckCall(['crossystem', 'clear_tpm_owner_request=1'], log=True)
      self.dut.CheckCall(['stop', 'tcsd'], log=True)
      self.dut.CheckCall([tpm_tool_path, '-update', 'tpm12-takeownership',
                          '-firmware', tpm_firmware_bin_path], log=True)
      self.dut.CheckCall(['reboot'], log=True)

      # Wait for DUT reboot.
      time.sleep(5)
      sync_utils.WaitFor(self.dut.IsReady, timeout_secs=60, poll_interval=1)
