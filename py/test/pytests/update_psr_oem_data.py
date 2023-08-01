# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to update and verify PSR OEM Data.

Description
-----------
This pytest updates, commits and verifies PSR OEM Data. PSR OEM Data consists of
four NVARs: OEM Name, OEM Make, OEM Model, Country of Manufacturer.

Test Procedure
--------------
This is an automated test without user interaction. There are two ways to update
PSR OEM Data. First is to update from the dictionary `args.oem_data_value`. All
four NVARs have to be in the dictionary and assigned a value. Second is to
update from a config file `/usr/local/factory/py/config/oem_data.cfg`.

Dependency
----------
- `intel-psrtool`


Examples
--------
To update PSR OEM Data, add this to the test list::

  {
    "pytest_name": "update_psr_oem_data",
    "args": {
      "update_from_config": false,
      "oem_data_value": {
        "OEM Name": "Intel",
        "OEM Make": "CCG",
        "OEM Model": "MMS-SMMS",
        "Country of Manufacturer": "TW"
      }
    }
  }

To update PSR OEM Data from /usr/local/factory/py/config/oem_data.cfg, add this
to the test list::

  {
    "pytest_name": "update_psr_oem_data",
    "args": {
      "update_from_config": true
    }
  }
"""

import enum
import logging
import os
import re

from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.chromeos_cli import intel_psrtool


DEFAULT_OEM_DATA_CONFIG_FILE = '/usr/local/factory/py/config/oem_data.cfg'


class PSROEMData(str, enum.Enum):
  OEM_NAME = "OEM Name"
  OEM_MAKE = "OEM Make"
  OEM_MODEL = "OEM Model"
  COUNTRY_OF_MANUFACTURER = "Country of Manufacturer"

  def __str__(self):
    return self.value


class UpdatePSROEMData(test_case.TestCase):
  """Factory Test for updating PSR OEM data"""

  ARGS = [
      Arg('oem_data_value', dict, 'The value for each NVAR to update.',
          default={}),
      Arg('update_from_config', bool,
          f'To update from config at {DEFAULT_OEM_DATA_CONFIG_FILE}',
          default=True),
      Arg('oem_data_config_path', str, 'The file to update PSR OEM Data with',
          default=DEFAULT_OEM_DATA_CONFIG_FILE),
  ]

  def setUp(self):
    self._intel_psr_tool = intel_psrtool.IntelPSRTool()
    self._oem_data_config_path = self.args.oem_data_config_path
    self.CheckUpdateSource(self.args.update_from_config)

  def runTest(self):
    try:
      self.VerifyOEMData(self.args.update_from_config)
      logging.info(
          'PSR OEM data has been set correctly. Pass the test directly.')
      return
    except intel_psrtool.IntelPSRToolError:
      logging.info('Try updating PSR OEM data.')

    self.UpdateOEMData(self.args.update_from_config)
    self._intel_psr_tool.CommitOEMData()
    self.VerifyOEMData(self.args.update_from_config)

  def CheckUpdateSource(self, update_from_config):
    if update_from_config:
      self.assertTrue(
          os.path.exists(self._oem_data_config_path),
          f'Config file not found at {self._oem_data_config_path}')
    else:
      for name in PSROEMData:
        self.assertIn(name, self.args.oem_data_value)

  def UpdateOEMData(self, update_from_config):
    if update_from_config:
      self._intel_psr_tool.UpdateOEMDataFromConfig(self._oem_data_config_path)
    else:
      for name in PSROEMData:
        self._intel_psr_tool.WriteNVAR(name, self.args.oem_data_value[name])

  def VerifyOEMData(self, update_from_config):
    if update_from_config:
      self._intel_psr_tool.VerifyOEMData(self._oem_data_config_path)
    else:
      stdout = self._intel_psr_tool.DisplayPSRLog()
      for name in PSROEMData:
        data_pattern = fr'{name}:\s*([\w\s]+)\n'
        match_data = re.search(data_pattern, stdout)
        if not match_data:
          raise intel_psrtool.IntelPSRToolRegexError(name, data_pattern, stdout)
        if match_data.group(1) != self.args.oem_data_value[name]:
          raise intel_psrtool.IntelPSRToolError(
              f'{name} not matched. Current={match_data.group(1)};'
              f'Expected={self.args.oem_data_value[name]}')
