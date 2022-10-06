#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.probe.functions import factory_device_data


class FactoryDeviceDataFunctionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    patcher = mock.patch('cros.factory.test.device_data.GetAllDeviceData')
    self._mock_get_all_device_data = patcher.start()
    self.addCleanup(patcher.stop)

    self._mock_get_all_device_data.return_value = {
        'serials': {
            'serial_number': 'aabbcc',
            'mlb_serial_number': 'ddeeff',
        },
    }

    factory_device_data.FactoryDeviceDataFunction.CleanCachedData()

  def testKeyNotFound(self):
    func = factory_device_data.FactoryDeviceDataFunction(
        device_data_keys=['serials.serial_number', 'serials.no_such_key'])
    self.assertEqual(func.Probe(), [])

  def testWrongfulKeyRemapArgumentWithDifferentNumberOfFields(self):
    with self.assertRaises(ValueError):
      unused_inst = factory_device_data.FactoryDeviceDataFunction(
          device_data_keys=['serials.serial_number'],
          probed_result_keys=['output_key1', 'output_key2'])

  def testWrongfulKeyRemapArgumentWithDuplicatedFields(self):
    with self.assertRaises(ValueError):
      unused_inst = factory_device_data.FactoryDeviceDataFunction(
          device_data_keys=[
              'serials.serial_number', 'serials.mlb_serial_number'
          ], probed_result_keys=['output_key1', 'output_key1'])

  def testSucceedWithKeyRemap(self):
    func = factory_device_data.FactoryDeviceDataFunction(
        device_data_keys=['serials.serial_number', 'serials.mlb_serial_number'],
        probed_result_keys=['sn', None])  # only rename `serials.serial_number`
    self.assertEqual(func.Probe(), [{
        'sn': 'aabbcc',
        'serials.mlb_serial_number': 'ddeeff'
    }])

  def testSucceedWithoutKeyRemap(self):
    func = factory_device_data.FactoryDeviceDataFunction(
        device_data_keys=['serials.mlb_serial_number'])
    self.assertEqual(func.Probe(), [{
        'serials.mlb_serial_number': 'ddeeff'
    }])


if __name__ == '__main__':
  unittest.main()
