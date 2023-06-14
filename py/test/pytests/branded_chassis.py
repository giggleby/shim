# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A test to check if chassis is branded.

Description
-----------
This pytest reads the data from device_data and ask the operator to verify if
there the A panel of the chassis has "SOMETHING" on it. Upon verifying by the
operator, the Pytest will store the information.

Test Procedure
--------------
The operator should visually inspect if the chassis has "SOMETHING" on the
A panel.

Dependency
----------
- Display
- Chassis

Examples
--------
To verify the the chassis is branded, add this to the test list::

  {
    "pytest_name": "branded_chassis",
  }

or

  "BrandedChassis"

"""
import logging
from typing import Union

from cros.factory.test import device_data
from cros.factory.test import device_data_constants
from cros.factory.test.i18n import _
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.chromeos_cli.gsctool import GSCTool


def IsInconsistentResponse(existing_data: Union[None, bool], response: bool):
  """Verify if the response is inconsistent with existing data."""
  return (existing_data is not None) and (existing_data != response)


class VerifyBrandedChassis(test_case.TestCase):
  """Factory Test for verifying Branded Chassis"""

  # This test should support RMA.
  ARGS = [Arg('rma_mode', bool, 'Enable rma_mode.', default=False)]

  def setUp(self) -> None:
    self.feature_management = device_data.GetFeatureDeviceData()

  def ShowPrompt(self) -> None:
    self.ui.SetTitle(_('Verify branded chassis'))
    self.ui.SetState(
        _('Please verify if the chassis has X label on it.'
          'If Yes, press "Y". If not, press "N"'))

  def runTest(self):
    branded_chassis_data = self.feature_management.get(
        device_data_constants.NAME_CHASSIS_BRANDED, None)

    if (self.args.rma_mode and GSCTool().IsGSCFeatureManagementFlagsLocked()):
      branded_chassis_data = GSCTool().GetFeatureManagementFlags(
      ).is_chassis_branded
      logging.info('Chassis branded already set in GSC as %s.',
                   branded_chassis_data)

    self.ShowPrompt()
    key = self.ui.WaitKeysOnce(['Y', 'N'], 20)

    operator_response = (key == 'Y')
    if operator_response:
      self.ui.SetState(_('The DUT is a branded chassis'))
    else:
      self.ui.SetState(_('The DUT is NOT branded chassis'))

    if IsInconsistentResponse(branded_chassis_data, operator_response):
      self.FailTask(_('Data is inconsistent, please double check!'))

    device_data.SetBrandedChassisData(operator_response)

    session.console.info(
        f'The feature device data is: {device_data.GetFeatureDeviceData()}')
    self.ui.WaitKeysOnce([test_ui.ENTER_KEY])
