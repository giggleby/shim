# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Update Fingerprint MCU firmware.

Description
-----------
This test provides two functionalities, toggled by the test argument ``method``.

1. In `update mode`, this test updates FPMCU firmware. The firmware image is
   either from a given path in the station or on the DUT, or from the release
   partition on the DUT.
2. In `check mode`, this test checks if the running FPMCU firmware version is
   the same as the given firmware image.


Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

1. Firstly, this test will create a DUT link.
2. If the FPMCU firmware image is from the station, the image would be sent
   to DUT.
3. If the FPMCU firmware image is not specified or the path is in release
   partition, the test mounts the release partition and get the FPMCU firmware.
4. If `method` is set to `UPDATE`, DUT runs `flash_fp_mcu` to update FPMCU
   firmware using the specified FPMCU firmware image.
5. If `method` is set to `CHECK_VERSION`, DUT runs `futility` and `ectool` to
   check if the running FPMCU firmware version is the same as the specified
   FPMCU firmware.

Dependency
----------
- DUT link must be ready before running this test.
- `flash_fp_mcu` (from ec-utils-test package) on DUT.
- `futility`, `ectool`, `crossystem`, and `cros_config` on DUT.
- FPMCU firmware image must be prepared.
- Hardware write-protection must be disabled (`crossystem wpsw_cur` returns 0).

Examples
--------
To update fingerprint firmware with the image in DUT release partition,
add this in test list::

  {
    "pytest_name": "update_fpmcu_firmware"
  }

To update fingerprint firmware with a specified image in the station
(only recommended in pre-PVT stages)::

  {
    "pytest_name": "update_fpmcu_firmware",
    "args": {
      "firmware_file": "/path/on/station/to/image.bin",
      "from_release": false
    }
  }

To check if fingerprint firmware version is the same as the fingerprint firmware
in the release image::

  {
    "pytest_name": "update_fpmcu_firmware",
    "args": {
      "method": "CHECK_VERSION"
    }
  }
"""

import logging
import os

from cros.factory.device import device_utils
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.test.utils import fpmcu_utils
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sys_utils
from cros.factory.utils import type_utils

FLASHTOOL = '/usr/local/bin/flash_fp_mcu'
FPMCU_FW_DIR_UNDER_ROOTFS = 'opt/google/biod/fw'


class UpdateFpmcuFirmwareTest(test_case.TestCase):
  _METHOD_TYPE = type_utils.Enum(['UPDATE', 'CHECK_VERSION'])

  ARGS = [
      Arg('firmware_file', str, 'The full path of the firmware binary file.',
          default=None),
      Arg('from_release', bool, 'Find the firmware from release rootfs',
          default=True),
      Arg('method', _METHOD_TYPE,
          'Specify whether to update the FPMCU firmware or to check the '
          'firmware version.',
          default=_METHOD_TYPE.UPDATE)
  ]

  ui_class = test_ui.ScrollableLogUI

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._fpmcu = fpmcu_utils.FpmcuDevice(self._dut)

  def runTest(self):
    fpmcu_board = self._dut.CallOutput(
        ['cros_config', '/fingerprint', 'board'])
    if not fpmcu_board:
      raise type_utils.Error('No fingerprint board found in cros_config')

    if self.args.firmware_file is None:
      logging.info('No specified path to FPMCU FW image')
      self.assertTrue(
          self.args.from_release,
          'Must set "from_release" to True if not specifying firmware_file')

      logging.info('Get FPMCU FW image from the release rootfs partition.')
      with sys_utils.MountPartition(
          self._dut.partitions.RELEASE_ROOTFS.path, dut=self._dut) as root:
        pattern = self._dut.path.join(root, FPMCU_FW_DIR_UNDER_ROOTFS,
                                      '%s_v*.bin' % fpmcu_board)
        fpmcu_fw_files = self._dut.Glob(pattern)
        self.assertEqual(len(fpmcu_fw_files), 1,
                         'No uniquely matched FPMCU firmware blob found')
        self.args.firmware_file = os.path.join(
            '/', os.path.relpath(fpmcu_fw_files[0], root))
    else:
      self.assertEqual(self.args.firmware_file[0], '/',
                       'firmware_file should be a full path')

    if self.args.method == self._METHOD_TYPE.UPDATE:
      method_func = self.UpdateFpmcuFirmware
    else:
      method_func = self.CheckFpmcuFirmwareVersion

    if self.args.from_release:
      with sys_utils.MountPartition(
          self._dut.partitions.RELEASE_ROOTFS.path, dut=self._dut) as root:
        method_func(os.path.join(root, self.args.firmware_file[1:]))
    else:
      if self._dut.link.IsLocal():
        method_func(self.args.firmware_file)
      else:
        with self._dut.temp.TempFile() as dut_temp_file:
          self._dut.SendFile(self.args.firmware_file, dut_temp_file)
          method_func(dut_temp_file)

  def UpdateFpmcuFirmware(self, firmware_file):
    """Update FPMCU firmware by `flash_fp_mcu`."""
    # Before updating FPMCU firmware, HWWP must be disabled.
    if self._dut.CallOutput(['crossystem', 'wpsw_cur']).strip() != '0':
      raise type_utils.Error('Hardware write protection is enabled.')

    try:
      old_ro_ver, old_rw_ver = self._fpmcu.GetFpmcuFirmwareVersion()
      logging.info('Current FPMCU RO: %s, RW: %s', old_ro_ver, old_rw_ver)
    except Exception:
      logging.exception('Fail to read the current FPMCU RO/RW FW versions.')

    bin_ro_ver, bin_rw_ver = self.GetFirmwareVersionFromFile(firmware_file)
    logging.info('Ready to update FPMCU firmware to RO: %s, RW: %s.',
                 bin_ro_ver, bin_rw_ver)

    flash_cmd = [FLASHTOOL, firmware_file]
    session.console.debug(self._dut.CallOutput(flash_cmd))

  def CheckFpmcuFirmwareVersion(self, firmware_file):
    """Check if the current FPMCU firmware version matches the firmware blob."""
    actual_ro_ver, actual_rw_ver = self._fpmcu.GetFpmcuFirmwareVersion()
    expect_ro_ver, expect_rw_ver = self.GetFirmwareVersionFromFile(
        firmware_file)
    self.assertEqual(actual_ro_ver, expect_ro_ver,
                     'FPMCU RO: %s does not match the expected RO: %s.'
                     % (actual_ro_ver, expect_ro_ver))
    self.assertEqual(actual_rw_ver, expect_rw_ver,
                     'FPMCU RW: %s does not match the expected RW: %s.'
                     % (actual_rw_ver, expect_rw_ver))

  def GetFirmwareVersionFromFile(self, firmware_file):
    """Read RO and RW FW version from the FW binary file."""
    ro_ver = self.ReadFmapArea(firmware_file, "RO_FRID")
    rw_ver = self.ReadFmapArea(firmware_file, "RW_FWID")
    return (ro_ver, rw_ver)

  def ReadFmapArea(self, firmware_file, area_name):
    """Read fmap from a specified area_name."""
    get_fmap_cmd = ["futility", "dump_fmap", "-p", firmware_file, area_name]
    get_fmap_output = self._dut.CheckOutput(get_fmap_cmd)
    if not get_fmap_output:
      raise type_utils.Error('Fmap area name might be wrong?')
    unused_name, offset, size = get_fmap_output.split()
    get_ro_ver_cmd = ["dd", "bs=1", "skip=%s" % offset,
                      "count=%s" % size, "if=%s" % firmware_file]
    return self._dut.CheckOutput(get_ro_ver_cmd).strip('\x00')
