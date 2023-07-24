#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import textwrap
import unittest
from unittest import mock

from cros.factory.external.chromeos_cli import futility
from cros.factory.external.chromeos_cli import shell


class FutilityTest(unittest.TestCase):

  def setUp(self):
    self.futility = futility.Futility()
    self.shell = mock.Mock(spec=shell.Shell)
    self.futility._shell = self.shell  # pylint: disable=protected-access

  def testGetFlashSize(self):
    self._SetFutilityUtilityResult(
        stdout=textwrap.dedent("""
        ignored messages
        16777216
        """))
    flash_size = self.futility.GetFlashSize()
    self.shell.assert_called_with(['flashrom', '--flash-size'])
    self.assertEqual(flash_size, 16777216)

  def testGetFlashSizeError(self):
    self._SetFutilityUtilityResult(stdout='unknown messages')
    self.assertRaises(futility.FutilityError, self.futility.GetFlashSize)

  def testGetWriteProtectInfo(self):
    self._SetFutilityUtilityResult(
        stdout=textwrap.dedent("""
        ignored messages
        Expected WP SR configuration by FW image:(start = 0x00800000, length = 0x00700000)
        """))
    wp_conf = self.futility.GetWriteProtectInfo()
    self.shell.assert_called_with(['futility', 'flash', '--flash-info'])
    self.assertEqual(wp_conf['start'], '0x00800000')
    self.assertEqual(wp_conf['length'], '0x00700000')

  def testGetWriteProtectInfoError(self):
    self._SetFutilityUtilityResult(stdout='unknown messages')
    self.assertRaises(futility.FutilityError, self.futility.GetWriteProtectInfo)

  def testSetGBBFlags(self):
    self.futility.SetGBBFlags(57)
    self.shell.assert_called_with('futility gbb --set --flash --flags=57 2>&1')
    self.futility.SetGBBFlags('0x39')
    self.shell.assert_called_with(
        'futility gbb --set --flash --flags=0x39 2>&1')

  def testGetGBBFlags(self):
    self._SetFutilityUtilityResult(stdout='flags: 0x00000039')
    gbb_flags = self.futility.GetGBBFlags()

    self.assertEqual(gbb_flags, 57)
    self.shell.assert_called_with('futility gbb --get --flags --flash')

    gbb_flags = self.futility.GetGBBFlags('fw_file')
    self.shell.assert_called_with('futility gbb --get --flags fw_file')

  def testGetKeyHashFromFutil(self):
    self._SetFutilityUtilityResult(
        stdout=textwrap.dedent("""
      Public Key file:       /tmp/ec_binasdf1234
        Vboot API:           2.1
        Desc:                ""
        Signature Algorithm: 7 RSA3072EXP3
        Hash Algorithm:      2 SHA256
        Version:             0x00000001
        ID:                  matched
      Signature:             /tmp/ec_binasdf1234
        Vboot API:           2.1
        Desc:                ""
        Signature Algorithm: 7 RSA3072EXP3
        Hash Algorithm:      2 SHA256
        Total size:          0x1b8 (440)
        ID:                  ignored
        Data size:           0x17164 (94564)
      Signature verification succeeded.
        """))

    res = self.futility.GetKeyHashFromFutil('fw_file')

    self.shell.assert_called_once_with(
        ['futility', 'show', '--type', 'rwsig', 'fw_file'])
    self.assertEqual(res, 'matched')

  @mock.patch(
      'cros.factory.external.chromeos_cli.futility.Futility.GetKeyHashFromFutil'
  )
  @mock.patch('tempfile.NamedTemporaryFile')
  def testVerifyECKeyInputKeyHash(self, mock_temp_file, mock_get_hash):
    mock_get_hash.return_value = 'hash'
    mock_temp_file.return_value.__enter__.return_value.name = 'ec.bin'

    self.futility.VerifyECKey(pubkey_hash='hash')
    self.shell.assert_called_with('flashrom -p ec -r ec.bin')
    mock_get_hash.assert_called_with('ec.bin')

  @mock.patch(
      'cros.factory.external.chromeos_cli.futility.Futility.GetKeyHashFromFutil'
  )
  def testVerifyECKeyInputKeyHashNotEqual(self, mock_get_hash):
    mock_get_hash.return_value = 'real_hash'

    self.assertRaises(futility.FutilityError, self.futility.VerifyECKey,
                      pubkey_hash='input_hash')

  @mock.patch('tempfile.NamedTemporaryFile')
  def testVerifyECKeyInputKeyPath(self, mock_temp_file):
    mock_temp_file.return_value.__enter__.return_value.name = 'ec.bin'
    self.futility.VerifyECKey(pubkey_path='path')

    self.shell.assert_called_with(
        'futility show --type rwsig --pubkey path ec.bin')

  @mock.patch('tempfile.NamedTemporaryFile')
  def testVerifyECKeyInputBothCheckKeyPath(self, mock_temp_file):
    mock_temp_file.return_value.__enter__.return_value.name = 'ec.bin'

    self.futility.VerifyECKey(pubkey_hash='hash', pubkey_path='path')

    self.shell.assert_called_with(
        'futility show --type rwsig --pubkey path ec.bin')

  def testVerifyECKeyInputNoneRaise(self):
    self.assertRaises(ValueError, self.futility.VerifyECKey)

  def testWriteHWID(self):
    self.futility.WriteHWID('fw_file', 'hwid')

    self.shell.assert_called_with('futility gbb --set --hwid="hwid" "fw_file"')

  def testReadHWID(self):
    self._SetFutilityUtilityResult(stdout='hardware_id: Test HWID 123456 ')
    res = self.futility.ReadHWID('fw_file')

    self.assertEqual(res, 'Test HWID 123456')
    self.shell.assert_called_with('futility gbb -g --hwid "fw_file"')

  def _SetFutilityUtilityResult(self, stdout='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr='')

if __name__ == '__main__':
  unittest.main()
