#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.gooftool import vpd_data
from cros.factory.gooftool import vpd_utils

from cros.factory.external.chromeos_cli import vpd


VPDTOOL = 'cros.factory.external.chromeos_cli.vpd.VPDTool'
VPDUTILS = 'cros.factory.gooftool.vpd_utils.VPDUtils'
CROS_CONFIG = 'cros.factory.external.chromeos_cli.cros_config.CrosConfig'


class VPDUTILSTest(unittest.TestCase):

  def setUp(self):
    self.vpd_util = vpd_utils.VPDUtils('project')

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
    # pylint: disable=protected-access
    invalid_key, _ = self.vpd_util._GetInvalidVPDFields(data, known_key,
                                                        known_key_re)
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
    # pylint: disable=protected-access
    _, invalid_values = self.vpd_util._GetInvalidVPDFields(
        data, {}, known_key_re)
    self.assertEqual(invalid_values, [('key2', '[0-9]'), ('key3', '[0-9]')])

  @mock.patch('logging.info')
  @mock.patch(f'{VPDTOOL}.GetAllData')
  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  def testClearUnknownVPDEntries(self, mock_clear_vpd, mock_invalid_vpd,
                                 mock_get_vpd, mock_info):
    mock_get_vpd.return_value = {
        'ubind_attribute': 1
    }
    mock_invalid_vpd.return_value = ['unknown'], []

    self.vpd_util.ClearUnknownVPDEntries()

    mock_invalid_vpd.assert_called_with({'ubind_attribute': 1},
                                        dict(vpd_data.REQUIRED_RW_DATA,
                                             **vpd_data.KNOWN_RW_DATA),
                                        vpd_data.KNOWN_RW_DATA_RE)
    mock_clear_vpd.assert_called_with(['unknown'])
    mock_info.assert_called_with('Current RW VPDs: %r',
                                 {'ubind_attribute': '<redacted type int>'})

  @mock.patch('logging.info')
  @mock.patch(f'{VPDTOOL}.GetAllData')
  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  def testClearUnknownVPDEntriesAllValid(self, mock_invalid_vpd, mock_get_vpd,
                                         mock_info):
    mock_get_vpd.return_value = {
        'known': 1
    }
    mock_invalid_vpd.return_value = [], []

    self.vpd_util.ClearUnknownVPDEntries()

    mock_info.assert_called_with('No unknown RW VPDs are found. Skip clearing.')

  @mock.patch('logging.info')
  @mock.patch(f'{VPDTOOL}.UpdateData')
  def testClearRWVPDEntries(self, mock_update_vpd, mock_info):
    keys = ['key1', 'key2']
    # pylint: disable=protected-access
    self.vpd_util._ClearRWVPDEntries(keys)

    mock_update_vpd.assert_called_with({
        'key1': None,
        'key2': None
    }, partition=vpd.VPD_READWRITE_PARTITION_NAME)
    mock_info.assert_called_with('Removing VPD entries with key %r', keys)

  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  def testCheckVPDFields(self, mock_invalid_vpd):
    mock_invalid_vpd.return_value = [], []
    self.vpd_util.CheckVPDFields('section', {'req': ''}, {'req': ''},
                                 {'opt': ''}, {'opt_re': ''})

    mock_invalid_vpd.assert_called_with({'req': ''}, {
        'req': '',
        'opt': ''
    }, {'opt_re': ''})

  @mock.patch(f'{VPDUTILS}._GetInvalidVPDFields')
  def testCheckVPDFieldsError(self, mock_invalid_vpd):
    mock_invalid_vpd.return_value = ['key'], []
    self.assertRaises(vpd_utils.VPDError, self.vpd_util.CheckVPDFields, '',
                      {'key': 1}, {}, {}, {})

    mock_invalid_vpd.return_value = [], [('key', '[0-9]')]
    self.assertRaises(vpd_utils.VPDError, self.vpd_util.CheckVPDFields, '',
                      {'key': 1}, {}, {}, {})

  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  @mock.patch(f'{VPDTOOL}.GetAllData')
  def testClearFactoryVPDEntries(self, mock_get_vpd, mock_clear_vpd):
    data = {
        'factory.key': 1,
        'factory.key1': 1,
        'component.key': 1,
        'serials.key': 1
    }
    mock_get_vpd.return_value = data

    self.vpd_util.ClearFactoryVPDEntries()

    mock_clear_vpd.assert_called_with(data.keys())

  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  @mock.patch(f'{VPDTOOL}.GetAllData')
  def testClearFactoryVPDEntriesUnknowDot(self, mock_get_vpd, mock_clear_vpd):
    mock_get_vpd.return_value = {
        'unknow.key': 1
    }

    self.assertRaises(vpd_utils.VPDError, self.vpd_util.ClearFactoryVPDEntries)
    mock_clear_vpd.assert_not_called()

  @mock.patch('logging.info')
  @mock.patch(f'{VPDUTILS}._ClearRWVPDEntries')
  @mock.patch(f'{VPDTOOL}.GetAllData')
  def testClearFactoryVPDEntriesNonDot(self, mock_get_vpd, mock_clear_vpd,
                                       mock_info):
    mock_get_vpd.return_value = {
        'key': 1
    }

    self.vpd_util.ClearFactoryVPDEntries()

    mock_clear_vpd.assert_not_called()
    mock_info.assert_called_with(
        'No factory-related RW VPDs are found. Skip clearing.')

  @mock.patch('logging.info')
  @mock.patch('cros.factory.test.utils.smart_amp_utils.GetSmartAmpInfo')
  def testGetAudioVPDROData(self, mock_get_amp_info, mock_info):
    mock_get_amp_info.return_value = 'speaker_amp', 'sound_card_init_file', [
        'channel1', 'channel2'
    ]
    res = self.vpd_util.GetAudioVPDROData()

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

    self.assertEqual(self.vpd_util.GetAudioVPDROData(), {})
    mock_info.assert_called_with(
        'No smart amplifier found! Skip checking DSM VPD value.')

  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationCodeReturnProject(self, mock_cros_config):
    mock_cros_config.return_value = None
    self.assertEqual(self._GetDeviceName(), 'project')

    mock_cros_config.return_value = {
        'key': 'value'
    }
    self.assertEqual(self._GetDeviceName(), 'project')

    mock_cros_config.assert_called_with('custom_label_reg_code',
                                        validate_schema=False)

  @mock.patch(f'{CROS_CONFIG}.GetCustomLabelTag')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationNotCustomLabel(self, mock_cros_config,
                                                     mock_custom_label):
    mock_cros_config.return_value = {
        'project': {}
    }
    mock_custom_label.return_value = False, ''
    self.assertEqual(self._GetDeviceName(), 'project')

    mock_cros_config.return_value = {
        'project': {
            'key': 'value'
        }
    }
    mock_custom_label.return_value = True, 'label_key'
    self.assertEqual(self._GetDeviceName(), 'project')

    mock_cros_config.return_value = {
        'project': {
            'label_key': ''
        }
    }
    mock_custom_label.return_value = True, 'label_key'
    self.assertEqual(self._GetDeviceName(), 'project')

  @mock.patch(f'{CROS_CONFIG}.GetCustomLabelTag')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  def testGetDeviceNameForRegistrationCustomLabel(self, mock_cros_config,
                                                  mock_custom_label):
    mock_cros_config.return_value = {
        'project': {
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
    mock_cros_config.side_effect = [None, {
        'project': {
            'label_key': 'value'
        }
    }]
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
    return self.vpd_util.GetDeviceNameForRegistrationCode('project')


if __name__ == '__main__':
  unittest.main()
