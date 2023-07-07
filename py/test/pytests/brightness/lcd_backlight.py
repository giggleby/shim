# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a factory test to check the functionality of LCD backlight module.

Description
-----------

This is another version of :doc:`backlight <backlight>`.

The goal is to share code between led, lcd_backlight, keyboard_backlight, and so
on. However, users still use the backlight test.

Test Procedure
--------------

1. Enumerate levels and set brightness to each level.
2. Operators decide pass or fail.

Dependency
----------
- Device API ``cros.factory.device.display.SetBacklightBrightness``.

Examples
--------
An example::

  {
    "pytest_name": "brightness.lcd_backlight",
    "args": {
      "levels": [0.2, 0.4, 0.6, 0.8, 1.0]
    }
  }

"""

from cros.factory.test.i18n import _
from cros.factory.test.i18n import arg_utils as i18n_arg_utils
from cros.factory.test.pytests.brightness import brightness
from cros.factory.test import test_tags
from cros.factory.utils import arg_utils
from cros.factory.utils.arg_utils import Arg


class LCDBacklightTest(brightness.BrightnessTest):
  related_components = (test_tags.TestCategory.LCD, )
  ARGS = arg_utils.MergeArgs(
      brightness.BrightnessTest.ARGS,
      [
          i18n_arg_utils.I18nArg(
              'msg', 'Message HTML',
              default=_('Please check if backlight brightness is changing from '
                        'dark to bright.')),
          Arg('levels', list, 'A sequence of brightness levels.',
              default=None),
          Arg('interval_secs', (int, float),
              'Time for each brightness level in seconds.', default=0.5)
      ])

  def setUp(self):
    if self.args.levels is None:
      self.args.levels = [0.2, 0.4, 0.6, 0.8, 1.0]
    super().setUp()

  def tearDown(self):
    self.dut.display.SetBacklightBrightness(1.0)

  def _SetBrightnessLevel(self, level):
    self.dut.display.SetBacklightBrightness(level)
