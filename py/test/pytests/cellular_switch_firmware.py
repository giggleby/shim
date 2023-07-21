# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test for switching the modem's firmware.

Description
-----------
This test will first check current firmware and switch if necessary.

Internal references
^^^^^^^^^^^^^^^^^^^
- b/35518794

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

Dependency
----------
- cros.factory.test.rf.cellular

Examples
--------
An example::

  {
    "pytest_name": "cellular_switch_firmware",
    "args": {
      "target": "Generic UMTS"
    }
  }

"""

from cros.factory.test.i18n import _
from cros.factory.test.rf import cellular
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class CellularFirmwareSwitching(test_case.TestCase):
  related_components = (test_case.TestCategory.WWAN, )
  ARGS = [
      Arg('target', str, 'The firmware name to switch.')]

  def runTest(self):
    self.ui.SetState(
        _('Switching firmware to {target!r}', target=self.args.target))
    cellular.SwitchModemFirmware(self.args.target)
