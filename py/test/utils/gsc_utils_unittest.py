#!/usr/bin/env python3
# pylint: disable=protected-access
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest
from unittest import mock

from cros.factory.gooftool import gbb
from cros.factory.test.env import paths
from cros.factory.test.rules import phase
from cros.factory.test.utils import gsc_utils
from cros.factory.test.utils.gsc_utils import GSCScriptPath
from cros.factory.utils import file_utils
from cros.factory.utils import fmap
from cros.factory.utils import interval

from cros.factory.external.chromeos_cli.gsctool import FeatureManagementFlags
from cros.factory.external.chromeos_cli import shell


class FakeFirmwareImage(fmap.FirmwareImage):
  # pylint: disable=super-init-not-called
  def __init__(self, areas, image_source):
    self._image = image_source
    self._areas = areas

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
    self.gsctool = mock.create_autospec(gsc_utils.gsctool.GSCTool,
                                        instance=True)
    self.gsc = gsc_utils.GSCUtils(self.mock_gsc_constants_path,
                                  gsc_tool=self.gsctool)

    self.check_path_patcher = mock.patch.object(gsc_utils.file_utils,
                                                'CheckPath', autospec=True)
    self.mock_check_path = self.check_path_patcher.start()

    patcher = mock.patch.object(gsc_utils.cros_config.CrosConfig,
                                'GetBrandCode', return_value='ZZCR',
                                autospec=True)
    self.mock_brand_code = patcher.start()

    patcher = mock.patch.object(
        gsc_utils.flashrom.FirmwareContent,
        'GetFirmwareImage', return_value=FakeFirmwareImage(
            {'RO_GSCVD': (0x0, 0x1b)},
            b'wordsbefore RCZZ wordsafter'), autospec=True)
    self.mock_fw = patcher.start()

    patcher = mock.patch.object(gsc_utils.phase, 'GetPhase', autospec=True)
    self.mock_phase = patcher.start()
    self.addCleanup(mock.patch.stopall)
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

  @mock.patch.object(gsc_utils.GSCUtils, 'IsTi50', autospec=True)
  def testIsGSCFieldLockedTi50CheckInitialFactoryMode(self, mock_is_ti50):
    mock_is_ti50.return_value = True
    self.gsctool.IsGSCBoardIdTypeSet.return_value = True

    self.gsctool.IsTi50InitialFactoryMode.return_value = True
    self.assertFalse(self.gsc.IsGSCFieldLocked())

    self.gsctool.IsTi50InitialFactoryMode.return_value = False
    self.assertTrue(self.gsc.IsGSCFieldLocked())

  @mock.patch.object(gsc_utils.GSCUtils, 'IsTi50', autospec=True)
  def testIsGSCFieldLockedCr50CheckBoardIdType(self, mock_is_ti50):
    mock_is_ti50.return_value = False
    self.gsctool.IsTi50InitialFactoryMode.return_value = False

    self.gsctool.IsGSCBoardIdTypeSet.return_value = False
    self.assertFalse(self.gsc.IsGSCFieldLocked())

    self.gsctool.IsGSCBoardIdTypeSet.return_value = True
    self.assertTrue(self.gsc.IsGSCFieldLocked())

  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
  def testIsGSCFeatureManagementFlagsLockedNotSet(self, mock_gsc_locked):
    self.gsctool.GetFeatureManagementFlags.return_value = (
        FeatureManagementFlags(False, 0))

    mock_gsc_locked.return_value = True
    self.assertTrue(self.gsc.IsGSCFeatureManagementFlagsLocked())

    mock_gsc_locked.return_value = False
    self.assertFalse(self.gsc.IsGSCFeatureManagementFlagsLocked())

  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
  def testIsGSCFeatureManagementFlagsLockedSet(self, mock_gsc_locked):
    self.gsctool.GetFeatureManagementFlags.return_value = (
        FeatureManagementFlags(False, 1))
    mock_gsc_locked.return_value = False

    self.assertTrue(self.gsc.IsGSCFeatureManagementFlagsLocked())

  def testVerifySnBits(self):
    self._SetShellResult(stdout=' out ', stderr=' err ', status=0)

    with self.assertLogs() as cm:
      self.gsc.VerifySnBits()
    self.assertSequenceEqual(cm.output, [
        'INFO:root:status: 0',
        'INFO:root:stdout: out',
        'INFO:root:stderr: err',
    ])

  def testVerifySnBitsError(self):
    self._SetShellResult(stdout=' out ', status=1)
    self.assertRaisesRegex(gsc_utils.GSCUtilsError, 'out',
                           self.gsc.VerifySnBits)

  def testVerifySnBitsRMAed(self):
    self._SetShellResult(stdout='This device has been RMAed. xxx')

    with self.assertLogs() as cm:
      self.gsc.VerifySnBits()
    self.assertIn('WARNING:root:SN Bits cannot be set anymore.', cm.output)

  def testVerifySnBitsNotSet(self):
    self._SetShellResult(stdout='SN Bits have not been set yet. xxx')
    with self.assertLogs() as cm:
      self.gsc.VerifySnBits()

    self.assertSequenceEqual(cm.output, [
        'INFO:root:status: 0',
        'INFO:root:stdout: SN Bits have not been set yet. xxx',
        'INFO:root:stderr: ',
    ])

    self._SetShellResult(
        stdout='SN Bits have not been set yet. BoardID is set. xxx')
    with self.assertLogs() as cm:
      self.gsc.VerifySnBits()
    self.assertIn('WARNING:root:SN Bits cannot be set anymore.', cm.output)

  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
  def testCr50ClearROHash(self, mock_gsc_locked):
    mock_gsc_locked.return_value = False
    self.gsctool.IsCr50ROHashSet.return_value = True

    with self.assertLogs() as cm:
      self.gsc.Cr50ClearROHash()

    self.gsctool.ClearROHash.assert_called_once()
    self.assertSequenceEqual(
        cm.output, ['INFO:root:Successfully clear AP-RO hash on Cr50.'])

  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
  def testCr50ClearROHashLocked(self, mock_gsc_locked):
    mock_gsc_locked.return_value = True

    with self.assertLogs() as cm:
      self.gsc.Cr50ClearROHash()

    self.assertSequenceEqual(
        cm.output,
        ['WARNING:root:GSC fields is locked. Skip clearing RO hash.'])
    self.assertFalse(self.gsctool.ClearROHash.called)

  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
  def testCr50ClearROHashAlreadyClear(self, mock_gsc_locked):
    mock_gsc_locked.return_value = False
    self.gsctool.IsCr50ROHashSet.return_value = False

    with self.assertLogs() as cm:
      self.gsc.Cr50ClearROHash()

    self.assertFalse(self.gsctool.ClearROHash.called)
    self.assertSequenceEqual(
        cm.output, ['INFO:root:AP-RO hash is already cleared, do nothing.'])

  @mock.patch.object(gsc_utils.GSCUtils, 'Cr50SetROHash', autospec=True)
  @mock.patch.object(gsc_utils.futility.Futility, 'SetGBBFlags',
                     spec=gsc_utils.futility.Futility)
  @mock.patch.object(gsc_utils.futility.Futility, 'GetGBBFlags',
                     spec=gsc_utils.futility.Futility)
  def testCr50SetROHashForShipping(self, mock_get_gbb, mock_set_gbb,
                                   mock_set_hash):
    mock_get_gbb.return_value = 0x39

    self.gsc.Cr50SetROHashForShipping()

    mock_set_gbb.assert_has_calls([mock.call(0), mock.call(0x39)])
    mock_set_hash.assert_called_once()

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  @mock.patch.object(gsc_utils.GSCUtils, '_CalculateHashInterval',
                     autospec=True)
  @mock.patch.object(gsc_utils.GSCUtils, 'Cr50ClearROHash', autospec=True)
  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
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

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  @mock.patch.object(gsc_utils.GSCUtils, 'IsGSCFieldLocked', autospec=True)
  def testCr50SetROHashSkip(self, mock_gsc_locked, mock_script):
    mock_gsc_locked.return_value = True

    with self.assertLogs() as cm:
      self.gsc.Cr50SetROHash()

    self.assertFalse(mock_script.called)
    self.assertSequenceEqual(
        cm.output, ['WARNING:root:GSC fields is locked. Skip setting RO hash.'])

  @mock.patch.object(gsc_utils.gbb, 'UnpackGBB', autospec=True)
  def testCalculateHashInterval(self, mock_gbb):
    self.mock_fw.return_value = FakeFirmwareImage(
        {
            'RO_SECTION': (0x100, 0x900000),  # All [0x100, 0x900100)
            'RO_VPD': (0x200, 0x100),  # Exclude [0x200, 0x300)
            'GBB': (0x400, 0x100)  # Include [0x400, 0x500)
        },
        'image_source')
    mock_gbb.return_value = gbb.GBBContent(
        hwid=gbb.GBBField(value='unused', offset=0x1000,
                          size=0x1000),  # Exclude [0x1000, 0x2000)
        hwid_digest=gbb.GBBField(value='unused', offset=0x3000,
                                 size=0x1000),  # Exclude [0x3000, 0x4000)
        rootkey='unused',
        recovery_key='unused')

    res = self.gsc._CalculateHashInterval()
    mock_gbb.assert_called_with('image_source', 0x400)
    self.assertEqual(res, [
        interval.Interval(0x100, 0x200),
        interval.Interval(0x300, 0x1000),
        interval.Interval(0x2000, 0x3000),
        interval.Interval(0x4000, 0x404000),
        interval.Interval(0x404000, 0x804000),
        interval.Interval(0x804000, 0x900100)
    ])
    self.assertTrue(all(r.size <= 0x400000 for r in res))

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  @mock.patch.object(gsc_utils.vpd.VPDTool, 'GetValue',
                     spec=gsc_utils.vpd.VPDTool)
  def testGSCSetSnBits(self, mock_vpd, mock_script):
    mock_vpd.return_value = 'adid'

    self.gsc.GSCSetSnBits()
    mock_vpd.assert_called_with('attested_device_id')
    mock_script.assert_called_with(GSCScriptPath.SN_BITS)

  @mock.patch.object(gsc_utils.vpd.VPDTool, 'GetValue')
  def testGSCSetSnBitsNoVPD(self, mock_vpd):
    mock_vpd.return_value = None

    self.assertRaises(gsc_utils.GSCUtilsError, self.gsc.GSCSetSnBits)

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  def testGSCSetFeatureManagementFlagsWithHwSecUtils(self, mock_script):
    self.gsc.GSCSetFeatureManagementFlagsWithHwSecUtils(True, 1)
    mock_script.assert_called_with(GSCScriptPath.FACTORY_CONFIG, ['true', '1'])

  @mock.patch.object(gsc_utils.GSCUtils,
                     'GSCSetFeatureManagementFlagsWithHwSecUtils',
                     autospec=True)
  @mock.patch.object(gsc_utils.device_data, 'GetDeviceData', autospec=True)
  def testGSCSetFeatureManagementFlagsSameValue(self, mock_device_data,
                                                mock_set_flags):
    mock_device_data.side_effect = [True, 1]
    self.gsctool.GetFeatureManagementFlags.return_value = (
        FeatureManagementFlags(True, 1))

    self.gsc.GSCSetFeatureManagementFlags()

    self.assertFalse(mock_set_flags.called)

  @mock.patch.object(gsc_utils.GSCUtils,
                     'GSCSetFeatureManagementFlagsWithHwSecUtils',
                     spec=gsc_utils.GSCUtils)
  @mock.patch.object(gsc_utils.device_data, 'GetDeviceData', autospec=True)
  def testGSCSetFeatureManagementFlagsSetByScript(self, mock_device_data,
                                                  mock_set_flags):
    mock_device_data.side_effect = [True, 2]
    self.gsctool.GetFeatureManagementFlags.return_value = (
        FeatureManagementFlags(False, 0))

    self.gsc.GSCSetFeatureManagementFlags()

    mock_set_flags.assert_called_with(True, 2)

  @mock.patch.object(gsc_utils.device_data, 'GetDeviceData', autospec=True)
  def testGSCSetFeatureManagementFlagsFallback(self, mock_device_data):
    self.mock_check_path.side_effect = IOError
    mock_device_data.side_effect = [True, 1]
    self.gsctool.GetFeatureManagementFlags.return_value = (
        FeatureManagementFlags(False, 0))

    self.gsc.GSCSetFeatureManagementFlags()

    self.gsctool.SetFeatureManagementFlags.assert_called_with(True, 1)

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  def testGSCSetBoardIdTwoStagesFlags(self, mock_script):
    self.mock_phase.return_value = phase.PVT
    self._SetShellResult(status=0)

    self.gsc.GSCSetBoardId(two_stages=True, is_flags_only=True)

    mock_script.assert_called_with(GSCScriptPath.BOARD_ID,
                                   'two_stages_pvt_flags')

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  def testGSCSetBoardIdTwoStagesPVT(self, mock_script):
    self.mock_phase.return_value = phase.PVT

    self.gsc.GSCSetBoardId(two_stages=True, is_flags_only=False)
    mock_script.assert_called_with(GSCScriptPath.BOARD_ID, 'two_stages_pvt')

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  def testGSCSetBoardIdPVT(self, mock_script):
    for p in [phase.PVT, phase.PVT_DOGFOOD]:
      self.mock_phase.return_value = p
      self.gsc.GSCSetBoardId(two_stages=False, is_flags_only=False)
      mock_script.assert_called_with(GSCScriptPath.BOARD_ID, 'pvt')

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  def testGSCSetBoardIdDev(self, mock_script):
    for p in [phase.DVT, phase.EVT, phase.PROTO]:
      self.mock_phase.return_value = p
      self.gsc.GSCSetBoardId(two_stages=False, is_flags_only=False)
      mock_script.assert_called_with(GSCScriptPath.BOARD_ID, 'dev')

  @mock.patch.object(gsc_utils.GSCUtils, 'ExecuteGSCSetScript',
                     spec=gsc_utils.GSCUtils)
  def testGSCSetBoardIdMismatched(self, mock_script):
    self.mock_phase.return_value = phase.EVT
    self.mock_brand_code.return_value = 'ABCD'

    self.assertRaisesRegex(
        gsc_utils.GSCUtilsError,
        'The brand code in RO_GSCVD ZZCR is different from '
        'the brand code in cros_config ABCD.', self.gsc.GSCSetBoardId,
        two_stages=False, is_flags_only=False)
    mock_script.assert_not_called()

    # Won't verify brand code when only set board ID flags.
    self.gsc.GSCSetBoardId(two_stages=True, is_flags_only=True)
    mock_script.assert_called_once()

  @mock.patch.object(gsc_utils.GSCUtils, 'Ti50SetSWWPRegister',
                     spec=gsc_utils.GSCUtils)
  @mock.patch.object(gsc_utils.GSCUtils, 'Ti50SetAddressingMode', autospec=True)
  def testTi50ProvisionSPIData(self, mock_addressing_mode, mock_wpsr):
    self.gsc.Ti50ProvisionSPIData(False)

    mock_addressing_mode.assert_called_once()
    mock_wpsr.assert_called_with(False)

  @mock.patch.object(gsc_utils.futility.Futility, 'GetFlashSize', autospec=True)
  def testTi50SetAddressingMode(self, mock_get_size):
    mock_get_size.return_value = 123

    self.gsc.Ti50SetAddressingMode()

    self.gsctool.SetAddressingMode.assert_called_with(123)

  def testTi50SetSWWPRegisterWPDisabled(self):
    self.gsc.Ti50SetSWWPRegister(True)

    self.gsctool.SetWpsr.assert_called_with('0 0')

  @mock.patch.object(gsc_utils.futility.Futility, 'GetWriteProtectInfo',
                     autospec=True)
  @mock.patch.object(gsc_utils.GSCUtils, 'GetFlashName', autospec=True)
  def testTi50SetSWWPRegisterWPEnabled(self, mock_flash_name, mock_wp_info):
    mock_flash_name.return_value = 'name'
    mock_wp_info.return_value = {
        'start': 1,
        'length': 2
    }  # To simulate a match object.
    self._SetShellResult(stdout='SR Value/Mask = wpsr')

    with self.assertLogs() as cm:
      self.gsc.Ti50SetSWWPRegister(False)

    self.shell.assert_called_with(
        ['ap_wpsr', '--name=name', '--start=1', '--length=2'])
    self.gsctool.SetWpsr.assert_called_with('wpsr')
    self.assertSequenceEqual(cm.output,
                             ['INFO:root:WPSR: SR Value/Mask = wpsr'])

  @mock.patch.object(gsc_utils.futility.Futility, 'GetWriteProtectInfo',
                     autospec=True)
  @mock.patch.object(gsc_utils.GSCUtils, 'GetFlashName', autospec=True)
  def testTi50SetSWWPRegisterUnknownOutput(self, mock_flash_name, mock_wp_info):
    del mock_flash_name  # not  used
    del mock_wp_info  # not  used
    self._SetShellResult(stdout='unabled to parse')

    self.assertRaisesRegex(gsc_utils.GSCUtilsError,
                           'Fail to parse the wpsr from ap_wpsr tool',
                           self.gsc.Ti50SetSWWPRegister, False)

  @mock.patch.object(gsc_utils.flash_chip.FlashChipFunction, 'ProbeDevices',
                     autospec=True)
  @mock.patch.object(gsc_utils.model_sku_utils, 'GetDesignConfig',
                     autospec=True)
  def testGetFlashName_NoTransform(self, mock_get_config, mock_probe_device):
    mock_probe_device.return_value = {
        'name': 'mock_name'
    }
    mock_get_config.return_value = {}

    with self.assertLogs() as cm:
      flash_name = self.gsc.GetFlashName()
    self.assertEqual(flash_name, 'mock_name')
    mock_probe_device.assert_called_once_with('internal')
    mock_get_config.assert_called_once_with(
        self.gsc._dut,
        default_config_dirs=f'{paths.FACTORY_DIR}/py/test/pytests',
        config_name='model_sku')
    self.assertSequenceEqual(cm.output, ['INFO:root:Flash name: mock_name'])

  @mock.patch.object(gsc_utils.flash_chip.FlashChipFunction, 'ProbeDevices',
                     autospec=True)
  @mock.patch.object(gsc_utils.model_sku_utils, 'GetDesignConfig',
                     autospec=True)
  def testGetFlashName_Transform(self, mock_get_config, mock_probe_device):
    mock_probe_device.return_value = {
        'partname': 'mock_partname'
    }
    mock_get_config.return_value = {
        'spi_flash_transform': {
            'mock_partname': 'transformed_mock_partname'
        }
    }

    with self.assertLogs() as cm:
      flash_name = self.gsc.GetFlashName()
    self.assertEqual(flash_name, 'transformed_mock_partname')
    mock_probe_device.assert_called_once_with('internal')
    mock_get_config.assert_called_once_with(
        self.gsc._dut,
        default_config_dirs=f'{paths.FACTORY_DIR}/py/test/pytests',
        config_name='model_sku')
    self.assertSequenceEqual(cm.output, [
        'INFO:root:Transform flash name from "mock_partname" to '
        '"transformed_mock_partname".',
        'INFO:root:Flash name: transformed_mock_partname'
    ])

  def testExecuteGSCSetScript(self):
    self._SetShellResult(status=0)

    with self.assertLogs() as cm:
      self.gsc.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, 'args')

    self.shell.assert_called_with(
        ['/usr/share/cros/hwsec-utils/cr50_set_board_id', 'args'])
    self.assertSequenceEqual(cm.output, [
        'INFO:root:Successfully set BOARD_ID on GSC with '
        '`/usr/share/cros/hwsec-utils/cr50_set_board_id args`.'
    ])

  def testExecuteGSCSetScriptAlreadySet(self):
    self._SetShellResult(status=2)

    with self.assertLogs() as cm:
      self.gsc.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, 'args')

    self.assertSequenceEqual(
        cm.output, ['ERROR:root:BOARD_ID has already been set on GSC!'])

  def testExecuteGSCSetScriptSetDiff(self):
    self._SetShellResult(status=3)

    self.mock_phase.return_value = phase.DVT
    with self.assertLogs() as cm:
      self.gsc.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, 'args')
    self.assertSequenceEqual(
        cm.output, ['ERROR:root:BOARD_ID has been set DIFFERENTLY on GSC!'])

    self.mock_phase.return_value = phase.PVT
    self.assertRaisesRegex(
        gsc_utils.GSCUtilsError, 'BOARD_ID has been set DIFFERENTLY on GSC!',
        self.gsc.ExecuteGSCSetScript, GSCScriptPath.BOARD_ID, 'args')

  def testExecuteGSCSetScriptOtherError(self):
    self._SetShellResult(status=9)

    self.assertRaisesRegex(
        gsc_utils.GSCUtilsError, 'Failed to set BOARD_ID on GSC',
        self.gsc.ExecuteGSCSetScript, GSCScriptPath.BOARD_ID, 'args')

  def testExecuteGSCSetScriptFileNotFound(self):
    self.check_path_patcher.stop()
    self.assertRaises(IOError, self.gsc.ExecuteGSCSetScript,
                      GSCScriptPath.BOARD_ID, 'args')

    self.check_path_patcher.start(
    )  # To prevent runtime error before python 3.8

  def _SetShellResult(self, stdout='', stderr='', status=0):
    self.shell.return_value = shell.ShellResult(
        success=status == 0, status=status, stdout=stdout, stderr=stderr)
    self.gsc._shell = self.shell


if __name__ == '__main__':
  unittest.main()
