#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.pytests import read_device_data_from_cros_config


class ReadDeviceDataFromCrosConfigTest(unittest.TestCase):

  def setUp(self):
    self.test = read_device_data_from_cros_config.ReadDeviceDataFromCrosConfig()

  @mock.patch(read_device_data_from_cros_config.__name__ +
              ".device_data.UpdateDeviceData")
  def testRunTest(self, mock_update_device_data):
    mock_cros_func = mock.Mock(return_value='test_return_value')
    self.test.fields_to_read = {
        'test.key': mock_cros_func
    }

    self.test.runTest()

    mock_cros_func.assert_called_once()
    mock_update_device_data.assert_called_with(
        {'cros_config.test.key': 'test_return_value'})


if __name__ == '__main__':
  unittest.main()
