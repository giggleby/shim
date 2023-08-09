#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest
from unittest import mock

from cros.factory.test.rules import phase
from cros.factory.test.utils import gsc_utils
from cros.factory.test.utils.gsc_utils import GSCScriptPath
from cros.factory.utils import file_utils
from cros.factory.utils import interval

from cros.factory.external.chromeos_cli.gsctool import FeatureManagementFlags
from cros.factory.external.chromeos_cli import shell


GSCTOOL = 'cros.factory.external.chromeos_cli.gsctool.GSCTool'
FUTILITY = 'cros.factory.external.chromeos_cli.futility.Futility'
VPD = 'cros.factory.external.chromeos_cli.vpd.VPDTool'
GSCUTIL = 'cros.factory.test.utils.gsc_utils.GSCUtils'
PHASE = 'cros.factory.test.rules.phase.GetPhase'


class GSCUtilsTest(unittest.TestCase):
  _GSC_CONSTANTS = """
    #!/bin/sh
    gsc_name() {
      printf "ti50"
    }

    gsc_image_base_name() {
      printf "/opt/google/ti50/firmware/ti50.bin"
    }

    gsc_metrics_prefix() {
      printf "Platform.Ti50"
    }
  """

  def setUp(self):
    self.mock_gsc_constants_path = file_utils.CreateTemporaryFile()
    self.gsc = gsc_utils.GSCUtils(self.mock_gsc_constants_path)
    self.mock_check_path = mock.patch('cros.factory.utils.file_utils.CheckPath')
    self.mock_check_path.start()
    self.addCleanup(self.mock_check_path.stop)

    self.mock_phase = mock.patch(PHASE)
    self.mock_phase.start()
    self.addCleanup(self.mock_phase.stop)
    self.shell = mock.Mock(spec=shell.Shell)

  def tearDown(self):
    if os.path.exists(self.mock_gsc_constants_path):
      os.remove(self.mock_gsc_constants_path)

  def testLoadConstantsFail(self):
    # Function not exists.
    file_utils.WriteFile(self.mock_gsc_constants_path, '#!/bin/sh')
    gsc = gsc_utils.GSCUtils(self.mock_gsc_constants_path)
    with self.assertRaisesRegex(gsc_utils.GSCUtilsError,
                                'Fail to load constant'):
      # gsc.name is a lazy property which triggers the execution of a command
      # on the first call.
      # pylint: disable=pointless-statement
      gsc.name

  def testLoadConstantsSuccess(self):
    file_utils.WriteFile(self.mock_gsc_constants_path, self._GSC_CONSTANTS)
    self.assertEqual(self.gsc.name, 'ti50')
    self.assertEqual(self.gsc.image_base_name,
                     '/opt/google/ti50/firmware/ti50.bin')
    self.assertEqual(self.gsc.metrics_prefix, 'Platform.Ti50')
    self.assertTrue(self.gsc.IsTi50())
    self.assertListEqual(self.gsc.GetGSCToolCmd(), ['/usr/sbin/gsctool', '-D'])

  @mock.patch(f'{GSCTOOL}.IsGSCBoardIdTypeSet')
  @mock.patch(f'{GSCTOOL}.IsTi50InitialFactoryMode')
  @mock.patch(f'{GSCUTIL}.IsTi50')
  def testIsGSCFieldLockedTi50CheckInitialFactoryMode(
      self, mock_is_ti50, mock_init_factory_mode, mock_is_board_id_set):
    mock_is_ti50.return_value = True
    mock_is_board_id_set.return_value = True

    mock_init_factory_mode.return_value = True
    self.assertFalse(self.gsc.IsGSCFieldLocked())

    mock_init_factory_mode.return_value = False
    self.assertTrue(self.gsc.IsGSCFieldLocked())

  @mock.patch(f'{GSCTOOL}.IsGSCBoardIdTypeSet')
  @mock.patch(f'{GSCTOOL}.IsTi50InitialFactoryMode')
  @mock.patch(f'{GSCUTIL}.IsTi50')
  def testIsGSCFieldLockedCr50CheckBoardIdType(
      self, mock_is_ti50, mock_init_factory_mode, mock_is_board_id_set):
    mock_is_ti50.return_value = False
    mock_init_factory_mode.return_value = False

    mock_is_board_id_set.return_value = False
    self.assertFalse(self.gsc.IsGSCFieldLocked())

    mock_is_board_id_set.return_value = True
    self.assertTrue(self.gsc.IsGSCFieldLocked())

  @mock.patch(f'{GSCTOOL}.GetFeatureManagementFlags')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testIsGSCFeatureManagementFlagsLockedNotSet(self, mock_gsc_locked,
                                                  mock_get_flags):
    mock_get_flags.return_value = FeatureManagementFlags(False, 0)

    mock_gsc_locked.return_value = True
    self.assertTrue(self.gsc.IsGSCFeatureManagementFlagsLocked())

    mock_gsc_locked.return_value = False
    self.assertFalse(self.gsc.IsGSCFeatureManagementFlagsLocked())

  @mock.patch(f'{GSCTOOL}.GetFeatureManagementFlags')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testIsGSCFeatureManagementFlagsLockedSet(self, mock_gsc_locked,
                                               mock_get_flags):
    mock_get_flags.return_value = FeatureManagementFlags(False, 1)
    mock_gsc_locked.return_value = False

    self.assertTrue(self.gsc.IsGSCFeatureManagementFlagsLocked())

  @mock.patch('logging.info')
  def testVerifySnBits(self, mock_info):
    self._SetShellResult(stdout=' out ', stderr=' err ', status=0)

    self.gsc.VerifySnBits()
    mock_info.assert_has_calls([
        mock.call('status: %d', 0),
        mock.call('stdout: %s', 'out'),
        mock.call('stderr: %s', 'err')
    ])

  def testVerifySnBitsError(self):
    self._SetShellResult(stdout=' out ', status=1)
    self.assertRaisesRegex(gsc_utils.GSCUtilsError, 'out',
                           self.gsc.VerifySnBits)

  @mock.patch('logging.warning')
  def testVerifySnBitsRMAed(self, mock_warn):
    self._SetShellResult(stdout='This device has been RMAed. xxx')

    self.gsc.VerifySnBits()
    mock_warn.assert_called_with('SN Bits cannot be set anymore.')

  @mock.patch('logging.warning')
  def testVerifySnBitsNotSet(self, mock_warn):
    self._SetShellResult(stdout='SN Bits have not been set yet. xxx')
    self.gsc.VerifySnBits()
    self.assertFalse(mock_warn.called)

    self._SetShellResult(
        stdout='SN Bits have not been set yet. BoardID is set. xxx')
    self.gsc.VerifySnBits()
    mock_warn.assert_called_with('SN Bits cannot be set anymore.')

  @mock.patch('logging.info')
  @mock.patch(f'{GSCTOOL}.ClearROHash')
  @mock.patch(f'{GSCTOOL}.IsCr50ROHashSet')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testCr50ClearROHash(self, mock_gsc_locked, mock_is_hash_set,
                          mock_clear_hash, mock_info):
    mock_gsc_locked.return_value = False
    mock_is_hash_set.return_value = True

    self.gsc.Cr50ClearROHash()

    mock_clear_hash.assert_called_once()
    mock_info.assert_called_with('Successfully clear AP-RO hash on Cr50.')

  @mock.patch('logging.warning')
  @mock.patch(f'{GSCTOOL}.ClearROHash')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testCr50ClearROHashLocked(self, mock_gsc_locked, mock_clear_hash,
                                mock_warn):
    mock_gsc_locked.return_value = True

    self.gsc.Cr50ClearROHash()

    mock_warn.assert_called_with('GSC fields is locked. Skip clearing RO hash.')
    self.assertFalse(mock_clear_hash.called)

  @mock.patch('logging.info')
  @mock.patch(f'{GSCTOOL}.ClearROHash')
  @mock.patch(f'{GSCTOOL}.IsCr50ROHashSet')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testCr50ClearROHashAlreadyClear(self, mock_gsc_locked, mock_is_hash_set,
                                      mock_clear_hash, mock_info):
    mock_gsc_locked.return_value = False
    mock_is_hash_set.return_value = False

    self.gsc.Cr50ClearROHash()

    self.assertFalse(mock_clear_hash.called)
    mock_info.assert_called_with('AP-RO hash is already cleared, do nothing.')

  @mock.patch(f'{GSCUTIL}.Cr50SetROHash')
  @mock.patch(f'{FUTILITY}.SetGBBFlags')
  @mock.patch(f'{FUTILITY}.GetGBBFlags')
  def testCr50SetROHashForShipping(self, mock_get_gbb, mock_set_gbb,
                                   mock_set_hash):
    mock_get_gbb.return_value = 0x39

    self.gsc.Cr50SetROHashForShipping()

    mock_set_gbb.assert_has_calls([mock.call(0), mock.call(0x39)])
    mock_set_hash.assert_called_once()

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(f'{GSCUTIL}._CalculateHashInterval')
  @mock.patch(f'{GSCUTIL}.Cr50ClearROHash')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testCr50SetROHash(self, mock_gsc_locked, mock_clear_hash,
                        mock_hash_interval, mock_script):
    mock_gsc_locked.return_value = False
    mock_hash_interval.return_value = [
        interval.Interval(1, 3),
        interval.Interval(6, 9)
    ]

    self.gsc.Cr50SetROHash()

    mock_script.assert_called_with(GSCScriptPath.AP_RO_HASH, '1:2 6:3')
    mock_clear_hash.assert_called_once()

  @mock.patch('logging.warning')
  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(f'{GSCUTIL}.IsGSCFieldLocked')
  def testCr50SetROHashSkip(self, mock_gsc_locked, mock_script, mock_warn):
    mock_gsc_locked.return_value = True

    self.gsc.Cr50SetROHash()

    self.assertFalse(mock_script.called)
    mock_warn.assert_called_with('GSC fields is locked. Skip setting RO hash.')

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(f'{VPD}.GetValue')
  def testGSCSetSnBits(self, mock_vpd, mock_script):
    mock_vpd.return_value = 'adid'

    self.gsc.GSCSetSnBits()
    mock_vpd.assert_called_with('attested_device_id')
    mock_script.assert_called_with(GSCScriptPath.SN_BITS)

  @mock.patch(f'{VPD}.GetValue')
  def testGSCSetSnBitsNoVPD(self, mock_vpd):
    mock_vpd.return_value = None

    self.assertRaises(gsc_utils.GSCUtilsError, self.gsc.GSCSetSnBits)

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  def testGSCSetFeatureManagementFlagsWithHwSecUtils(self, mock_script):
    self.gsc.GSCSetFeatureManagementFlagsWithHwSecUtils(True, 1)
    mock_script.assert_called_with(GSCScriptPath.FACTORY_CONFIG, ['true', '1'])

  @mock.patch('logging.warning')
  @mock.patch(f'{GSCUTIL}.IsGSCFeatureManagementFlagsLocked')
  def testGSCSetFeatureManagementFlagsLocked(self, mock_locked, mock_warn):
    mock_locked.return_value = True

    self.gsc.GSCSetFeatureManagementFlags()

    mock_warn.assert_called_with(
        'GSC fields is locked. Skip setting feature management flags.')

  @mock.patch(f'{GSCUTIL}.GSCSetFeatureManagementFlagsWithHwSecUtils')
  @mock.patch(f'{GSCTOOL}.GetFeatureManagementFlags')
  @mock.patch('cros.factory.test.device_data.GetDeviceData')
  @mock.patch(f'{GSCUTIL}.IsGSCFeatureManagementFlagsLocked')
  def testGSCSetFeatureManagementFlagsSameValue(
      self, mock_locked, mock_device_data, mock_get_flags, mock_set_flags):
    mock_locked.return_value = False
    mock_device_data.side_effect = [True, 1]
    mock_get_flags.return_value = FeatureManagementFlags(True, 1)

    self.gsc.GSCSetFeatureManagementFlags()

    self.assertFalse(mock_set_flags.called)

  @mock.patch(f'{GSCUTIL}.GSCSetFeatureManagementFlagsWithHwSecUtils')
  @mock.patch(f'{GSCTOOL}.GetFeatureManagementFlags')
  @mock.patch('cros.factory.test.device_data.GetDeviceData')
  @mock.patch(f'{GSCUTIL}.IsGSCFeatureManagementFlagsLocked')
  def testGSCSetFeatureManagementFlagsSetByScript(
      self, mock_locked, mock_device_data, mock_get_flags, mock_set_flags):
    mock_locked.return_value = False
    mock_device_data.side_effect = [True, 2]
    mock_get_flags.return_value = FeatureManagementFlags(False, 0)

    self.gsc.GSCSetFeatureManagementFlags()

    mock_set_flags.assert_called_with(True, 2)

  @mock.patch('cros.factory.utils.file_utils.CheckPath')
  @mock.patch(f'{GSCTOOL}.SetFeatureManagementFlags')
  @mock.patch(f'{GSCTOOL}.GetFeatureManagementFlags')
  @mock.patch('cros.factory.test.device_data.GetDeviceData')
  @mock.patch(f'{GSCUTIL}.IsGSCFeatureManagementFlagsLocked')
  def testGSCSetFeatureManagementFlagsFallback(self, mock_locked,
                                               mock_device_data, mock_get_flags,
                                               mock_set_flags, mock_path):
    mock_path.side_effect = FileNotFoundError
    mock_locked.return_value = False
    mock_device_data.side_effect = [True, 1]
    mock_get_flags.return_value = FeatureManagementFlags(False, 0)

    self.gsc.GSCSetFeatureManagementFlags()

    mock_set_flags.assert_called_with(True, 1)

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(PHASE)
  def testGSCSetBoardIdTwoStagesFlags(self, mock_phase, mock_script):
    mock_phase.return_value = phase.PVT
    self._SetShellResult(status=0)

    self.gsc.GSCSetBoardId(two_stages=True, is_flags_only=True)

    mock_script.assert_called_with(GSCScriptPath.BOARD_ID,
                                   'whitelabel_pvt_flags')

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(PHASE)
  def testGSCSetBoardIdTwoStagesPVT(self, mock_phase, mock_script):
    mock_phase.return_value = phase.PVT

    self.gsc.GSCSetBoardId(two_stages=True, is_flags_only=False)
    mock_script.assert_called_with(GSCScriptPath.BOARD_ID, 'whitelabel_pvt')

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(PHASE)
  def testGSCSetBoardIdPVT(self, mock_phase, mock_script):
    for p in [phase.PVT, phase.PVT_DOGFOOD]:
      mock_phase.return_value = p
      self.gsc.GSCSetBoardId(two_stages=False, is_flags_only=False)
      mock_script.assert_called_with(GSCScriptPath.BOARD_ID, 'pvt')

  @mock.patch(f'{GSCUTIL}.ExecuteGSCSetScript')
  @mock.patch(PHASE)
  def testGSCSetBoardIdDev(self, mock_phase, mock_script):

    for p in [phase.DVT, phase.EVT, phase.PROTO]:
      mock_phase.return_value = p
      self.gsc.GSCSetBoardId(two_stages=False, is_flags_only=False)
      mock_script.assert_called_with(GSCScriptPath.BOARD_ID, 'dev')

  @mock.patch(f'{GSCUTIL}.Ti50SetSWWPRegister')
  @mock.patch(f'{GSCUTIL}.Ti50SetAddressingMode')
  def testTi50ProvisionSPIData(self, mock_addressing_mode, mock_wpsr):
    self.gsc.Ti50ProvisionSPIData(False)

    mock_addressing_mode.assert_called_once()
    mock_wpsr.assert_called_with(False)

  @mock.patch(f'{GSCTOOL}.SetAddressingMode')
  @mock.patch(f'{FUTILITY}.GetFlashSize')
  def testTi50SetAddressingMode(self, mock_get_size, mock_set_addressing_mode):
    mock_get_size.return_value = 123

    self.gsc.Ti50SetAddressingMode()

    mock_set_addressing_mode.assert_called_with(123)

  @mock.patch(f'{GSCTOOL}.SetWpsr')
  def testTi50SetSWWPRegisterWPDisnabled(self, mock_set_wpsr):
    self.gsc.Ti50SetSWWPRegister(True)

    mock_set_wpsr.assert_called_with('0 0')

  @mock.patch('logging.info')
  @mock.patch(f'{GSCTOOL}.SetWpsr')
  @mock.patch(f'{FUTILITY}.GetWriteProtectInfo')
  @mock.patch(f'{GSCUTIL}.GetFlashName')
  def testTi50SetSWWPRegisterWPEnabled(self, mock_flash_name, mock_wp_info,
                                       mock_set_wpsr, mock_info):
    mock_flash_name.return_value = 'name'
    mock_wp_info.return_value = {
        'start': 1,
        'length': 2
    }  # To simulate a match object.
    self._SetShellResult(stdout='SR Value/Mask = wpsr')

    self.gsc.Ti50SetSWWPRegister(False)

    self.shell.assert_called_with(
        ['ap_wpsr', '--name=name', '--start=1', '--length=2'])
    mock_set_wpsr.assert_called_with('wpsr')
    mock_info.assert_called_with('WPSR: %s', 'SR Value/Mask = wpsr')

  @mock.patch(f'{FUTILITY}.GetWriteProtectInfo')
  @mock.patch(f'{GSCUTIL}.GetFlashName')
  def testTi50SetSWWPRegisterUnknownOutput(self, mock_flash_name, mock_wp_info):
    del mock_flash_name  # not  used
    del mock_wp_info  # not  used
    self._SetShellResult(stdout='unabled to parse')

    self.assertRaisesRegex(gsc_utils.GSCUtilsError,
                           'Fail to parse the wpsr from ap_wpsr tool',
                           self.gsc.Ti50SetSWWPRegister, False)

  @mock.patch('logging.info')
  def testExecuteGSCSetScript(self, mock_info):
    self._SetShellResult(status=0)

    self.gsc.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, 'args')

    self.shell.assert_called_with(
        ['/usr/share/cros/cr50-set-board-id.sh', 'args'])
    mock_info.assert_called_with('Successfully set %s on GSC with `%s`.',
                                 'BOARD_ID',
                                 '/usr/share/cros/cr50-set-board-id.sh args')

  @mock.patch('logging.error')
  def testExecuteGSCSetScriptAlreadySet(self, mock_error):
    self._SetShellResult(status=2)

    self.gsc.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, 'args')

    mock_error.assert_called_with('%s has already been set on GSC!', 'BOARD_ID')

  @mock.patch('logging.error')
  @mock.patch(PHASE)
  def testExecuteGSCSetScriptSetDiff(self, mock_phase, mock_error):
    self._SetShellResult(status=3)

    mock_phase.return_value = phase.DVT
    self.gsc.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, 'args')
    mock_error.assert_called_with('BOARD_ID has been set DIFFERENTLY on GSC!')

    mock_phase.return_value = phase.PVT
    self.assertRaisesRegex(
        gsc_utils.GSCUtilsError, 'BOARD_ID has been set DIFFERENTLY on GSC!',
        self.gsc.ExecuteGSCSetScript, GSCScriptPath.BOARD_ID, 'args')

  def testExecuteGSCSetScriptOtherError(self):
    self._SetShellResult(status=9)

    self.assertRaisesRegex(
        gsc_utils.GSCUtilsError, 'Failed to set BOARD_ID on GSC',
        self.gsc.ExecuteGSCSetScript, GSCScriptPath.BOARD_ID, 'args')

  def testGSCScriptPath(self):

    self.assertEqual(
        GSCScriptPath(GSCScriptPath.BOARD_ID).value,
        '/usr/share/cros/cr50-set-board-id.sh')
    self.assertEqual(
        GSCScriptPath(GSCScriptPath.SN_BITS).value,
        '/usr/share/cros/cr50-set-sn-bits.sh')
    self.assertEqual(
        GSCScriptPath(GSCScriptPath.AP_RO_HASH).value, 'ap_ro_hash.py')
    self.assertEqual(
        GSCScriptPath(GSCScriptPath.FACTORY_CONFIG).value,
        '/usr/share/cros/hwsec-utils/cr50_set_factory_config')

  def _SetShellResult(self, stdout='', stderr='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr=stderr)
    self.gsc._shell = self.shell  # pylint: disable=protected-access


if __name__ == '__main__':
  unittest.main()
