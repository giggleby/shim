# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests keyboard pin connectivity in SMT factory test.

Description
-----------
Unlike keyboard test, it only expects a key sequence where keys are the keyboard
scan lines' row-column crossing points. It also can trigger a SMT testing
fixture to send out signals to simulate key presses on the key sequence.

Test Procedure
--------------
- A ``keycode_sequence`` is required for the expected key sequence.
- If ``bft_fixture`` is set the test calls the fixture to simulate key press
  events.
- Listen to keyboard events, the received keycode must match the expected
  sequence.

Dependency
----------
Depends on 'evdev' module to monitor key presses.

Examples
--------
Here is an example::

  {
    "pytest_name": "keyboard_smt",
    "args": {
      "keycode_sequence": [1, 61, 19, 68, 27, 22, 42, 12, 67, 56, 57, 106, 29],
      "timeout_secs": 10,
      "bft_fixture": { ... }
    }
  }
"""

from cros.factory.test.fixture import bft_fixture
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.test.utils import evdev_utils
from cros.factory.utils.arg_utils import Arg

from cros.factory.external.py_lib import evdev


class KeyboardSMTTest(test_case.TestCase):
  """Tests each keyboard scan lines are connected.

  It triggers a keyboard scan module by sending 0xC1 to fixture via RS-232.
  The keyboard scan module will send a sequence of keycodes. This test checks
  if the upcoming keyup events match the expected keycode sequence.
  """
  ARGS = [
      Arg('device_filter', (int, str),
          'Keyboard input event id or evdev name.',
          default=None),
      Arg('timeout_secs', int, 'Timeout for the test.', default=30),
      Arg('keycode_sequence', list,
          'Expected keycode sequence generated by a keyboard scan module in '
          'the fixture.'),
      Arg('bft_fixture', dict, bft_fixture.TEST_ARG_HELP, default=None),
      Arg('debug', bool,
          'True to disable timeout and never fail. Used to observe keystrokes.',
          default=False)
  ]

  def setUp(self):
    self.debug = self.args.debug
    self.expected_sequence = self.args.keycode_sequence
    self.received_sequence = []

    self.fixture = None
    if self.args.bft_fixture:
      self.fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)

    # Get the keyboard input device.
    self.event_dev = evdev_utils.FindDevice(self.args.device_filter,
                                            evdev_utils.IsKeyboardDevice)

    # Monitor keyboard event within specified time period.
    self.event_dev.grab()
    self.dispatcher = evdev_utils.InputDeviceDispatcher(
        self.event_dev, self.event_loop.CatchException(self.HandleEvdevEvent))
    self.dispatcher.StartDaemon()
    self.UpdateUI()

  def tearDown(self):
    self.dispatcher.Close()
    self.event_dev.ungrab()

  def UpdateUI(self):
    expected_sequence = self.expected_sequence
    if not self.debug:
      expected_sequence = expected_sequence[len(self.received_sequence):]

    self.ui.CallJSFunction('setMatchedSequence', self.received_sequence)
    self.ui.CallJSFunction('setExpectedSequence', expected_sequence)

  def HandleEvdevEvent(self, event):
    """Handles evdev event.

    Args:
      event: evdev event.
    """
    if event.type == evdev.ecodes.EV_KEY and event.value == 0:
      self.HandleKey(event.code)

  def HandleKey(self, key):
    """Handles keyup event."""
    if self.debug:
      session.console.info('keycode: %s', key)
      self.received_sequence.append(key)
    else:
      self.received_sequence.append(key)
      if key != self.expected_sequence[len(self.received_sequence) - 1]:
        self.FailTask(
            f'Keycode sequence mismatches. expected: '
            f'{self.expected_sequence!r}, actual: {self.received_sequence!r}.')
      if self.received_sequence == self.expected_sequence:
        self.PassTask()
    self.UpdateUI()

  def runTest(self):
    if not self.debug:
      self.ui.StartFailingCountdownTimer(self.args.timeout_secs)
    if self.fixture:
      self.fixture.SimulateKeystrokes()
    self.WaitTaskEnd()
