#!/usr/bin/env python3
# pylint: disable=protected-access
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.gooftool import vpd_data
from cros.factory.gooftool import vpd_utils
from cros.factory.test.rules import phase
from cros.factory.unittest_utils import label_utils
from cros.factory.utils import file_utils

from cros.factory.external.chromeos_cli import cros_config
from cros.factory.external.chromeos_cli import vpd


VPDUTILS = 'cros.factory.gooftool.vpd_utils.VPDUtils'
CROS_CONFIG = 'cros.factory.external.chromeos_cli.cros_config.CrosConfig'
PHASE = 'cros.factory.test.rules.phase.GetPhase'


class VPDUtilsTest(unittest.TestCase):
  _SIMPLE_VALID_RO_VPD_DATA = {
      'serial_number': 'A1234',
      'region': 'us',
  }

  _SIMPLE_VALID_RW_VPD_DATA = {
      'gbind_attribute': ('=CjAKIAABAgMEBQYHCAkKCwwNDg8QERITFBUWF'
                          'xgZGhscHR4fEAAaCmNocm9tZWJvb2sQhOfLlA8='),
      'ubind_attribute': ('=CjAKIAABAgMEBQYHCAkKCwwNDg8QERITFBUWF'
                          'xgZGhscHR4fEAEaCmNocm9tZWJvb2sQgdSQ-AI='),
      'rlz_embargo_end_date': '2018-03-09',
      'should_send_rlz_ping': '1',
  }

  def setUp(self):
    self._project = 'chromebook'
    self.vpd_utils = vpd_utils.VPDUtils(self._project)
    self.vpd_utils._vpd = mock.Mock(self.vpd_utils._vpd)
    self.get_amp_info = mock.patch(
        'cros.factory.test.utils.smart_amp_utils.GetSmartAmpInfo')
    self.get_amp_info.start().return_value = [None, None, None]
    self.addCleanup(self.get_amp_info.stop)
    mock_phase = mock.patch(PHASE)
    mock_phase.start().return_value = phase.PVT
    self.addCleanup(mock_phase.stop)


  def test_GetInvalidVPDFieldsUnknownKeys(self):
    data = {
        'known': '1',
        're1': 'a',
        're2': '.',
        'unknown1': '1',
        'unknown2': '1'
    }
    known_key = {
        'known': r'.*'
    }
    known_key_re = {
        're[0-9]': r'.*'
    }
    invalid_key, _ = self.vpd_utils._GetInvalidVPDFields(
        data, known_key, known_key_re)
    self.assertEqual(invalid_key, ['unknown1', 'unknown2'])

  def test_GetInvalidVPDFieldsUnknownValues(self):
    data = {
        'key1': '1',
        'key2': 'a',
        'key3': '.',
    }
    known_key_re = {
        'key[0-9]': r'[0-9]'
    }

    _, invalid_values = self.vpd_utils._GetInvalidVPDFields(
        data, {}, known_key_re)
    self.assertEqual(invalid_values, [('key2', '[0-9]'), ('key3', '[0-9]')])

  @mock.patch('logging.info')
  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  def testClearUnknownVPDEntries(self, mock_clear_vpd, mock_invalid_vpd,
                                 mock_info):
    self.vpd_utils._vpd.GetAllData.return_value = {
        'ubind_attribute': 1
    }
    mock_invalid_vpd.return_value = ['unknown'], []

    self.vpd_utils.ClearUnknownVPDEntries()

    mock_invalid_vpd.assert_called_with({'ubind_attribute': 1},
                                        dict(vpd_data.REQUIRED_RW_DATA,
                                             **vpd_data.KNOWN_RW_DATA),
                                        vpd_data.KNOWN_RW_DATA_RE)
    mock_clear_vpd.assert_called_with(['unknown'])
    mock_info.assert_called_with('Current RW VPDs: %r',
                                 {'ubind_attribute': '<redacted type int>'})

  @mock.patch('logging.info')
  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  def testClearUnknownVPDEntriesAllValid(self, mock_invalid_vpd, mock_info):
    self.vpd_utils._vpd.GetAllData.return_value = {
        'known': 1
    }
    mock_invalid_vpd.return_value = [], []

    self.vpd_utils.ClearUnknownVPDEntries()

    mock_info.assert_called_with('No unknown RW VPDs are found. Skip clearing.')

  @mock.patch('logging.info')
  def testClearRWVPDEntries(self, mock_info):
    keys = ['key1', 'key2']

    self.vpd_utils._ClearRWVPDEntries(keys)

    self.vpd_utils._vpd.UpdateData.assert_called_with(
        {
            'key1': None,
            'key2': None
        }, partition=vpd.VPD_READWRITE_PARTITION_NAME)
    mock_info.assert_called_with('Removing VPD entries with key %r', keys)

  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  def testCheckVPDFields(self, mock_invalid_vpd):
    mock_invalid_vpd.return_value = [], []
    self.vpd_utils._CheckVPDFields('section', {'req': ''}, {'req': ''},
                                   {'opt': ''}, {'opt_re': ''})

    mock_invalid_vpd.assert_called_with({'req': ''}, {
        'req': '',
        'opt': ''
    }, {'opt_re': ''})

  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  def testCheckVPDFieldsError(self, mock_invalid_vpd):
    mock_invalid_vpd.return_value = ['key'], []
    self.assertRaises(vpd_utils.VPDError, self.vpd_utils._CheckVPDFields, '',
                      {'key': 1}, {}, {}, {})

    mock_invalid_vpd.return_value = [], [('key', '[0-9]')]
    self.assertRaises(vpd_utils.VPDError, self.vpd_utils._CheckVPDFields, '',
                      {'key': 1}, {}, {}, {})

  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  def testClearFactoryVPDEntries(self, mock_clear_vpd):
    data = {
        'factory.key': 1,
        'factory.key1': 1,
        'component.key': 1,
        'serials.key': 1
    }
    self.vpd_utils._vpd.GetAllData.return_value = data

    self.vpd_utils.ClearFactoryVPDEntries()

    mock_clear_vpd.assert_called_with(data.keys())

  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  def testClearFactoryVPDEntriesUnknownDot(self, mock_clear_vpd):
    self.vpd_utils._vpd.GetAllData.return_value = {
        'unknow.key': 1
    }

    self.assertRaises(vpd_utils.VPDError, self.vpd_utils.ClearFactoryVPDEntries)
    mock_clear_vpd.assert_not_called()

  @mock.patch('logging.info')
  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  def testClearFactoryVPDEntriesNonDot(self, mock_clear_vpd, mock_info):
    self.vpd_utils._vpd.GetAllData.return_value = {
        'key': 1
    }

    self.vpd_utils.ClearFactoryVPDEntries()

    mock_clear_vpd.assert_not_called()
    mock_info.assert_called_with(
        'No factory-related RW VPDs are found. Skip clearing.')

  @mock.patch('logging.info')
  @mock.patch('cros.factory.test.utils.smart_amp_utils.GetSmartAmpInfo')
  def testGetAudioVPDROData(self, mock_get_amp_info, mock_info):
    mock_get_amp_info.return_value = 'speaker_amp', 'sound_card_init_file', [
        'channel1', 'channel2'
    ]
    res = self.vpd_utils._GetAudioVPDROData()

    self.assertEqual(
        res, {
            'dsm_calib_r0_0': r'[0-9]*',
            'dsm_calib_temp_0': r'[0-9]*',
            'dsm_calib_r0_1': r'[0-9]*',
            'dsm_calib_temp_1': r'[0-9]*'
        })
    mock_info.assert_has_calls([
        mock.call('Amplifier %s found on DUT.', 'speaker_amp'),
        mock.call(
            'The VPD RO should contain `dsm_calib_r0_N` and'
            ' `dsm_calib_temp_N` where N ranges from 0 ~ %d.', 1)
    ])

  @mock.patch('logging.info')
  @mock.patch('cros.factory.test.utils.smart_amp_utils.GetSmartAmpInfo')
  def testGetAudioVPDRODataNotFound(self, mock_get_amp_info, mock_info):
    mock_get_amp_info.return_value = 'speaker_amp', '', ['channel']

    self.assertEqual(self.vpd_utils._GetAudioVPDROData(), {})
    mock_info.assert_called_with(
        'No smart amplifier found! Skip checking DSM VPD value.')

  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationCodeReturnProject(self, mock_cros_config):
    mock_cros_config.return_value = None
    self.assertEqual(self._GetDeviceName(), self._project)

    mock_cros_config.return_value = {
        'key': 'value'
    }
    self.assertEqual(self._GetDeviceName(), self._project)

    mock_cros_config.assert_called_with('custom_label_reg_code',
                                        validate_schema=False)

  @mock.patch(f'{CROS_CONFIG}.GetCustomLabelTag')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationNotCustomLabel(self, mock_cros_config,
                                                     mock_custom_label):
    mock_cros_config.return_value = {
        self._project: {}
    }
    mock_custom_label.return_value = False, ''
    self.assertEqual(self._GetDeviceName(), self._project)

    mock_cros_config.return_value = {
        self._project: {
            'key': 'value'
        }
    }
    mock_custom_label.return_value = True, 'label_key'
    self.assertEqual(self._GetDeviceName(), self._project)

    mock_cros_config.return_value = {
        self._project: {
            'label_key': ''
        }
    }
    mock_custom_label.return_value = True, 'label_key'
    self.assertEqual(self._GetDeviceName(), self._project)

  @mock.patch(f'{CROS_CONFIG}.GetCustomLabelTag')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationCustomLabel(self, mock_cros_config,
                                                  mock_custom_label):
    mock_cros_config.return_value = {
        self._project: {
            'label_key': 'value'
        }
    }
    mock_custom_label.return_value = True, 'label_key'

    self.assertEqual(self._GetDeviceName(), 'label_key')

  @mock.patch('logging.warning')
  @mock.patch(f'{CROS_CONFIG}.GetCustomLabelTag')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationCustomLabelFallback(
      self, mock_cros_config, mock_custom_label, mock_warn):
    mock_cros_config.side_effect = [
        None, {
            self._project: {
                'label_key': 'value'
            }
        }
    ]
    mock_custom_label.return_value = True, 'label_key'

    self.assertEqual(self._GetDeviceName(), 'label_key')
    mock_cros_config.assert_has_calls([
        mock.call('custom_label_reg_code', validate_schema=False),
        mock.call('whitelabel_reg_code', validate_schema=False)
    ])
    mock_warn.assert_called_with(
        '"whitelabel_reg_code.json is deprecated, please rename it to %s',
        'custom_label_reg_code')

  def _GetDeviceName(self):
    return self.vpd_utils._GetDeviceNameForRegistrationCode(self._project)

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

    self.vpd_utils._vpd.GetAllData.side_effect = GetAllDataSideEffect

  # TODO (b/212216855)
  @label_utils.Informational
  def testVerifyVPD_AllValid(self):
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA,
                        rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.vpd_utils.VerifyVPD()
    self.vpd_utils._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READONLY_PARTITION_NAME)
    self.vpd_utils._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READWRITE_PARTITION_NAME)

  @mock.patch.object(cros_config, 'CrosConfig')
  def testVerifyVPD_NonSmartAmp(self, mock_cros_config):
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA,
                        rw=self._SIMPLE_VALID_RW_VPD_DATA)
    mock_cros_config.return_value.GetAmplifier.return_value = 'MAX98360'
    mock_cros_config.return_value.GetSoundCardInit.return_value = None
    self.get_amp_info.stop()

    # Should not fail, since MAX98360 is not a smart amplifier.
    self.vpd_utils.VerifyVPD()
    self.vpd_utils._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READONLY_PARTITION_NAME)
    self.vpd_utils._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READWRITE_PARTITION_NAME)
    self.get_amp_info.start()  # To prevent runtime error before python 3.8

  @mock.patch.object(cros_config, 'CrosConfig')
  @mock.patch.object(file_utils, 'CheckPath')
  @mock.patch.object(file_utils, 'ReadFile')
  def testVerifyVPD_SmartAmpNoDSM(self, mock_file_reader, mock_path_checker,
                                  mock_cros_config):
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA,
                        rw=self._SIMPLE_VALID_RW_VPD_DATA)
    mock_cros_config.return_value.GetAmplifier.return_value = 'MAX98373'
    mock_cros_config.return_value.GetSoundCardInit.return_value = 'factory.yaml'
    mock_path_checker.return_value = True
    mock_file_reader.return_value = \
      '  temp_ctrl: ["Left ADC TEMP", "Right ADC TEMP"]'
    self.get_amp_info.stop()

    # Should fail, since dsm calib is missing.
    # Since the dictionary ordering is not deterministic, we use regex to parse
    # the error messages.
    dsm_string_regex = 'dsm_calib_(?:temp|r0)_[0-1]'
    self.assertRaisesRegex(
        vpd_utils.VPDError,
        f'Missing required RO VPD values: (?:{dsm_string_regex},){{3}}'
        f'{dsm_string_regex}', self.vpd_utils.VerifyVPD)
    self.get_amp_info.start()  # To prevent runtime error before python 3.8

  def testVerifyVPD_NoRegion(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    del ro_vpd_value['region']
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    # Should fail, since region is missing.
    self.assertRaisesRegex(vpd_utils.VPDError,
                           'Missing required RO VPD values: region',
                           self.vpd_utils.VerifyVPD)

  def testVerifyVPD_InvalidRegion(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    ro_vpd_value['region'] = 'nonexist'
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.assertRaisesRegex(vpd_utils.VPDError, 'Unknown region: "nonexist".',
                           self.vpd_utils.VerifyVPD)

  def testVerifyVPD_InvalidMACKey(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    ro_vpd_value['wifi_mac'] = '00:11:de:ad:be:ef'
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.assertRaisesRegex(vpd_utils.VPDError,
                           'Unexpected RO VPD: wifi_mac=00:11:de:ad:be:ef.',
                           self.vpd_utils.VerifyVPD)

  # TODO (b/212216855)
  @label_utils.Informational
  def testVerifyVPD_InvalidRegistrationCode(self):
    rw_vpd_value = self._SIMPLE_VALID_RW_VPD_DATA.copy()
    rw_vpd_value['gbind_attribute'] = 'badvalue'
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA, rw=rw_vpd_value)

    self.assertRaisesRegex(vpd_utils.VPDError, 'gbind_attribute is invalid:',
                           self.vpd_utils.VerifyVPD)

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch(PHASE)
  def testVerifyVPD_InvalidTestingRegistrationCodePVT_DOGFOOD(
      self, get_phase_mock):
    get_phase_mock.return_value = phase.PVT_DOGFOOD
    rw_vpd_value = self._SIMPLE_VALID_RW_VPD_DATA.copy()
    rw_vpd_value['gbind_attribute'] = (
        '=CjAKIP______TESTING_______-rhGkyZUn_'
        'zbTOX_9OQI_3EAAaCmNocm9tZWJvb2sQouDUgwQ=')
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA, rw=rw_vpd_value)

    self.assertRaisesRegex(vpd_utils.VPDError, 'gbind_attribute is invalid: ',
                           self.vpd_utils.VerifyVPD)

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch(PHASE)
  def testVerifyVPD_InvalidTestingRegistrationCodeDVT(self, get_phase_mock):
    get_phase_mock.return_value = phase.DVT
    rw_vpd_value = self._SIMPLE_VALID_RW_VPD_DATA.copy()
    rw_vpd_value['gbind_attribute'] = (
        '=CjAKIP______TESTING_______-rhGkyZUn_'
        'zbTOX_9OQI_3EAAaCmNocm9tZWJvb2sQouDUgwQ=')
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA, rw=rw_vpd_value)
    self.vpd_utils.VerifyVPD()

  def testVerifyVPD_UnexpectedValues(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    ro_vpd_value['initial_locale'] = 'en-US'
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.assertRaisesRegex(vpd_utils.VPDError,
                           'Unexpected RO VPD: initial_locale=en-US',
                           self.vpd_utils.VerifyVPD)

if __name__ == '__main__':
  unittest.main()
