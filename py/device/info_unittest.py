#!/usr/bin/env python3
#
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Unittest for SystemInfo."""


import logging
import unittest
from unittest import mock

from cros.factory.device import info as info_module


MOCK_RELEASE_IMAGE_LSB_RELEASE = ('GOOGLE_RELEASE=5264.0.0\n'
                                  'CHROMEOS_RELEASE_TRACK=canary-channel\n')

MOCK_CROSSYSTEM = """
ecfw_act                = RW                             # [RO/str] Active EC firmware
fwid                    = Google_Mock.12345.0.0          # [RO/str] Active firmware ID
hwid                    = Mock-ZZCR mock-hwid            # [RO/str] Hardware ID
mainfw_act              = A                              # [RO/str] Active main firmware
mainfw_type             = developer                      # [RO/str] Active main firmware type
ro_fwid                 = Google_Mock.12345.0.0          # [RO/str] Read-only firmware ID
wpsw_cur                = 0                              # [RO/int] Firmware write protect hardware switch current position
"""

MOCK_LSCPU = """
CPU(s):                          8
Model name:                      Vendor ID 1234
"""

MOCK_CROSID = """
SKU='95'
CONFIG_INDEX='10'
FIRMWARE_MANIFEST_KEY='mock_fw'
"""

class SystemInfoTest(unittest.TestCase):
  """Unittest for SystemInfo."""

  @mock.patch('cros.factory.device.info.MountDeviceAndReadFile')
  def testReleaseLSB(self, mount_and_read_mock):
    dut = mock.MagicMock()
    dut.partitions.RELEASE_ROOTFS.path = '/dev/sda5'
    mount_and_read_mock.return_value = MOCK_RELEASE_IMAGE_LSB_RELEASE

    info = info_module.SystemInfo(dut)
    self.assertEqual('5264.0.0', info.release_image_version)
    self.assertEqual('canary-channel', info.release_image_channel)
    # The cached release image version will be used in the second time.
    self.assertEqual('5264.0.0', info.release_image_version)
    self.assertEqual('canary-channel', info.release_image_channel)

    mount_and_read_mock.assert_called_once_with('/dev/sda5', '/etc/lsb-release',
                                                dut=dut)

  def testCrossystem(self):
    dut = mock.MagicMock()
    dut.CheckOutput.return_value = MOCK_CROSSYSTEM
    info = info_module.SystemInfo(dut)
    self.assertEqual('RW', info.ecfw_act)
    self.assertEqual('Google_Mock.12345.0.0', info.firmware_version)
    self.assertEqual('Mock-ZZCR mock-hwid', info.hwid)
    self.assertEqual('A', info.mainfw_act)
    self.assertEqual('developer', info.mainfw_type)
    self.assertEqual('Google_Mock.12345.0.0', info.ro_firmware_version)
    self.assertEqual('0', info.hwwp)

  def testLscpu(self):
    dut = mock.MagicMock()
    dut.CheckOutput.return_value = MOCK_LSCPU
    info = info_module.SystemInfo(dut)
    self.assertEqual(8, info.cpu_count)
    self.assertEqual('Vendor ID 1234', info.cpu_model)

  def testCrosID(self):
    dut = mock.MagicMock()
    dut.CheckOutput.return_value = MOCK_CROSID
    info = info_module.SystemInfo(dut)
    self.assertEqual(
        {
            'sku': '0x5f',
            'config_index': 10,
            'firmware_manifest_key': 'mock_fw',
        }, info.crosid)


if __name__ == '__main__':
  logging.basicConfig(
      format='%(asctime)s:%(filename)s:%(lineno)d:%(levelname)s:%(message)s',
      level=logging.DEBUG)
  unittest.main()
