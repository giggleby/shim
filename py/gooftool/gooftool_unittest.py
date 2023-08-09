#!/usr/bin/env python3
# pylint: disable=protected-access
#
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for gooftool module."""

from collections import namedtuple
import logging
import os
from tempfile import NamedTemporaryFile
import time
import unittest
from unittest import mock

from cros.factory.device import info
from cros.factory.gooftool.bmpblk import unpack_bmpblock
from cros.factory.gooftool.common import Shell
from cros.factory.gooftool import core
from cros.factory.gooftool.core import CrosConfigIdentity
from cros.factory.gooftool.core import IdentitySourceEnum
from cros.factory.gooftool.management_engine import ManagementEngineError
from cros.factory.gooftool.management_engine import SKU
from cros.factory.gooftool import vpd_utils
from cros.factory.test.utils import model_sku_utils
from cros.factory.unittest_utils import label_utils
from cros.factory.utils import pygpt
from cros.factory.utils import sys_utils
from cros.factory.utils.type_utils import Error
from cros.factory.utils.type_utils import Obj

from cros.factory.external.chromeos_cli import flashrom
from cros.factory.external.chromeos_cli import futility
from cros.factory.external.chromeos_cli.gsctool import FeatureManagementFlags
from cros.factory.external.chromeos_cli import ifdtool
from cros.factory.external.chromeos_cli import vpd


_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')

# A stub for stdout
StubStdout = namedtuple('StubStdout', ['stdout'])


class MockMainFirmware:
  """Mock main firmware object."""

  def __init__(self, image=None):
    self.GetFileName = lambda *args, **kwargs: 'firmware'
    self.Write = lambda filename: filename == 'firmware'
    self.GetFirmwareImage = lambda: image


class MockIfdtool:

  def __init__(self, flmstr):
    self._flmstr = flmstr

  def Dump(self):
    output = ''
    for idx, value in self._flmstr.items():
      output += f'FLMSTR{idx}:   0x{value:08x} (Host CPU/BIOS)\n'
    return output


class MockIntelMainFirmware(MockMainFirmware):
  """Mock Intel's firmware image object."""

  def __init__(self, flmstr, image=None):
    super().__init__(image)
    self.DumpDescriptor = MockIfdtool(flmstr).Dump

class MockFirmwareImage:
  """Mock firmware image object."""

  def __init__(self, section_map):
    self.has_section = lambda name: name in section_map
    self.get_section = lambda name: section_map[name]

class MockFile:
  """Mock file object."""

  def __init__(self):
    self.name = 'filename'
    self.read = lambda: 'read_results'

  def __enter__(self):
    return self

  def __exit__(self, filetype, value, traceback):
    pass


class MockPath(os.PathLike):

  def __fspath__(self):
    return 'mock_path'

  def __enter__(self):
    return self

  def __exit__(self, filetype, value, traceback):
    pass


class MockME:
  FW_NO_ME = {
      'RO_SECTION': b''
  }
  FW_ME_READ_LOCKED = {
      ifdtool.IntelLayout.ME.value: b'\xff' * 1024
  }
  FW_ME_READ_UNLOCKED = {
      ifdtool.IntelLayout.ME.value: b'\x55' * 1024
  }
  DESCRIPTOR_UNLOCKED = {
      1: 0xffffffff,
      2: 0xffffffff,
      3: 0xffffffff,
      5: 0xffffffff,
  }

  def GetMockedCBMEM(self, sku_flag, mode='NO', fw_table='OK',
                     wp_ro_enabled='YES', ro_wp_vals=('0x1000', '0x14FFFF')):
    output = (f'ME: HFSTS3                  : 0x{sku_flag:08x}\n'
              f'ME: Manufacturing Mode      : {mode}\n'
              f'ME: FW Partition Table      : {fw_table}\n'
              f'ME: WP for RO is enabled    : {wp_ro_enabled}\n')
    if ro_wp_vals:
      output += (f'ME: RO write protection scope - '
                 f'Start={ro_wp_vals[0]}, End={ro_wp_vals[1]}\n')
    return Obj(success=True, stdout=output)


class UtilTest(unittest.TestCase):
  """Unit test for core.Util."""

  def setUp(self):
    self._util = core.Util()

    # Mock out small wrapper functions that do not need unittests.
    self._util.shell = mock.Mock(Shell)
    self._util._IsDeviceFixed = mock.Mock()
    self._util.FindScript = mock.Mock()

  def testGetPrimaryDevicePath(self):
    """Test for GetPrimaryDevice."""

    self._util._IsDeviceFixed.return_value = True
    self._util.shell.return_value = StubStdout('/dev/sda')

    self.assertEqual('/dev/sda', self._util.GetPrimaryDevicePath())
    self.assertEqual('/dev/sda1', self._util.GetPrimaryDevicePath(1))
    self.assertEqual('/dev/sda2', self._util.GetPrimaryDevicePath(2))

    # also test thin callers
    self.assertEqual('/dev/sda5', self._util.GetReleaseRootPartitionPath())
    self.assertEqual('/dev/sda4', self._util.GetReleaseKernelPartitionPath())

    self._util.shell.assert_any_call('rootdev -s -d')
    self._util._IsDeviceFixed.assert_any_call('sda')

  def testGetPrimaryDevicePathNotFixed(self):
    """Test for GetPrimaryDevice when multiple primary devices are found."""

    self._util._IsDeviceFixed.return_value = False
    self._util.shell.return_value = StubStdout('/dev/sda')

    self.assertRaises(Error, self._util.GetPrimaryDevicePath)

    self._util.shell.assert_any_call('rootdev -s -d')
    self._util._IsDeviceFixed.assert_any_call('sda')

  def testFindRunScript(self):
    stub_result = lambda: None
    stub_result.success = True

    self._util.FindScript.return_value = 'script'
    self._util.shell.return_value = stub_result

    self._util.FindAndRunScript('script')
    self._util.shell.assert_called_with('script')

    self._util.FindAndRunScript('script', None)
    self._util.shell.assert_called_with('script')

    self._util.FindAndRunScript('script', ['a'])
    self._util.shell.assert_called_with('script a')

    self._util.FindAndRunScript('script', ['a', 'b'])
    self._util.shell.assert_called_with('script a b')

    self._util.FindAndRunScript('script', ['a', 'b'], ['c=d'])
    self._util.shell.assert_called_with('c=d script a b')

    self._util.FindAndRunScript('script', None, ['c=d'])
    self._util.shell.assert_called_with('c=d script')


class GooftoolTest(unittest.TestCase):
  """Unit test for Gooftool."""


  _SIMPLE_MODEL_SKU_CONFIG_REBRAND = {
      'custom_type': 'rebrand',
      'fw_config': '90913',
  }

  _SIMPLE_MODEL_SKU_CONFIG_CUSTOM_LABEL = {
      'custom_type': 'custom_label',
      'fw_config': '90913',
  }

  def setUp(self):
    self._gooftool = core.Gooftool(
        hwid_version=3, project='chromebook', hwdb_path=_TEST_DATA_PATH)
    self._gooftool._util = mock.Mock(core.Util)
    self._gooftool._util.shell = mock.Mock(Shell)
    self._gooftool.futility = mock.Mock(futility.Futility)

    self._gooftool._flashrom = mock.Mock(flashrom)
    self._gooftool._ifdtool = mock.Mock(ifdtool)
    self._gooftool._unpack_bmpblock = mock.Mock(unpack_bmpblock)
    self._gooftool.vpd = mock.Mock(self._gooftool.vpd)
    self._gooftool._named_temporary_file = mock.Mock(NamedTemporaryFile)
    self._gooftool._cros_config = mock.Mock(self._gooftool._cros_config)
    self._gooftool._cros_config.GetCustomLabelTag.return_value = (True,
                                                                  'unittest')
    self._gooftool._cros_config.GetModelName.return_value = 'unittest'
    self._gooftool._cros_config.GetFirmwareImageName.return_value = 'unittest'

    self._gooftool._gsctool = mock.Mock(self._gooftool._gsctool)
    self._gooftool._gsctool.GetFeatureManagementFlags.return_value = (
        FeatureManagementFlags(False, 0))


  def testLoadHWIDDatabase(self):
    db = self._gooftool.db  # Shouldn't raise any exception.

    # Assure loading DB multiple times is prevented.
    self.assertIs(self._gooftool.db, db)

  @mock.patch.object(sys_utils, 'MountPartition', autospec=True)
  @mock.patch.object(pygpt, 'GPT', autospec=True)
  def testVerifyKey(self, mock_pygpt, mock_mount):
    self._gooftool._util.GetReleaseKernelPathFromRootPartition.return_value = \
        '/dev/zero'
    self._gooftool._flashrom.LoadMainFirmware.side_effect = [
        MockMainFirmware(),
        MockMainFirmware(
            MockFirmwareImage({
                'GBB': b'GBB',
                'FW_MAIN_A': b'MA',
                'FW_MAIN_B': b'MB',
                'VBLOCK_A': b'VA',
                'VBLOCK_B': b'VB'
            }))
    ]

    # TODO(hungte) Improve unit test scope.
    def fake_tmpexc(*unused_args, **unused_kargs):
      return ''

    class FakeGPT:

      def LoadFromFile(self):
        gpt = mock.Mock()
        gpt.IsLastPartition = mock.Mock(return_value=True)
        return gpt

    mock_mount.return_value = MockPath()

    mock_pygpt.return_value = FakeGPT()

    self._gooftool.VerifyKeys('/dev/null', _tmpexec=fake_tmpexc)
    self._gooftool._flashrom.LoadMainFirmware.assert_called()

  def testVerifySystemTime(self):
    self._gooftool._util.GetReleaseRootPartitionPath.return_value = 'root'
    self._gooftool._util.shell.return_value = Obj(
        stdout='Filesystem created:     Mon Jan 25 16:13:18 2016\n',
        success=True)

    bad_system_time = time.mktime(time.strptime('Sun Jan 24 15:00:00 2016'))
    good_system_time = time.mktime(time.strptime('Tue Jan 26 15:00:00 2016'))

    self._gooftool.VerifySystemTime(system_time=good_system_time)
    self.assertRaises(Error, self._gooftool.VerifySystemTime,
                      release_rootfs='root', system_time=bad_system_time)
    self._gooftool._util.GetReleaseRootPartitionPath.assert_called()
    self._gooftool._util.shell.assert_called_with('dumpe2fs -h root')

  def testVerifyRootFs(self):
    fake_attrs = {'test': 'value'}
    self._gooftool._util.GetPartitionDevice.return_value = 'root'
    self._gooftool._util.GetCgptAttributes.return_value = fake_attrs
    self._gooftool._util.SetCgptAttributes.return_value = None

    self._gooftool.VerifyRootFs('root3')
    self._gooftool._util.GetPartitionDevice.assert_called_once_with('root3')
    self._gooftool._util.GetCgptAttributes.assert_called_once_with('root')
    self._gooftool._util.InvokeChromeOSPostInstall.assert_called_once_with(
        'root3')
    self._gooftool._util.SetCgptAttributes.assert_called_once_with(fake_attrs,
                                                                   'root')

  @mock.patch('os.path.exists')
  @mock.patch('builtins.open')
  def testVerifyTPM(self, open_mock, path_exists_mock):
    # Mock os.path.exists to ensure that 3.18+ kernel TPM path does not exist.
    path_exists_mock.return_value = False
    open_mock_calls = [
        mock.call('/sys/class/misc/tpm0/device/enabled', encoding='utf-8',
                  mode='r'),
        mock.call('/sys/class/misc/tpm0/device/owned', encoding='utf-8',
                  mode='r'),
    ]

    # It's correct tpm sysfs status: enabled = 1, owned = 0
    open_mock.side_effect = [
        mock.mock_open(read_data='1').return_value,
        mock.mock_open(read_data='0').return_value
    ]

    # It's correct tpm manager status.
    self._gooftool._util.GetTPMManagerStatus.return_value = {
        'is_enabled': 'true',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }

    # Should pass w/ correct tpm sysfs status + correct tpm manager status.
    self._gooftool.VerifyTPM()
    path_exists_mock.assert_called_with('/sys/class/tpm/tpm0/device')
    self.assertEqual(open_mock.call_args_list, open_mock_calls)

  @mock.patch('os.path.exists')
  @mock.patch('builtins.open')
  def testVerifyTPMWrongSysfsStatus(self, open_mock, path_exists_mock):
    # Mock os.path.exists to ensure that 3.18+ kernel TPM path does not exist.
    path_exists_mock.return_value = False

    # It's wrong tpm sysfs status: enabled = 1, owned = 1
    # The correct should be: enabled = 1, owned = 0
    open_mock.side_effect = [
        mock.mock_open(read_data='1').return_value,
        mock.mock_open(read_data='1').return_value
    ]

    # It's correct tpm manager status.
    self._gooftool._util.GetTPMManagerStatus.return_value = {
        'is_enabled': 'true',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }

    # Should raise error w/ wrong tpm sysfs status.
    self.assertRaises(Error, self._gooftool.VerifyTPM)
    path_exists_mock.assert_called_with('/sys/class/tpm/tpm0/device')

  @mock.patch('os.path.exists')
  @mock.patch('builtins.open')
  def testVerifyTPMWrongManagerStatus(self, open_mock, path_exists_mock):
    # Mock os.path.exists to ensure that 3.18+ kernel TPM path does not exist.
    path_exists_mock.return_value = False

    # It's correct tpm sysfs status: enabled = 1, owned = 0
    open_mock.side_effect = [
        mock.mock_open(read_data='1').return_value,
        mock.mock_open(read_data='0').return_value
    ]

    # It's wrong tpm manager status, the correct should be:
    # is_enabled = true, is_owned = false, is_owner_password_present = false
    self._gooftool._util.GetTPMManagerStatus.return_value = {
        'is_enabled': 'false',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }

    # Should raise error w/ wrong tpm manager status.
    self.assertRaises(Error, self._gooftool.VerifyTPM)
    path_exists_mock.assert_called_with('/sys/class/tpm/tpm0/device')

  def testVerifyManagementEngineLockedNoME(self):
    # No ME firmware
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(None, MockFirmwareImage(MockME.FW_NO_ME))
    self._gooftool.VerifyManagementEngineLocked()

  def testVerifyManagementEngineLockedUnknownSKU(self):
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        MockME.DESCRIPTOR_UNLOCKED,
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))

    # Raise since it is an unknown SKU
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(SKU.Unknown.flag)
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

  def testVerifyManagementEngineLockedConsumerSKU(self):
    consumer = SKU.Consumer
    # Read locked ME section + locked cbmem + locked descriptor
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        consumer.flmstr,
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(consumer.flag)
    # Pass since everything is fine
    self._gooftool.VerifyManagementEngineLocked()

    # Read unlocked ME section + locked cbmem + locked descriptor
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        consumer.flmstr,
        MockFirmwareImage(MockME.FW_ME_READ_UNLOCKED))
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(consumer.flag)
    # Raise since the ME section is not 0xff
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

    # Read locked ME section + locked cbmem + unlocked descriptor
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        MockME().DESCRIPTOR_UNLOCKED,
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(consumer.flag)
    # Raise since the descriptor is not locked
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

  def testVerifyManagementEngineLockedLiteSKU(self):
    lite = SKU.Lite
    # Read locked ME section + locked cbmem + locked descriptor
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        lite.flmstr,
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag)
    # Pass since everything is fine
    self._gooftool.VerifyManagementEngineLocked()

    # Read locked ME section + locked cbmem with invalid manufacturing mode
    # + locked descriptor
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag, mode='YES')
    # Raise since Manufacturing Mode is not NO
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

    # Read locked ME section + locked cbmem with invalid FW partition table
    # + locked descriptor
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag, fw_table='BAD')
    # Raise since FW Partition Table is not OK
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

    # Read locked ME section + locked cbmem with WP in RO not enabled
    # + locked descriptor
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag, wp_ro_enabled='NO')
    # Raise since WP in RO is not YES
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

    # Read locked ME section + locked cbmem + locked descriptor
    # No RO WP scope.
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag, ro_wp_vals=None)
    # Raise since there's no RO WP scope.
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

    # Read unlocked ME section + locked cbmem + locked descriptor
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        lite.flmstr,
        MockFirmwareImage(MockME.FW_ME_READ_UNLOCKED))
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag)
    # Pass since we don't check the SI_ME content
    self._gooftool.VerifyManagementEngineLocked()

    # Read locked ME section + locked cbmem + unlocked descriptor
    self._gooftool._ifdtool.LoadIntelMainFirmware.return_value = \
      MockIntelMainFirmware(
        MockME().DESCRIPTOR_UNLOCKED,
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite.flag)
    # Raise since the descriptor is not locked
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

  def testGenerateStableDeviceSecretSuccess(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('00' * 32 + '\n')

    self._gooftool.GenerateStableDeviceSecret()
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)
    self._gooftool.vpd.UpdateData.assert_called_once_with(
        dict(stable_device_secret_DO_NOT_SHARE='00' * 32),
        partition=vpd.VPD_READONLY_PARTITION_NAME)

  def testGenerateStableDeviceSecretNoOutput(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('')

    self.assertRaisesRegex(Error, 'Error validating device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)

  def testGenerateStableDeviceSecretShortOutput(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('00' * 31)

    self.assertRaisesRegex(Error, 'Error validating device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)

  def testGenerateStableDeviceSecretBadOutput(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('Error!')

    self.assertRaisesRegex(Error, 'Error validating device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)

  def testGenerateStableDeviceSecretBadReleaseImageVersion(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6886.0.0'

    self.assertRaisesRegex(Error, 'Release image version',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()

  def testGenerateStableDeviceSecretVPDWriteFailed(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('00' * 32 + '\n')
    self._gooftool.vpd.UpdateData.side_effect = Exception()

    self.assertRaisesRegex(Error, 'Error writing device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)
    self._gooftool.vpd.UpdateData.assert_called_once_with(
        dict(stable_device_secret_DO_NOT_SHARE='00' * 32),
        partition=vpd.VPD_READONLY_PARTITION_NAME)

  def testWriteHWID(self):
    self._gooftool._flashrom.LoadMainFirmware.return_value = MockMainFirmware()

    self._gooftool.WriteHWID('hwid')

    self._gooftool.futility.WriteHWID.assert_called_with('firmware', 'hwid')
    self._gooftool._flashrom.LoadMainFirmware.assert_called()

  def testVerifyWPSwitch(self):
    shell_calls = [
        mock.call('crossystem wpsw_cur'),
        mock.call('ectool flashprotect')]

    # 1st call: AP and EC wpsw are enabled.
    self._gooftool._util.shell.side_effect = [
        StubStdout('1'),
        StubStdout('Flash protect flags: 0x00000008 wp_gpio_asserted\n'
                   'Valid flags:...')]

    self._gooftool.VerifyWPSwitch()
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

    # 2nd call: AP wpsw is disabled.
    self._gooftool._util.shell.reset_mock()
    self._gooftool._util.shell.side_effect = [StubStdout('0')]

    self.assertRaises(Error, self._gooftool.VerifyWPSwitch)
    self.assertEqual(self._gooftool._util.shell.call_args_list,
                     [shell_calls[0]])

    # 3st call: AP wpsw is enabled but EC is disabled.
    self._gooftool._util.shell.reset_mock()
    self._gooftool._util.shell.side_effect = [
        StubStdout('1'),
        StubStdout('Flash protect flags: 0x00000000\nValid flags:...')]

    self.assertRaises(Error, self._gooftool.VerifyWPSwitch)
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

  def _SetupVPDMocks(self, ro=None, rw=None):
    """Set up mocks for vpd related tests.

    Args:
      ro: The dictionary to use for the RO VPD if set.
      rw: The dictionary to use for the RW VPD if set.
    """
    def GetAllDataSideEffect(*unused_args, **kwargs):
      if kwargs['partition'] == vpd.VPD_READONLY_PARTITION_NAME:
        return ro
      if kwargs['partition'] == vpd.VPD_READWRITE_PARTITION_NAME:
        return rw
      return None

    self._gooftool.vpd.GetAllData.side_effect = GetAllDataSideEffect

  def testVerifyReleaseChannel_CanaryChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'canary-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self.assertRaisesRegex(Error,
                           'Release image channel is incorrect: canary-channel',
                           self._gooftool.VerifyReleaseChannel)

  def testVerifyReleaseChannel_DevChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'dev-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self._gooftool.VerifyReleaseChannel()

  def testVerifyReleaseChannel_DevChannelFailed(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'dev-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']
    enforced_channels = ['stable', 'beta']

    self.assertRaisesRegex(Error,
                           'Release image channel is incorrect: dev-channel',
                           self._gooftool.VerifyReleaseChannel,
                           enforced_channels)

  def testVerifyReleaseChannel_BetaChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'beta-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self._gooftool.VerifyReleaseChannel()

  def testVerifyReleaseChannel_BetaChannelFailed(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'beta-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']
    enforced_channels = ['stable']

    self.assertRaisesRegex(Error,
                           'Release image channel is incorrect: beta-channel',
                           self._gooftool.VerifyReleaseChannel,
                           enforced_channels)

  def testVerifyReleaseChannel_StableChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'stable-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self._gooftool.VerifyReleaseChannel()

  def testVerifyReleaseChannel_InvalidEnforcedChannels(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'stable-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']
    enforced_channels = ['canary']

    self.assertRaisesRegex(Error,
                           r'Enforced channels are incorrect: \[\'canary\'\].',
                           self._gooftool.VerifyReleaseChannel,
                           enforced_channels)

  # TODO (b/212216855)
  @label_utils.Informational
  def testSetFirmwareBitmapLocalePass(self):
    """Test for a normal process of setting firmware bitmap locale."""

    # Stub data from VPD for zh.
    self._gooftool._flashrom.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro=dict(region='tw'))

    f = MockFile()
    f.read = lambda: 'ja\nzh\nen'
    image_file = 'firmware'
    self._gooftool._named_temporary_file.return_value = f

    shell_calls = [
        mock.call(
            f'cbfstool {image_file} extract -n locales -f {f.name} -r COREBOOT'
        ),
        # Expect index = 1 for zh is matched.
        mock.call('crossystem loc_idx=1')
    ]

    self._gooftool.SetFirmwareBitmapLocale()
    self._gooftool._flashrom.LoadMainFirmware.assert_any_call()
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

  # TODO (b/212216855)
  @label_utils.Informational
  def testSetFirmwareBitmapLocaleNoCbfs(self):
    """Test for legacy firmware, which stores locale in bmpblk."""

    # Stub data from VPD for zh.
    self._gooftool._flashrom.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro=dict(region='tw'))

    f = MockFile()
    f.read = lambda: ''
    image_file = 'firmware'
    self._gooftool._named_temporary_file.return_value = f
    self._gooftool._unpack_bmpblock.return_value = {'locales': ['ja', 'zh',
                                                                'en']}
    shell_calls = [
        mock.call(
            f'cbfstool {image_file} extract -n locales -f {f.name} -r COREBOOT'
        ),
        mock.call(f'futility gbb -g --bmpfv={f.name} {image_file}'),
        # Expect index = 1 for zh is matched.
        mock.call('crossystem loc_idx=1')
    ]

    self._gooftool.SetFirmwareBitmapLocale()
    self._gooftool._flashrom.LoadMainFirmware.assert_any_call()
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)
    self._gooftool._unpack_bmpblock.assert_called_once_with(f.read())

  # TODO (b/212216855)
  @label_utils.Informational
  def testSetFirmwareBitmapLocaleNoMatch(self):
    """Test for setting firmware bitmap locale without matching default locale.
    """

    # Stub data from VPD for en.
    self._gooftool._flashrom.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro=dict(region='us'))

    f = MockFile()
    # Stub for multiple available locales in the firmware bitmap, but missing
    # 'en'.
    f.read = lambda: 'ja\nzh\nfr'
    image_file = 'firmware'
    self._gooftool._named_temporary_file.return_value = f

    self.assertRaises(Error, self._gooftool.SetFirmwareBitmapLocale)
    self._gooftool._flashrom.LoadMainFirmware.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        f'cbfstool {image_file} extract -n locales -f {f.name} -r COREBOOT')

  def testSetFirmwareBitmapLocaleNoVPD(self):
    """Test for setting firmware bitmap locale without default locale in VPD."""

    # VPD has no locale data.
    self._gooftool._flashrom.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro={})

    self.assertRaises(Error, self._gooftool.SetFirmwareBitmapLocale)

  def testGetSystemDetails(self):
    """Test for GetSystemDetails to ensure it returns desired keys."""

    self._gooftool._util.sys_interface = mock.Mock()
    self._gooftool._util.sys_interface.info = info.SystemInfo()
    self._gooftool._util.GetSystemInfo.return_value = core.Util.GetSystemInfo(
        self._gooftool._util)

    system_summary_keys = {
        'cbi',
        'crosid',
        'device',
        'factory',
        'fw',
        'gsc',
        'hw',
        'image',
        'system',
        'vpd',
        'wp',
        'crossystem',
        'modem_status',
    }
    self.assertEqual(system_summary_keys,
                     set(self._gooftool.GetSystemDetails().keys()))
    self._gooftool._util.GetSystemInfo.assert_called_once()

  def testGSCWriteFlashInfoWithCustomType(self):
    """Test for custom label field.

    Custom label field should only exist in VPD when custom type is custom
    label.
    """

    model_sku_utils.GetDesignConfig = mock.Mock()
    self._gooftool.GSCSetBoardId = mock.Mock()
    self._gooftool._util.sys_interface = None

    # custom type is 'custom_label' but no custom label field in VPD
    config = self._SIMPLE_MODEL_SKU_CONFIG_CUSTOM_LABEL
    model_sku_utils.GetDesignConfig.return_value = config
    self._gooftool.vpd.GetValue.return_value = None

    self.assertRaisesRegex(
        Error, 'This is a custom label device, but custom_label_tag is not set '
        'in VPD.', self._gooftool.GSCWriteFlashInfo)

    # custom type is rebrand and no custom label field in VPD
    config = self._SIMPLE_MODEL_SKU_CONFIG_REBRAND
    model_sku_utils.GetDesignConfig.return_value = config
    self.assertRaisesRegex(
        Error, 'custom_label_tag reported by cros_config and VPD does not '
        'match.  Have you reboot the device after updating VPD '
        'fields?', self._gooftool.GSCWriteFlashInfo)

  def testInitialCrosConfigIdentity_KeysAreStrings(self):
    isString = [
        isinstance(key, str)
        for key in CrosConfigIdentity(IdentitySourceEnum.cros_config).keys()
    ]
    self.assertEqual(isString, [True] * len(isString))

  def testMatchConfigWithIdentity_X86_Frid(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['smbios-name-match'] = 'skolas'
    identity['frid'] = 'Google_Skolas'
    identity['sku-id'] = 'sku1'
    identity['customization-id'] = '1'
    identity['custom-label-tag'] = 'custom-label-tag'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Skolas',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Skolas',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 2
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Skolas_Something',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertDictEqual(matched_config, configs[0])

  def testMatchConfigWithIdentity_extraVPD(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['frid'] = 'Google_Skolas'
    identity['sku-id'] = 'sku1'
    identity['customization-id'] = 'empty'
    identity['custom-label-tag'] = 'custom-label-tag'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Skolas',
                'sku-id': 1
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertIsNone(matched_config)

  def testMatchConfigWithIdentity_noVPD(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['frid'] = 'Google_Skolas'
    identity['sku-id'] = 'sku1'
    identity['customization-id'] = 'empty'
    identity['custom-label-tag'] = 'empty'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Skolas',
                'sku-id': 1
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertDictEqual(matched_config, configs[0])

  def testMatchConfigWithIdentity_Arm_Frid(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['device-tree-compatible-match'] = \
        'google,tentacruelgoogle,corsolamediatek,mt8186'
    identity['frid'] = 'Google_Tentacruel'
    identity['sku-id'] = '1'
    identity['customization-id'] = '1'
    identity['custom-label-tag'] = 'custom-label-tag'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Tentacruel',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Tentacruel',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 2
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'frid': 'Google_Tentacruel',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertDictEqual(matched_config, configs[0])

  def testMatchConfigWithIdentity_Smbios(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['smbios-name-match'] = 'Skolas'
    identity['frid'] = 'Google_Skolas'
    identity['sku-id'] = 'sku1'
    identity['customization-id'] = '1'
    identity['custom-label-tag'] = 'custom-label-tag'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'smbios-name-match': 'Skolas',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'smbios-name-match': 'Skolas',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 2
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'smbios-name-match': 'Skolas',
                'custom-label-tag': 'some-other-tag',
                'customization-id': '2',
                'sku-id': 1
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertDictEqual(matched_config, configs[0])

  def testMatchConfigWithIdentity_DeviceTree(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['device-tree-compatible-match'] = \
        'google,tentacruelgoogle,corsolamediatek,mt8186'
    identity['frid'] = 'Google_Tentacruel'
    identity['sku-id'] = '1'
    identity['customization-id'] = '1'
    identity['custom-label-tag'] = 'custom-label-tag'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'device-tree-compatible-match': 'google,tentacruel',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'device-tree-compatible-match': 'google,tentacruel',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 2
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'device-tree-compatible-match': 'google,tentacruel',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1',
                'sku-id': 1
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertDictEqual(matched_config, configs[0])

  def testMatchConfigWithIdentity_NoSkuId(self):
    identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    identity['smbios-name-match'] = 'Hayato'
    identity['frid'] = 'Google_Hayato'
    identity['sku-id'] = ''
    identity['customization-id'] = '1'
    identity['custom-label-tag'] = 'custom-label-tag'
    identity[vpd_utils.non_inclusive_custom_label_tag_cros_config_key] = 'empty'

    configs = [
        {
            'brand-code': 'zzcr',
            'identity': {
                'smbios-name-match': 'Hayato',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1'
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'smbios-name-match': 'Hayato',
                'custom-label-tag': 'some-other-tag',
                'customization-id': '2'
            }
        },
        {
            'brand-code': 'zzcr',
            'identity': {
                'smbios-name-match': 'Hayato_something',
                'custom-label-tag': 'custom-label-tag',
                'customization-id': '1'
            }
        },
    ]

    matched_config = self._gooftool._MatchConfigWithIdentity(configs, identity)
    self.assertDictEqual(matched_config, configs[0])

if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()
