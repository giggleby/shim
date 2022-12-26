# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Lock the Intel descriptor for projects supporting flexible EOM.

Description
-----------
For non-flexible EOM projects, the descriptor is already locked in their first
boot in PVT. As for flexible EOM projects, the descriptor will be locked in
this test.

Test Procedure
--------------
1. Check if the descriptor is locked or not.
2. If yes, end the test.
3. Else write the locked descriptor to the main firmware.

Dependency
----------
- `flashrom` and `ifdtool`

Examples
--------
To lock the descriptor and make the changes to take effect, add this to the
test list::

  {
    "LockIntelDescriptor": {
      "pytest_name": "lock_intel_descriptor"
    },
    "LockIntelDescriptorGroup": {
      "subtests": [
        "LockIntelDescriptor",
        {
          "inherit": "FullRebootStep",
          "run_if": "device.factory.desc_update_need_reboot"
        },
        {
          "inherit": "LockIntelDescriptor",
          "run_if": "device.factory.desc_update_need_reboot",
          "args": {
            "mode": "verify"
          }
        }
      ]
    }
  }

"""

import enum
import logging

from cros.factory.gooftool import crosfw
from cros.factory.test import device_data
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class TestMode(str, enum.Enum):
  lock = 'lock'
  verify = 'verify'

  def __str__(self):
    return self.value


class LockIntelDescriptor(test_case.TestCase):
  _DESC_UPDATE_NEED_REBOOT = device_data.JoinKeys(device_data.KEY_FACTORY,
                                                  'desc_update_need_reboot')

  ARGS = [
      Arg(
          'mode', str, 'Specify the operation to perform. Valid values are:\n'
          '- "lock": Lock the descriptor if it is not locked.\n'
          '- "verify": Verify if the descriptor is locked or not.\n',
          default='lock'),
  ]

  def runTest(self):
    mode = self.args.mode
    valid_modes = [m.value for m in TestMode]
    if mode not in valid_modes:
      raise KeyError(f'Mode {mode} is not valid. '
                     f'Valid modes: {valid_modes}')
    logging.info('Test mode is: %s', mode)
    main_fw = crosfw.LoadIntelMainFirmware()
    fw_image = main_fw.GetFirmwareImage()
    if not fw_image.has_section(crosfw.IntelLayout.DESC.value):
      self.FailTask('Cannot find descriptor from the firmware image layout. '
                    'Is this an Intel project?')

    logging.info('Generate locked descriptor...')
    locked_desc_bin, is_locked = main_fw.GenerateAndCheckLockedDescriptor()
    logging.info('Is descriptor already locked: %r', is_locked)
    device_data.UpdateDeviceData({self._DESC_UPDATE_NEED_REBOOT: False})
    if mode == TestMode.lock:
      if is_locked:
        logging.info('Skip locking the descriptor since it is already locked.')
        return
      logging.info('Lock the descriptor...')
      main_fw.WriteDescriptor(locked_desc_bin)
      device_data.UpdateDeviceData({self._DESC_UPDATE_NEED_REBOOT: True})
    elif mode == TestMode.verify:
      self.assertTrue(is_locked, 'The descriptor is not locked!')
