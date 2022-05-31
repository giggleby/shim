# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests touchscreen or stylus by drawing in any order or in spiral pattern.

Description
-----------
In this test, screen area is segmented into `x_segments` x `y_segments` blocks.
If argument `spiral_mode` is True, the operator has to swipe the blocks in
clockwise spiral pattern. Otherwise the operator has to touch all the blocks in
arbitrary order.

In `spiral_mode`, the pattern is:

1. Starting from upper-left block, move to rightmost block.
2. Then move down, left, up, to draw a outer rectangular circle.
3. Move to the inner upper-left block (1, 1), repeat 1-2.
4. Until the center block is reached.

The index of block (x, y) is defined as::

  index =  x + y * x_segments (number of blocks in x-axis).

For, example, a 3x3 grid::

  0 1 2
  3 4 5
  6 7 8

The clockwise spiral drawing sequence is: 0, 1, 2, 5, 8, 7, 6, 3, 4.

There are two modes available: end-to-end mode and evdev mode.

- End-to-end mode uses Chrome touch event API.
- Evdev mode uses Linux evdev.

Test logic is in touchscreen.js.

Test Procedure
--------------
1. Once the test started, it would be set to fullscreen and shows
   `x_segments` x `y_segments` grey blocks.
2. Draw these blocks green by touching them (or move your stylus to make it
   hovering on a block in hover mode) in specified order. Test will pass after
   all blocks being green.
3. If there is any problem with the touch device, press Escape to abort and
   mark this test failed.
4. If `timeout_secs` is set and the test couldn't be passed in `timeout_secs`
   seconds, the test will fail automatically.

Dependency
----------
- End-to-end mode is based on Chrome touch event API.
- Non end-to-end mode is based on Linux evdev.

Examples
--------
To test touchscreen with 30x20 blocks, add this in test list::

  {
    "pytest_name": "touchscreen",
    "args": {
      "y_segments": 30,
      "x_segments": 20
    }
  }

To test touchscreen in end-to-end mode and cancel the time limit::

  {
    "pytest_name": "touchscreen",
    "args": {
      "e2e_mode": true,
      "timeout_secs": null
    }
  }

To test touchscreen without spiral order restriction::

  {
    "pytest_name": "touchscreen",
    "args": {
      "spiral_mode": false
    }
  }

To test stylus in hover mode::

  {
    "pytest_name": "touchscreen",
    "args": {
      "stylus": true,
      "hover_mode": true
    }
  }

Trouble Shooting
----------------
If you find the spiral test keeps failing, here are some tips:

1. Use end-to-end mode to see if it helps.
2. Use the tool `evtest` to check touch events reported by driver.

If seeing unexpected touch events in `evtest`, here are some thoughts:

1. Check if the motherboard and operator are properly grounded.
2. Remove all external connections to the DUT (including power adaptor, ethernet
   cable, usb hub).
3. Check if there are noises coming from the grounding line. Maybe move the DUT
   out of the manufacturing line to see if it helps.
4. Flash touchscreen firmware to a different version. Maybe it's too sensitive.
"""

from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.test.utils import evdev_utils
from cros.factory.test.utils import touch_monitor
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.type_utils import Enum

# pylint: disable=no-name-in-module
from cros.factory.external.evdev import ecodes


class StylusMonitor(touch_monitor.SingleTouchMonitor):
  """Stylus monitor."""

  def __init__(self, device, frontend_proxy, code):
    """Initialize.

    Args:
      device: evdev.InputDevice
      frontend_proxy: Proxy to frontend test.
      code: Which key to monitor: BTN_TOUCH (for touching) or BTN_TOOL_PEN
        (for hovering).
    """
    super().__init__(device)
    self._frontend_proxy = frontend_proxy
    self._code = code
    # A boolean flag indicating if BTN_TOUCH or BTN_TOOL_PEN is on.
    self._flag = self._state.keys[code]

  def _EmitEvent(self, receiver):
    event_state = self.GetState()
    self._frontend_proxy.GoofyTouchListener(receiver, event_state.x,
                                            event_state.y)

  def OnKey(self, key_event_code):
    """Called by Handler after state of a key changed."""
    if key_event_code == self._code:
      self._flag = not self._flag
      if self._flag:
        self._EmitEvent('touchStartHandler')
      else:
        self._EmitEvent('touchEndHandler')

  def OnMove(self):
    """Called by Handler after X or Y coordinate changes."""
    if self._flag:
      self._EmitEvent('touchMoveHandler')


class TouchscreenMonitor(touch_monitor.MultiTouchMonitor):
  """Touchscreen monitor."""

  def __init__(self, device, frontend_proxy):
    """Initialize.

    Args:
      device: evdev.InputDevice
      frontend_proxy: test_ui.JavaScriptProxy to frontend test
    """
    super().__init__(device)
    self._frontend_proxy = frontend_proxy

  def _EmitEvent(self, receiver, slot_id):
    slot = self.GetState().slots[slot_id]
    self._frontend_proxy.GoofyTouchListener(receiver, slot.x, slot.y)

  def OnNew(self, slot_id):
    """Called by Handler after a new contact comes."""
    self._EmitEvent('touchStartHandler', slot_id)

  def OnMove(self, slot_id):
    """Called by Handler after a contact moved."""
    self._EmitEvent('touchMoveHandler', slot_id)

  def OnLeave(self, slot_id):
    """Called by Handler after a contact leaves."""
    self._EmitEvent('touchEndHandler', slot_id)


class TouchscreenTest(test_case.TestCase):
  """Tests touchscreen by drawing blocks in sequence.

  Properties:
    self._device: evdev.InputDevice
    self._dispatcher: evdev_utils.InputDeviceDispatcher
    self._monitor: StylusMonitor or TouchscreenMonitor
  """
  ARGS = [
      Arg('x_segments', int, 'Number of segments in x-axis.', default=5),
      Arg('y_segments', int, 'Number of segments in y-axis.', default=5),
      Arg('retries', int, 'Number of retries (for spiral_mode).', default=5),
      Arg(
          'demo_interval_ms', int,
          'Interval (ms) to show drawing pattern (for spiral mode). '
          '<= 0 means no demo.', default=150),
      Arg('stylus', bool, 'Testing stylus or not.', default=False),
      Arg('e2e_mode', bool, 'Perform end-to-end test or not (for touchscreen).',
          default=False),
      Arg('spiral_mode', bool,
          'Do blocks need to be drawn in spiral order or not.', default=True),
      Arg('device_filter', (int, str), 'Evdev input event id or name.',
          default=None),
      Arg('hover_mode', bool, 'Test hovering or touching (for stylus).',
          default=False),
      Arg('timeout_secs', (int, type(None)),
          'Timeout for the test. None for no time limit.', default=20),
      Arg(
          'angle_compensation', Enum([0, 90, 180, 270]),
          'Specify a degree to compensate the orientation difference between '
          'panel and system in counter-clockwise direction. It is used when '
          'panel scanout is different from default system orientation, i.e., '
          'a angle difference between the instruction line displayed on '
          'screen and the position read from evdev.', default=0)
  ]

  def setUp(self):
    if self.args.stylus:
      self._device = evdev_utils.FindDevice(self.args.device_filter,
                                            evdev_utils.IsStylusDevice)
    else:
      if self.args.e2e_mode:
        self._device = None
      else:
        self._device = evdev_utils.FindDevice(self.args.device_filter,
                                              evdev_utils.IsTouchscreenDevice)
    self._dispatcher = None
    self._monitor = None
    self._state = state.GetInstance()
    self._SetInternalDisplayRotation(self.args.angle_compensation)
    # Waits the screen rotates, then starts the test.
    self.Sleep(1)

    self._frontend_proxy = self.ui.InitJSTestObject(
        'TouchscreenTest', self.args.x_segments, self.args.y_segments,
        self.args.retries, self.args.demo_interval_ms, self.args.e2e_mode,
        self.args.spiral_mode)

  def tearDown(self):
    if self._dispatcher is not None:
      self._dispatcher.close()
    if self._device is not None:
      self._device.ungrab()
    self._SetInternalDisplayRotation(-1)

  def runTest(self):
    if self.args.timeout_secs:
      self.ui.StartCountdownTimer(self.args.timeout_secs,
                                  self._frontend_proxy.FailTest)

    if self._device is not None:
      self._device = evdev_utils.DeviceReopen(self._device)
      self._device.grab()
      if self.args.stylus:
        self._monitor = StylusMonitor(
            self._device, self._frontend_proxy,
            ecodes.BTN_TOOL_PEN if self.args.hover_mode else ecodes.BTN_TOUCH)
      else:
        self._monitor = TouchscreenMonitor(self._device, self._frontend_proxy)
      self._dispatcher = evdev_utils.InputDeviceDispatcher(
          self._device, self._monitor.Handler)
      self._dispatcher.StartDaemon()

    self.ui.BindKey(test_ui.ESCAPE_KEY,
                    lambda unused_event: self._frontend_proxy.FailTest())
    self.WaitTaskEnd()

  def _SetInternalDisplayRotation(self, degree):
    # degree should be one of [0, 90, 180, 270, -1], where -1 means auto-rotate
    display_id = self._GetInternalDisplayInfo()['id']
    self._state.DeviceSetDisplayProperties(display_id, {"rotation": degree})

  def _GetInternalDisplayInfo(self):
    display_info = self._state.DeviceGetDisplayInfo()
    display_info = [info for info in display_info if info['isInternal']]
    if len(display_info) != 1:
      self.fail('Failed to get internal display.')
    return display_info[0]
