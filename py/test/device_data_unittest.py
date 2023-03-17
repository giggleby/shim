#!/usr/bin/env python3
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import unittest

from cros.factory.test import device_data
from cros.factory.test import device_data_constants
from cros.factory.test import state


class ReadDeviceDataFromVPDUnittest(unittest.TestCase):
  def setUp(self):
    self.state_proxy = state.StubFactoryState()

  def testDeriveDeviceDataKey(self):
    rule = ('factory.device_data.*', '')

    expected = {
        'factory.device_data.a': 'a',
        'factory.device_data.a.b': 'a.b', }

    result = {
        # pylint: disable=protected-access
        key: device_data._DeriveDeviceDataKey(rule, key)
        for key in expected}

    self.assertDictEqual(expected, result)

  def testRunTest(self):
    device_data.state.GetInstance = (
        lambda *args, **kwargs: self.state_proxy)

    key_map = {
        'factory.device_data.*': '',
        'abc': 'ABC',
    }

    vpd_data = {
        'factory.device_data.a': 'TRUE',
        'factory.device_data.b.c': 'foo',
        'abc': '123',
        'def': '456',
    }

    device_data.UpdateDeviceDataFromVPD({'ro': key_map}, {'ro': vpd_data})

    self.assertDictEqual(
        {
            'a': True,
            'b': {'c': 'foo'},
            'ABC': '123',
        },
        device_data.GetAllDeviceData())


class VerifyDeviceDataUnittest(unittest.TestCase):
  def testComponentDomain(self):
    device_data.VerifyDeviceData(
        {
            'component.has_aabb': 0,
            'component.has_ccdd': True,
        })

    self.assertRaises(
        ValueError, device_data.VerifyDeviceData,
        {
            'component.has_eeff': 'Y'
        })


class VerifyFeatureDataUnittest(unittest.TestCase):

  def setUp(self) -> None:
    self.state_proxy = state.StubFactoryState()

  def testVerifyExtraFeatureFields(self) -> None:
    fake_data = {
        device_data_constants.NAME_CHASSIS_BRANDED: False,
        device_data_constants.NAME_HW_COMPLIANCE_VERSION: 123,
        'something_else': 123
    }
    self.assertFalse(device_data.VerifyFeatureData(fake_data))

  def testVerifyMissingFeatureFields(self) -> None:
    fake_data = {
        device_data_constants.NAME_CHASSIS_BRANDED: False,
    }
    self.assertFalse(device_data.VerifyFeatureData(fake_data))

  def testVerifyIncorrectChassisType(self) -> None:
    fake_data = {
        device_data_constants.NAME_CHASSIS_BRANDED: 123,
    }
    self.assertFalse(device_data.VerifyFeatureData(fake_data))

  def testVerifyIncorrectHWComplianceType(self) -> None:
    fake_data = {
        device_data_constants.NAME_HW_COMPLIANCE_VERSION: False,
    }
    self.assertFalse(device_data.VerifyFeatureData(fake_data))

  def testSetFeatureDeviceData(self):
    mock_data = {
        device_data_constants.NAME_CHASSIS_BRANDED: False,
        device_data_constants.NAME_HW_COMPLIANCE_VERSION: 123
    }
    device_data.SetFeatureDeviceData(mock_data)
    result = device_data.GetFeatureDeviceData()

    self.assertEqual(
        json.dumps(mock_data, sort_keys=True), json.dumps(
            result, sort_keys=True))


if __name__ == '__main__':
  unittest.main()
