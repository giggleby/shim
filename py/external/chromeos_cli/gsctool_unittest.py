#!/usr/bin/env python3
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.external.chromeos_cli import gsctool
from cros.factory.external.chromeos_cli import shell


class GSCToolTest(unittest.TestCase):

  def setUp(self):
    self.gsctool = gsctool.GSCTool()
    self.shell = mock.Mock(spec=shell.Shell)
    self.gsctool._shell = self.shell  # pylint: disable=protected-access

  def testGetCr50FirmwareVersion(self):
    self._SetGSCToolUtilityResult(
        stdout=('start\n'
                'target running protocol version -1\n'
                'offsets: .....\n'
                'RO_FW_VER=1.2.34\n'
                'RW_FW_VER=5.6.78\n'))
    fw_ver = self.gsctool.GetCr50FirmwareVersion()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-M', '-a', '-f'])
    self.assertEqual(fw_ver.ro_version, '1.2.34')
    self.assertEqual(fw_ver.rw_version, '5.6.78')

    self._SetGSCToolUtilityResult(stdout=('invalid output\n'))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetCr50FirmwareVersion)

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetCr50FirmwareVersion)

  def testUpdateCr50Firmware(self):
    self._SetGSCToolUtilityResult()
    self.assertEqual(
        self.gsctool.UpdateCr50Firmware('img'), gsctool.UpdateResult.NOOP)
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-u', 'img'])

    self._SetGSCToolUtilityResult(status=1)
    self.assertEqual(
        self.gsctool.UpdateCr50Firmware('img'),
        gsctool.UpdateResult.ALL_UPDATED)

    self._SetGSCToolUtilityResult(status=2)
    self.assertEqual(
        self.gsctool.UpdateCr50Firmware('img'), gsctool.UpdateResult.RW_UPDATED)

    self._SetGSCToolUtilityResult(status=3)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.UpdateCr50Firmware,
                      'img')

  def testGetImageInfo(self):
    self._SetGSCToolUtilityResult(
        stdout=('read ... bytes from ...\n'
                'IMAGE_RO_FW_VER=1.2.34\n'
                'IMAGE_RW_FW_VER=5.6.78\n'
                'IMAGE_BID_STRING=00000000\n'
                'IMAGE_BID_MASK=00000000\n'
                'IMAGE_BID_FLAGS=00000abc\n'))
    image_info = self.gsctool.GetImageInfo('img')
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-M', '-b', 'img'])
    self.assertEqual(image_info.ro_fw_version, '1.2.34')
    self.assertEqual(image_info.rw_fw_version, '5.6.78')
    self.assertEqual(image_info.board_id_flags, 0xabc)

    self._SetGSCToolUtilityResult(
        stdout=('read ... bytes from ...\n'
                'IMAGE_BID_FLAGS=00000abc\n'))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetImageInfo, 'img')

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetImageInfo, 'img')

  def testSetFactoryMode(self):
    self._SetGSCToolUtilityResult()
    self.gsctool.SetFactoryMode(True)
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-F', 'enable'])

    self.gsctool.SetFactoryMode(False)
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-F', 'disable'])

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.SetFactoryMode, True)

  def testIsFactoryMode(self):
    self._SetGSCToolUtilityResult(stdout=('...\nCapabilities are default.\n'))
    self.assertFalse(self.gsctool.IsFactoryMode())
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-I'])

    self._SetGSCToolUtilityResult(stdout=('...\nCapabilities are modified.\n'))
    self.assertTrue(self.gsctool.IsFactoryMode())

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.IsFactoryMode)

  def testGetBoardID(self):
    fields = {
        'BID_TYPE': '41424344',
        'BID_TYPE_INV': 'bebdbcbb',
        'BID_FLAGS': '0000ff00',
        'BID_RLZ': 'ABCD'
    }
    self._SetGSCToolUtilityResult(
        stdout=(''.join(f'{k}={v}\n' for k, v in fields.items())))
    board_id = self.gsctool.GetBoardID()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-M', '-i'])
    self.assertEqual(board_id.type, 0x41424344)
    self.assertEqual(board_id.flags, 0x0000ff00)

    # If Cr50 is never provisioned yet, both BID_TYPE and BID_TYPE_INV are
    # 0xffffffff.
    fields2 = {
        'BID_TYPE': 'ffffffff',
        'BID_TYPE_INV': 'ffffffff',
        'BID_FLAGS': '0000ff00',
        'BID_RLZ': '????'
    }
    self._SetGSCToolUtilityResult(
        stdout=(''.join(f'{k}={v}\n' for k, v in fields2.items())))
    board_id = self.gsctool.GetBoardID()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-M', '-i'])
    self.assertEqual(board_id.type, 0xffffffff)
    self.assertEqual(board_id.flags, 0x0000ff00)

    # BID_TYPE_INV should be complement to BID_TYPE
    bad_fields = dict(fields, BID_TYPE_INV='aabbccdd')
    self._SetGSCToolUtilityResult(
        stdout=(''.join(f'{k}={v}\n' for k, v in bad_fields.items())))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetBoardID)

    # BID_TYPE should be the ascii codes of BID_RLZ
    bad_fields = dict(fields, BID_RLZ='XXYY')
    self._SetGSCToolUtilityResult(
        stdout=(''.join(f'{k}={v}\n' for k, v in bad_fields.items())))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetBoardID)

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetBoardID)

  def _SetGSCToolUtilityResult(self, stdout='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr='')

  def _CheckCalledCommand(self, cmd):
    self.assertEqual(self.shell.call_args[0][0], cmd)

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCUtils')
  def testTi50InitialFactoryMode_NotInInitialFactoryMode(self, mock_gsc_utils):
    mock_gsc_utils_object = mock.MagicMock()
    mock_gsc_utils.return_value = mock_gsc_utils_object
    mock_gsc_utils_object.IsTi50.return_value = True
    self._SetGSCToolUtilityResult(
        stdout=('STATE=Opened\n'
                'FLASH_AP=Y\n'
                'INITIAL_FACTORY_MODE=N\n'))
    self.assertFalse(self.gsctool.IsTi50InitialFactoryMode())
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-I', '-M'])

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCUtils')
  def testTi50InitialFactoryMode_IsInInitialFactoryMode(self, mock_gsc_utils):
    mock_gsc_utils_object = mock.MagicMock()
    mock_gsc_utils.return_value = mock_gsc_utils_object
    mock_gsc_utils_object.IsTi50.return_value = True
    self._SetGSCToolUtilityResult(
        stdout=('STATE=Opened\n'
                'FLASH_AP=Y\n'
                'INITIAL_FACTORY_MODE=Y\n'))
    self.assertTrue(self.gsctool.IsTi50InitialFactoryMode())
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-I', '-M'])

  def testIsWpsrProvisioned(self):
    self._SetGSCToolUtilityResult(stdout=('expected values: not provisioned'))
    self.assertFalse(self.gsctool.IsWpsrProvisioned())
    self._SetGSCToolUtilityResult(
        stdout=('expected values: 1: 94 & fc, 2: 00 & 41'))
    self.assertTrue(self.gsctool.IsWpsrProvisioned())
    self._SetGSCToolUtilityResult(stdout=('expected values: corrupted'))
    self.assertTrue(self.gsctool.IsWpsrProvisioned())
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-E'])

if __name__ == '__main__':
  unittest.main()
