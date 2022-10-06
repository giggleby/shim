# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A factory test for HPS (Human Presence Sensor).

Description
-----------
The test is a wrapper of hps-factory.

Test Procedure
--------------
This is an automated test without user interaction.

Dependency
----------
- hps-factory

Examples
--------
To test HPS, add this into test list::

  {
    "pytest_name": "hps"
  }

"""

from cros.factory.device import device_utils
from cros.factory.test import test_case
from cros.factory.test.utils import hps_utils
from cros.factory.utils.arg_utils import Arg

DEFAULT_HPS_FACTORY_TIMEOUT = 3600


class HPSTest(test_case.TestCase):
  ARGS = [
      Arg('hps_factory_path', str, 'The path of the hps-factory binary.',
          default=hps_utils.DEFAULT_HPS_FACTORY_PATH),
      Arg('dev', str,
          ('The path of the HPS device. If not set, use the default value in '
           f'{hps_utils.DEFAULT_HPS_FACTORY_PATH!r}'), default=None),
      Arg('timeout_secs', int, 'The timeout of the test command.',
          default=DEFAULT_HPS_FACTORY_TIMEOUT),
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._hps_device = hps_utils.HPSDevice(
        self._dut, self.args.hps_factory_path, self.args.dev)

  def runTest(self):
    self._hps_device.RunFactoryProcess(timeout_secs=self.args.timeout_secs)
