#!/usr/bin/env python3
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import textwrap
import unittest
from unittest import mock

from cros.factory.external.chromeos_cli import gsctool
from cros.factory.external.chromeos_cli import shell


class GSCToolTest(unittest.TestCase):

  def setUp(self):
    self.gsctool = gsctool.GSCTool()
    self.shell = mock.Mock(spec=shell.Shell)
    self.gsctool._shell = self.shell  # pylint: disable=protected-access

  def testGetGSCFirmwareVersion(self):
    self._SetGSCToolUtilityResult(
        stdout=('start\n'
                'target running protocol version -1\n'
                'offsets: .....\n'
                'RO_FW_VER=1.2.34\n'
                'RW_FW_VER=5.6.78\n'))
    fw_ver = self.gsctool.GetGSCFirmwareVersion()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-M', '-a', '-f'])
    self.assertEqual(fw_ver.ro_version, '1.2.34')
    self.assertEqual(fw_ver.rw_version, '5.6.78')

    self._SetGSCToolUtilityResult(stdout=('invalid output\n'))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetGSCFirmwareVersion)

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetGSCFirmwareVersion)

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
        stdout=(''.join('%s=%s\n' % (k, v) for k, v in fields.items())))
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
        stdout=(''.join('%s=%s\n' % (k, v) for k, v in fields2.items())))
    board_id = self.gsctool.GetBoardID()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-M', '-i'])
    self.assertEqual(board_id.type, 0xffffffff)
    self.assertEqual(board_id.flags, 0x0000ff00)

    # BID_TYPE_INV should be complement to BID_TYPE
    bad_fields = dict(fields, BID_TYPE_INV='aabbccdd')
    self._SetGSCToolUtilityResult(
        stdout=(''.join('%s=%s\n' % (k, v) for k, v in bad_fields.items())))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetBoardID)

    # BID_TYPE should be the ascii codes of BID_RLZ
    bad_fields = dict(fields, BID_RLZ='XXYY')
    self._SetGSCToolUtilityResult(
        stdout=(''.join('%s=%s\n' % (k, v) for k, v in bad_fields.items())))
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetBoardID)

    self._SetGSCToolUtilityResult(status=1)
    self.assertRaises(gsctool.GSCToolError, self.gsctool.GetBoardID)

  def testCCDOpen(self):
    self.gsctool.CCDOpen()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-o'])

  def testGetCr50APROHash(self):
    self.gsctool.GetCr50APROHash()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-A'])

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCTool.'
              'GetCr50APROHash')
  def testIsCr50ROHashSet(self, mock_get_cr50_ap_ro_hash):
    mock_get_cr50_ap_ro_hash.return_value = 'digest: af0241'
    self.assertTrue(self.gsctool.IsCr50ROHashSet())
    mock_get_cr50_ap_ro_hash.return_value = 'get hash rc: 12 board id blocked'
    self.assertFalse(self.gsctool.IsCr50ROHashSet())

  def testCr50VerifyAPRO(self):
    self.gsctool.Cr50VerifyAPRO()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-B', 'start'])

  def testTi50VerifyAPRO(self):
    self.gsctool.Ti50VerifyAPRO()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '--reboot'])

  def testParseGSCAPROResult(self):
    not_run = self.gsctool.ParseGSCAPROResult('apro result (0) : not run')
    self.assertEqual(not_run, gsctool.APROResult.AP_RO_NOT_RUN)
    success = self.gsctool.ParseGSCAPROResult('apro result (20) : success')
    self.assertEqual(success, gsctool.APROResult.AP_RO_V2_SUCCESS)

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCTool.'
              'ParseGSCAPROResult')
  def testGSCGetAPROResult(self, _unused_mock_parse_gsc_ap_ro_result):
    self.gsctool.GSCGetAPROResult()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-B'])

  def _SetGSCToolUtilityResult(self, stdout='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr='')

  def _CheckCalledCommand(self, cmd):
    self.assertEqual(self.shell.call_args[0][0], cmd)

  def testEncodeFeatureManagementBits_Not_Chassis_Branded_Hw_Incompliant(self):
    result = self.gsctool.EncodeFeatureManagementBits(False, 0)
    self.assertEqual(result, '0000000000000000')

  def testEncodeFeatureManagementBits_Not_Chassis_Branded_Hw_Compliant(self):
    result = self.gsctool.EncodeFeatureManagementBits(False, 1)
    self.assertEqual(result, '0000000000000001')

  def testEncodeFeatureManagementBits_Chassis_Branded_Hw_Compliant(self):
    result = self.gsctool.EncodeFeatureManagementBits(True, 1)
    self.assertEqual(result, '0000000000000011')

  def testParseFeatureConfigs_Not_Chassis_Branded_Hw_Incompliant(self):
    feature_config = textwrap.dedent("""raw_value: 0000000000000000
                 chassis_x_branded: false
                 hw_x_compliance_version: 00
              """)
    result = self.gsctool.ParseFeatureManagementConfigs(feature_config)
    self.assertEqual(result, gsctool.FeatureManagementFlags(False, 0))

  def testParseFeatureConfigs_Not_Chassis_Branded_Hw_Compliant(self):
    feature_config = textwrap.dedent("""raw_value: 0000000000000001
                 chassis_x_branded: false
                 hw_x_compliance_version: 01
              """)
    result = self.gsctool.ParseFeatureManagementConfigs(feature_config)
    self.assertEqual(result, gsctool.FeatureManagementFlags(False, 1))

  def testParseFeatureConfigs_Chassis_Branded_Hw_Compliant(self):
    feature_config = textwrap.dedent("""raw_value: 0000000000000011
                 chassis_x_branded: true
                 hw_x_compliance_version: 01
              """)
    result = self.gsctool.ParseFeatureManagementConfigs(feature_config)
    self.assertEqual(result, gsctool.FeatureManagementFlags(True, 1))

  def testInvalidFeatureManagementFlags_Invalid_Chassis_Branded_Type(self):
    with self.assertRaises(TypeError):
      self.gsctool.SetFeatureManagementFlags(0, 0)

  def testInvalidFeatureManagementFlags_Invalid_Hw_Compliance_Type(self):
    with self.assertRaises(TypeError):
      self.gsctool.SetFeatureManagementFlags(False, False)

  def testInvalidFeatureManagementFlags_Invalid_Hw_Compliance_Value(self):
    with self.assertRaises(ValueError):
      self.gsctool.SetFeatureManagementFlags(True, 16)

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCTool.'
              'EncodeFeatureManagementBits')
  def testSetFeatureManagementFlags(self, mock_encoded_bits):
    mocked_feature_bits = 'bits'
    mock_encoded_bits.return_value = mocked_feature_bits
    self.gsctool.SetFeatureManagementFlags(True, 1)
    self._CheckCalledCommand(
        ['/usr/sbin/gsctool', '-a', '--factory_config', mocked_feature_bits])

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCTool.'
              'ParseFeatureManagementConfigs')
  def testGetFeatureManagementFlags(self, mock_decode_func):
    expected_result = gsctool.FeatureManagementFlags(False, 0)
    mock_decode_func.return_value = expected_result
    feature_flags = self.gsctool.GetFeatureManagementFlags()

    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '--factory_config'])
    mock_decode_func.assert_called_with(mock.ANY)
    self.assertEqual(feature_flags, expected_result)

  def testSetAddressingMode3byte(self):
    self.gsctool.SetAddressingMode(0x1000000)
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-C', '3byte'])

  def testSetAddressingMode4byte(self):
    self.gsctool.SetAddressingMode(0x1000001)
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-C', '4byte'])

  def testGetAddressingMode(self):
    self.gsctool.GetAddressingMode()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-C'])

  def testParseWpsr(self):
    wpsr = self.gsctool.ParseWpsr('expected values: 1: 94 & fc, 2: 00 & 41')
    self.assertEqual(wpsr[0].value, 0x94)
    self.assertEqual(wpsr[0].mask, 0xfc)
    self.assertEqual(wpsr[1].value, 0x00)
    self.assertEqual(wpsr[1].mask, 0x41)

  @mock.patch('cros.factory.external.chromeos_cli.gsctool.GSCTool.ParseWpsr')
  def testGetWpsr(self, _unused_mock_parse_wpsr):
    self.gsctool.GetWpsr()
    self._CheckCalledCommand(['/usr/sbin/gsctool', '-a', '-E'])

if __name__ == '__main__':
  unittest.main()
