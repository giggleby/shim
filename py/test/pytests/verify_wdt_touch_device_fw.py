# -*- coding: utf-8 -*-
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import os
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test.args import Arg

"""Checks touch device firmware and config checksum.

This looks for a touch device configured with the given 'config_file'
name, and verifies that its fw_version and config_csum (read from
/sys) match the expected values.
"""

class VerifyTouchDeviceFWTest(unittest.TestCase):
  ARGS = [
    Arg('sysfs_path', str,
        'The expected sysfs path that udev events should '
        'come from, ex:/sys/bus/i2c/devices/*/)'),
    Arg('fw_version', str, 'Expected firmware version'),
    Arg('config_csum', str, 'Expected config checksum'),
  ]

  def runTest(self):
    # Find the appropriate config file.
    device_path = os.path.dirname(self.args.sysfs_path)

    for atom in ('fw_version', 'config_csum'):
      expected = getattr(self.args, atom)
      actual = open(os.path.join(device_path, atom)).read().strip()
      self.assertEquals(expected, actual,
                        'Mismatched %s (expected %r, found %r)' % (
                            atom, expected, actual))
