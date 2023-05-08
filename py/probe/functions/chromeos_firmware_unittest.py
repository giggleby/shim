#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import hashlib
import os
import tempfile
import unittest
from unittest import mock

from cros.factory.probe.functions import chromeos_firmware
from cros.factory.utils import file_utils


class ChromeosFirmwareTest(unittest.TestCase):

  DEV_KEY = 'b11d74edd286c144e1135b49e7f0bc20cf041f10'
  ROOTFS_FP_FIRMWARE_DIR = 'opt/google/biod/fw'

  def setUp(self):
    self.fake_rootfs = tempfile.mkdtemp()

    patcher = mock.patch(
        'cros.factory.gooftool.common.Util.GetReleaseRootPartitionPath')
    self.fake_get_release_rootfs = patcher.start()
    self.fake_get_release_rootfs.return_value = self.fake_rootfs
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.utils.sys_utils.MountPartition')
    self.fake_mount = patcher.start()
    self.fake_mount.return_value.__enter__.return_value = self.fake_rootfs
    self.addCleanup(patcher.stop)

    patcher = mock.patch(
        'cros.factory.external.chromeos_cli.cros_config.CrosConfig')
    self.mock_cros_config = patcher.start()
    self.mock_cros_config.return_value.GetFingerPrintBoard.return_value = (
        'board')
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.gooftool.crosfw.FirmwareImage')
    self.mock_fw_image = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.utils.process_utils.CheckOutput')
    self.mock_check_output = patcher.start()
    self.addCleanup(patcher.stop)

  def _CreateFakeFPFirmware(self, filename):
    fw_dir = os.path.join(self.fake_rootfs, self.ROOTFS_FP_FIRMWARE_DIR)
    file_utils.TryMakeDirs(fw_dir)
    file_utils.TouchFile(os.path.join(fw_dir, filename))

  def testGetFirmwareKeys(self):
    self.mock_check_output.return_value = 'Key sha1sum: somehashvalue'
    keys = chromeos_firmware.GetFirmwareKeys('unused_path')
    self.assertEqual(keys, {
        'key_recovery': 'kv3#somehashvalue',
        'key_root': 'kv3#somehashvalue'
    })

  def testGetFirmwareKeys_DevKeys(self):
    self.mock_check_output.return_value = f'Key sha1sum: {self.DEV_KEY}'
    keys = chromeos_firmware.GetFirmwareKeys('unused_path')
    self.assertEqual(
        keys, {
            'key_recovery': f'kv3#{self.DEV_KEY}#devkeys/rootkey',
            'key_root': f'kv3#{self.DEV_KEY}#devkeys/rootkey',
        })

  def testGetFirmwareKeys_MissingSha1Sum(self):
    self.mock_check_output.return_value = 'Key not_sha1sum: somehashvalue'
    keys = chromeos_firmware.GetFirmwareKeys('unused_path')
    self.assertEqual(keys, {
        'key_recovery': None,
        'key_root': None
    })

  @mock.patch('cros.factory.utils.file_utils.ReadFile', mock.Mock())
  def testCalculateFirmwareHashes_EcRoHash(self):

    def MockHasSection(section):
      return section in ('EC_RO', 'RO_FRID')

    def MockGetSection(section):
      return {
          'EC_RO': b'ec_ro',
          'RO_FRID': b'version_string'
      }[section]

    mock_fw_image = self.mock_fw_image.return_value
    mock_fw_image.has_section.side_effect = MockHasSection
    mock_fw_image.get_section.side_effect = MockGetSection
    mock_fw_image.get_fmap_blob.return_value = b''

    expected = {
        'hash': hashlib.sha256(b'ec_ro').hexdigest(),
        'version': 'version_string'
    }
    self.assertEqual(expected,
                     chromeos_firmware.CalculateFirmwareHashes('unused_path'))

  @mock.patch('cros.factory.utils.file_utils.ReadFile', mock.Mock())
  def testCalculateFirmwareHashes_MainRoHash(self):

    def MockHasSection(section):
      return section in ('GBB', 'RO_FRID', 'RO_SECTION')

    def MockGetSection(section):
      return {
          'GBB': b'gbb',
          'RO_SECTION': b'ro_section',
          'RO_FRID': b'version_string'
      }[section]

    mock_fw_image = self.mock_fw_image.return_value
    mock_fw_image.has_section.side_effect = MockHasSection
    mock_fw_image.get_section.side_effect = MockGetSection
    mock_fw_image.get_fmap_blob.return_value = b''

    expected = {
        'hash': hashlib.sha256(b'ro_section').hexdigest(),
        'version': 'version_string'
    }
    self.assertEqual(expected,
                     chromeos_firmware.CalculateFirmwareHashes('unused_path'))

  @mock.patch('cros.factory.utils.file_utils.ReadFile', mock.Mock())
  def testCalculateFirmwareHashes_FailedToLoadFW(self):
    self.mock_fw_image.side_effect = Exception
    self.assertIsNone(chromeos_firmware.CalculateFirmwareHashes('unused_path'))

  @mock.patch('cros.factory.utils.fmap.FirmwareImage')
  @mock.patch('cros.factory.utils.process_utils.CheckCall', mock.Mock())
  def testDumpFPFirmware_Succeed(self, mock_fmap_fw_image):
    self._CreateFakeFPFirmware('board_1111-RO_1111-RW.bin')
    mock_fmap_fw_image.return_value.get_section_area.return_value = (0, 1)
    chromeos_firmware.DumpFPFirmware()

  def testDumpFPFirmware_NoFirmwareMatched(self):
    with self.assertRaises(chromeos_firmware.FPReferenceFirmwareError):
      chromeos_firmware.DumpFPFirmware()

  def testDumpFPFirmware_MultipleFirmwareMatched(self):
    self._CreateFakeFPFirmware('board_1111-RO_1111-RW.bin')
    self._CreateFakeFPFirmware('board_2222-RO_2222-RW.bin')
    with self.assertRaises(chromeos_firmware.FPReferenceFirmwareError):
      chromeos_firmware.DumpFPFirmware()


if __name__ == '__main__':
  unittest.main()
