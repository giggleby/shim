#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.probe.functions import feature_management_flags

from cros.factory.external.chromeos_cli.gsctool import FeatureManagementFlags


class FeatureManagementFlagsFunctionTest(unittest.TestCase):

  def setUp(self):
    self._func = feature_management_flags.FeatureManagementFlagsFunction()
    patcher = mock.patch('cros.factory.probe.functions.feature_management_flags'
                         '.FeatureManagementFlagsFunction.IsBoardIDSet')
    self._mock_board_id_set = patcher.start()
    self.addCleanup(self._mock_board_id_set.stop)

  @mock.patch('cros.factory.external.chromeos_cli.gsctool'
              '.GSCTool.GetFeatureManagementFlags')
  def testCr50BoardIDAlreadySet(self, mock_gsc_get_flags):
    self._mock_board_id_set.return_value = True
    testdata = {
        'GSC chassis_branded, hw_compliance_version=1': (
            FeatureManagementFlags(True, 1),
            {
                'is_chassis_branded': '1',
                'hw_compliance_version': '1'
            },
        ),
        'GSC !chassis_branded, hw_compliance_version=0': (
            FeatureManagementFlags(False, 0),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '0'
            },
        ),
        'GSC !chassis_branded, hw_compliance_version=1': (
            FeatureManagementFlags(False, 1),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '1'
            },
        ),
    }
    for sub_test_name, (gsc_management_flags,
                        expect_probed_result) in (testdata.items()):
      with self.subTest(sub_test_name):
        mock_gsc_get_flags.return_value = gsc_management_flags

        results = self._func.Probe()
        self.assertEqual(results, [expect_probed_result])

  @mock.patch('cros.factory.test.device_data.GetDeviceData')
  def testCr50BoardIDNotSet(self, mock_get_device_data):
    self._mock_board_id_set.return_value = False
    testdata = {
        'Device data unset': (
            (None, None),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '0'
            },
        ),
        'Only chassis_branded data set as False': (
            (False, None),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '0'
            },
        ),
        'Only chassis_branded data set as True': (
            (True, None),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '0'
            },
        ),
        'Both device data set, chassis_branded, hw_compliance_version=1': (
            (True, 1),
            {
                'is_chassis_branded': '1',
                'hw_compliance_version': '1'
            },
        ),
        'Both device data set, !chassis_branded, hw_compliance_version=1': (
            (False, 1),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '1'
            },
        ),
        'Both device data set, !chassis_branded, hw_compliance_version=0': (
            (False, 0),
            {
                'is_chassis_branded': '0',
                'hw_compliance_version': '0'
            },
        )
    }
    for sub_test_name, (fm_device_data,
                        expect_probed_result) in (testdata.items()):
      with self.subTest(sub_test_name):
        mock_get_device_data.side_effect = fm_device_data
        results = self._func.Probe()
        self.assertEqual(results, [expect_probed_result])


if __name__ == '__main__':
  unittest.main()
