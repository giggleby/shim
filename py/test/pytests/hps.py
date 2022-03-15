# Copyright 2022 The Chromium OS Authors. All rights reserved.
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
    "pytest_name": "hps",
    "args": {
      "dev": "/dev/i2c-15"
    }
  }

The dev argument may be different for different models.
"""

import os

from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils


DEFAULT_HPS_FACTORY_PATH = os.path.join(os.sep, 'usr', 'bin', 'hps-factory')
IOTOOLS_PATH = 'iotools'


class HPSTest(test_case.TestCase):
  ARGS = [
      Arg('hps_factory_path', str, 'The path of the hps-factory binary.',
          default=DEFAULT_HPS_FACTORY_PATH),
      Arg('dev', str, 'The path of the HPS device.',
          default='/dev/i2c-hps-controller'),
      Arg('timeout_secs', int, 'The timeout of the test command.', default=10),
      Arg('power_cycle', bool, 'Power-cycle the HPS.', default=True),
  ]

  def PowerCycle(self):
    """Should be equivalent to the below command.

    iotools mmio_write32 0xfd6a0ae0 \
      $(iotools btr $(iotools mmio_read32 0xfd6a0ae0) 0) && \
    iotools mmio_write32 0xfd6a0ae0 \
      $(iotools bts $(iotools mmio_read32 0xfd6a0ae0) 0)
    """
    index = '0xfd6a0ae0'

    output = process_utils.CheckOutput([IOTOOLS_PATH, 'mmio_read32', index],
                                       log=True).strip()
    output = process_utils.CheckOutput([IOTOOLS_PATH, 'btr', output, '0'],
                                       log=True).strip()
    process = process_utils.Spawn([IOTOOLS_PATH, 'mmio_write32', index, output],
                                  log=True, call=True)

    if process.returncode == 0:
      output = process_utils.CheckOutput([IOTOOLS_PATH, 'mmio_read32', index],
                                         log=True).strip()
      output = process_utils.CheckOutput([IOTOOLS_PATH, 'bts', output, '0'],
                                         log=True).strip()
      process_utils.Spawn([IOTOOLS_PATH, 'mmio_write32', index, output],
                          log=True, call=True)

    self.Sleep(1)

  def runTest(self):
    if self.args.power_cycle:
      self.PowerCycle()
    process = process_utils.Spawn(
        [self.args.hps_factory_path, '--dev', self.args.dev, 'factory'],
        timeout=self.args.timeout_secs, log=True, call=True)
    if process.returncode != 0:
      self.FailTask('Test failed.')
