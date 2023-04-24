# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A factory test to check the feature compliance version.

Description
-----------
This test checks the feature compliance and sets the version to device data.

Test Procedure
--------------
This test will be run automatically.

Dependency
----------
- cros.factory.hwid.v3 for compliance version checker.
- branded_chassis pytest should be run prior to this test.
- cros.factory.test.device_data for getting/setting feature flags.

Examples
--------
To check the feature compliance version, please add this in test list::

  {
    "pytest_name": "feature_compliance_version"
  }
"""

import logging
import os

from cros.factory.hwid.v3.database import Database
from cros.factory.hwid.v3 import feature_compliance
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test import device_data
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class FeatureComplianceVersionTest(test_case.TestCase):
  """Factory test for verifying feature compliance version."""

  # This test is depending on HWID string so we need to pass these flags here.
  ARGS = [
      Arg('hwid_need_vpd', bool, 'Run the `vpd` command to get the vpd data.',
          default=True),
      Arg('rma_mode', bool,
          'Enable rma_mode, do not check for deprecated components.',
          default=False),
  ]

  def setUp(self) -> None:
    self._project = hwid_utils.ProbeProject().upper()
    self._hwid_dir = hwid_utils.GetDefaultDataPath()
    self._hw_db_path = os.path.join(self._hwid_dir, self._project)

    # We will need to reset feature compliance version device data every time
    # we run this test, so that it will not be affected by previous results.
    device_data.UpdateDeviceData(
        {device_data.KEY_FM_HW_COMPLIANCE_VERSION: None})

  def GetHWIDIdentity(self):
    """Gets the HWID identity with HWID cmdline helpers.

    Returns:
      `hwid.v3.Identity` instance.
    """

    database = Database.LoadFile(self._hw_db_path)
    vpd = hwid_utils.GetVPDData(run_vpd=self.args.hwid_need_vpd)
    device_info = hwid_utils.GetDeviceInfo()

    identity = hwid_utils.GenerateHWID(database, hwid_utils.GetProbedResults(),
                                       device_info, vpd, self.args.rma_mode,
                                       with_configless_fields=False,
                                       brand_code=hwid_utils.GetBrandCode())
    logging.info(identity)
    return identity

  def runTest(self) -> None:

    branded_chassis_device_data = device_data.GetDeviceData(
        device_data.KEY_FM_CHASSIS_BRANDED)
    if branded_chassis_device_data is None:
      self.FailTask('Chassis branded not verified, '
                    'please run branded_chassis pytest first.')

    logging.info('Chassis branded verified, '
                 'Generating HWID for feature compliance version.')

    identity = self.GetHWIDIdentity()
    checker = feature_compliance.LoadChecker(self._hwid_dir, self._project)
    checker_hw_compliance_version = checker.CheckFeatureComplianceVersion(
        identity)
    logging.info('HW compliance version acquired from checker: %d',
                 checker_hw_compliance_version)

    # Valid pairs are (False, 0), (False, n), (True, n).
    if branded_chassis_device_data:
      self.assertGreater(checker_hw_compliance_version,
                         feature_compliance.FEATURE_INCOMPLIANT_VERSION)
    else:
      self.assertGreaterEqual(checker_hw_compliance_version,
                              feature_compliance.FEATURE_INCOMPLIANT_VERSION)

    device_data.SetHWComplianceVersionData(checker_hw_compliance_version)
