# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Setup device data from ChromeOS Config.

Description
-----------
This test reads data from ChromeOS Config and sets it up in the device data. If
we want to add more field to add to device data, we can expand the
``fields_to_read`` variable in the test class.

Test Procedure
--------------
This test is an automated test that does not require any operator interaction.

Dependency
----------
The device running this test must have a matching crosid so that ``cros_config``
knows which config record to refer to. Run ``crosid -v`` on DUT for details.
All the fields adding to device data from Cros Config via this test should be
consistent across different SKUs since the SKU might change during factory flow.

Examples
--------
Currently, there are no arguments that need to be set for this test. To run the
test, simply run::

  {
    "pytest_name": "read_device_data_from_cros_config"
  }
"""

import logging

from cros.factory.device import device_utils
from cros.factory.test import device_data
from cros.factory.test import device_data_constants
from cros.factory.test import test_case

from cros.factory.external.chromeos_cli import cros_config as cros_config_module


class ReadDeviceDataFromCrosConfig(test_case.TestCase):

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.cros_config = cros_config_module.CrosConfig(self.dut)

    # NOTE: The fields here should be consistent across SKUs since the SKU might
    # change during factory flow.
    self.fields_to_read = {
        'rmad.enabled': self.cros_config.GetShimlessEnabledStatus,
    }

  def runTest(self):

    for key, func in self.fields_to_read.items():
      logging.info('Updating device data: \"%s\" from ChromeOS Config...', key)
      try:
        device_data_key = f"{device_data_constants.KEY_CROS_CONFIG}.{key}"
        value = func()
        device_data.UpdateDeviceData({device_data_key: value})
        logging.info('Device data: \"%s\" has been updated as %r',
                     device_data_key, value)
      except Exception:
        logging.warning('Failed to update device data: \"%s\"', key)
