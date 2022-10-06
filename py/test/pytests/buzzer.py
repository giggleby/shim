# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a buzzer test.

Description
-----------
This test checks the functionality of the buzzer of a ChromeOS device.

Test Procedure
--------------
1. Press space and DUT will start buzzing.
2. Press the number of buzz heard to pass the test or press 'r' to play again.

Dependency
----------
None.

Examples
--------
To test buzzer with default parameters on puff, add this in test list::

  {
    "pytest_name": "buzzer"
    "args": {
      "gpio_index": "382"
    }
  }

If you want to change the mute duration between two beeps and the duration of a
beep and test buzzer on brask::

  {
    "pytest_name": "buzzer",
    "args": {
      "gpio_index": "166"
      "beep_duration_secs": 0.8,
      "mute_duration_secs": 1.5
    }
  }
"""

import datetime
import random
import time

from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg


_MAX_BEEP_TIMES = 5


class BuzzerTest(test_case.TestCase):
  """Tests buzzer."""
  ARGS = [
      # Common arguments
      Arg('beep_duration_secs', float, 'How long for one beep', 0.3),
      Arg('mute_duration_secs', float, 'Mute duration between two beeps', 0.5),
      Arg('gpio_index', str, 'Index for gpio file depending on the board'),
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self._pass_digit = random.randint(1, _MAX_BEEP_TIMES)
    self.ui.ToggleTemplateClass('font-large', True)

  def runTest(self):
    max_total_duration = _MAX_BEEP_TIMES * (
        self.args.beep_duration_secs + self.args.mute_duration_secs)

    self.ui.SetState(_('How many beeps do you hear? <br>Press space to start.'))
    self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    self.ui.SetState(
        _('How many beeps do you hear? <br>'
          'Press the number you hear to pass the test.<br>'
          "Press 'r' to play again."))

    while True:
      start_time = time.time()
      for unused_i in range(self._pass_digit):
        self.BeepOnce(self.args.beep_duration_secs)
        self.Sleep(self.args.mute_duration_secs)
      # Try to make the test always run for about same duration, to avoid
      # cheating by looking at when the buttons appear.
      self.Sleep(max_total_duration - (time.time() - start_time))

      all_keys = [str(num + 1) for num in range(_MAX_BEEP_TIMES)] + ['R']
      key = self.ui.WaitKeysOnce(all_keys)
      if key != 'R':
        self.assertEqual(self._pass_digit, int(key), 'Wrong number to press.')
        return

  def BeepOnce(self, beep_duration):
    t1 = datetime.datetime.now()
    beep_sec = datetime.timedelta(seconds=beep_duration)
    index = self.args.gpio_index

    self.dut.WriteSpecialFile('/sys/class/gpio/export', index)
    self.dut.WriteSpecialFile(f'/sys/class/gpio/gpio{index}/direction', 'out')

    i = 0
    while t1 + beep_sec > datetime.datetime.now():
      self.dut.WriteSpecialFile(f'/sys/class/gpio/gpio{index}/value', str(i))
      i = i ^ 1
      self.Sleep(0.0001)  # A louder buzzing frequency

    self.dut.WriteSpecialFile('/sys/class/gpio/unexport', index)
