# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A factory test to test the functionality of touchpad.

dargs:
  touchpad_event_id: Touchpad input event id. (default: None)
  timeout_secs: Timeout for the test. (default: 30 seconds)
"""

import asyncore
import evdev
import logging
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.countdown_timer import StartCountdownTimer
from cros.factory.test.ui_templates import OneSection
from cros.factory.test.utils import evdev_utils
from cros.factory.utils import process_utils


_ID_CONTAINER = 'touchpad-test-container'
_ID_COUNTDOWN_TIMER = 'touchpad-test-timer'

# The layout contains one div for touchpad touch and scroll,
# one table for left/right click, and one div for countdown timer.
_HTML_TOUCHPAD = """
<div id="%s" style="position: relative; width: 100%%; height: 60%%;"></div>
<table style="width: 100%%; height: 30%%;">
  <tbody>
    <tr>
      <td style="width: 65%%;">
        <table id="quadrant_table" style="width: 100%%;">
          <tbody>
            <tr>
              <td>
                <div id="quadrant2" class="touchpad-test-sector-untested" align="center">
                  Click Left-Top Corner
                  <div id="quadrant2_count" align="center">0/3</div>
                </div>
              </td>
              <td>
                <div id="quadrant1" class="touchpad-test-sector-untested" align="center">
                  Click Right-Top Corner
                  <div id="quadrant1_count" align="center">0/3</div>
                </div>
              </td>
            </tr>
            <tr>
              <td>
                <div id="quadrant3" class="touchpad-test-sector-untested" align="center">
                  Click Left-Bottom Corner
                  <div id="quadrant3_count" align="center">0/3</div>
                </div>
              </td>
              <td>
                <div id="quadrant4" class="touchpad-test-sector-untested" align="center">
                  Click Right-Bottom Corner
                  <div id="quadrant4_count" align="center">0/3</div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </td>
      <td>
        <table style="width: 100%%;">
          <tbody>
            <tr>
              <td align="right" valign="center">
                <div id="left-circle" class="touchpad-test-circle-untested"></div>
              </td>
              <td align="left" valign="center">
                <div id="left-text-cell"></div>
              </td>
              <td align="right" valign="center">
                <div id="right-circle" class="touchpad-test-circle-untested"></div>
              </td>
              <td align="left" valign="center">
                <div id="right-text-cell"></div>
              </td>
            </tr>
          </tbody>
        </table>
      </td>
    </tr>
  </tbody>
</table>
<div id="%s"></div>
""" % (_ID_CONTAINER, _ID_COUNTDOWN_TIMER)

# The styles for each item on ui.
# For sectors (moving and scrolling event):
#   touchpad-test-sector-untested: sector not touched.
#   touchpad-test-sector-tested: sector touched.
# For circles (click event):
#   touchpad-test-circle-untested: the style to show before click.
#   touchpad-test-circle-down: click down.
#   touchpad-test-circle-tested: release click.
_TOUCHPAD_TEST_DEFAULT_CSS = """
    #touchpad-test-timer { font-size: 2em; }
    .touchpad-test-sector-untested {
      background-color: gray;
      height: 100%; }
    .touchpad-test-sector-tested {
      background-color: green; height: 100%;
      opacity: 0.5; }
    .touchpad-test-circle-untested {
      border: 3px solid gray;
      border-radius: 50%;
      width: 20px; height: 20px;
      box-sizing: border-box; }
    .touchpad-test-circle-down {
      border: 3px solid yellow;
      border-radius: 50%;
      width: 20px; height: 20px;
      box-sizing: border-box; }
    .touchpad-test-circle-tested {
      border: 3px solid green;
      border-radius: 50%;
      width: 20px; height: 20px;
      box-sizing: border-box; }
"""


class UpDown(object):
  """The class to represent Up or Down event for KEY input.

  The value is the same as value from evtest KEY event, where "0" is up and "1"
  is down.
  """

  def __init__(self):
    pass
  Up = 0
  Down = 1


class Quadrant(object):
  """The class is to update quadrant information.

  Update quadrant information according to x_ratio and y_ratio:

    Quadrant 1 is Right-Top Corner
    Quadrant 2 is Left-Top Corner
    Quadrant 3 is Left-Bottom Corner
    Quadrant 4 is Right-Bottom Corner
  """

  def __init__(self):
    self.quadrant = 0

  def UpdateQuadrant(self, x_ratio, y_ratio):
    if x_ratio >= 0.5 and y_ratio < 0.5:
      self.quadrant = 1
    elif x_ratio < 0.5 and y_ratio < 0.5:
      self.quadrant = 2
    elif x_ratio < 0.5 and y_ratio >= 0.5:
      self.quadrant = 3
    elif x_ratio >= 0.5 and y_ratio >= 0.5:
      self.quadrant = 4


class MoveEvent(object):
  """The class to store touchpad move event."""

  def __init__(self):
    self.x = None
    self.y = None
    self.scroll = None
    self.sync = None

  def Clear(self):
    self.x = self.y = self.scroll = self.sync = None


class ClickEvent(object):
  """The class to store touchpad click event.

  Double tap event is also stored to catch double click event.
  """

  def __init__(self):
    self.double_tap = None
    self.btn_left = None
    self.btn_right = None

  def ClearBtnLeft(self):
    self.btn_left = None

  def ClearBtnRight(self):
    self.btn_right = None


class TouchpadTest(unittest.TestCase):
  """Tests the function of touchpad.

  The test checks the following function:
    1. Detect finger on every sector of touchpad.
    2. Two finger scrolling.
    3. Single click.
    4. Either double click or right click.

  Properties:
    self.ui: test ui.
    self.template: ui template handling html layout.
    self.x_max: max grid value of horizontal movement.
    self.y_max: max grid valud of vertical movement.
    self.touchpad_device_name: This can be probed from evdev.
    self.move_event: the detected move event. The event will be drew
        and reset upon sync event.
    self.click_event: the detected click event. The event will be drew for each
        detected btn_left or btn_right up and down. btn_left or btn_right will
        get reset upon drawing. Note that double_tap will not get reset
        upon drawing since we have to keep double_tap value for the case that
        two fingers stay on the touchpad.
    self.touchpad_has_right_btn: for touchpad with right button, we don't want
        to process double click. We will only process right_btn and left_btn.
    self.quadrant: This represents the current quadrant of mouse.
  """
  ARGS = [
      Arg(
          'touchpad_event_id', int,
          'Touchpad input event id. The test will probe'
          ' for event id if it is not given.', default=None, optional=True),
      Arg('timeout_secs', int, 'Timeout for the test.', default=20),
      Arg('number_to_click', int, 'Target number to click.', default=10),
      Arg(
          'number_to_quadrant', int,
          'Target number to click for each quadrant.', default=3),
      Arg('x_segments', int, 'Number of X axis segments to test.', default=5),
      Arg('y_segments', int, 'Number of Y axis segments to test.', default=5),
      Arg('skip_sectors', list,
          'What sectors are intended to skip test. ex: There would be a case '
          'of that touch surface is not a rectangle.',
          default=[]),
      Arg('reverse_x_value', bool,
          'Whether to reverse reported value of x axis.', default=False),
      Arg('reverse_y_value', bool,
          'Whether to reverse reported value of y axis.', default=False)]

  def setUp(self):
    # Initialize frontend presentation
    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    self.ui.AppendCSS(_TOUCHPAD_TEST_DEFAULT_CSS)
    self.template.SetState(_HTML_TOUCHPAD)
    self.ui.CallJSFunction(
        'setupTouchpadTest', _ID_CONTAINER, self.args.x_segments,
        self.args.y_segments, self.args.number_to_click,
        self.args.number_to_quadrant)

    # Initialize properties
    self.x_max = None
    self.y_max = None
    self.touchpad_device_name = None
    self.move_event = MoveEvent()
    self.click_event = ClickEvent()
    self.touchpad_has_right_btn = False
    self.quadrant = Quadrant()
    if self.args.touchpad_event_id is None:
      touchpad_devices = evdev_utils.GetTouchpadDevices()
      assert len(touchpad_devices) == 1, 'Multiple touchpad devices detected.'
      self.touchpad_device = touchpad_devices[0]
    else:
      self.touchpad_device = evdev.InputDevice(
          '/dev/input/event%d' % self.args.touchpad_event_id)
    self.dispatcher = None
    self.MarkSectorsSkipTest(self.args.skip_sectors)

    logging.info('start monitor daemon thread')
    self.touchpad_device.grab()
    process_utils.StartDaemonThread(target=self.MonitorEvdevEvent)
    logging.info('start countdown timer daemon thread')
    StartCountdownTimer(self.args.timeout_secs,
                        lambda: self.ui.CallJSFunction('failTest'),
                        self.ui,
                        _ID_COUNTDOWN_TIMER)

  def ProbeEventSource(self):
    """Probes for touch event path.

    Touch device has type EV_ABS, and there is a code ABS_MT_POSITION_X in
    the first element of one of its values.
    It also has type EV_KEY, in which there is a code BTN_LEFT in its values.
    """
    for dev in map(evdev.InputDevice, evdev.list_devices()):
      event_type_code = dev.capabilities()
      logging.info('capabilities, %s', event_type_code)
      if not (evdev.ecodes.EV_KEY in event_type_code and
              evdev.ecodes.BTN_LEFT in event_type_code[evdev.ecodes.EV_KEY]):
        continue
      if (evdev.ecodes.EV_ABS in event_type_code):
        codes = [x[0] for x in event_type_code[evdev.ecodes.EV_ABS]]
        if evdev.ecodes.ABS_MT_POSITION_X in codes:
          logging.info('Probed device path: %s; name %s', dev.fn, dev.name)
          return dev.fn

  def tearDown(self):
    """Clean-up stuff.

    Terminates the running process or we'll have trouble stopping the
    test.

    Enable the touchpad at X to enable touchpad function in test ui.
    """
    self.dispatcher.close()
    self.touchpad_device.ungrab()

  def MonitorEvdevEvent(self):
    """Starts to monitor evdev events."""
    self.dispatcher = evdev_utils.InputDeviceDispatcher(
        self.touchpad_device, self.HandleEvent)
    self.GetSpec()
    asyncore.loop()

  def GetSpec(self):
    """Gets device name, btn_right, x_max and y_max."""
    self.touchpad_device_name = self.touchpad_device.name
    if (evdev.ecodes.BTN_RIGHT in
        self.touchpad_device.capabilities()[evdev.ecodes.EV_KEY]):
      self.touchpad_has_right_btn = True
    ev_abs_dict = dict(self.touchpad_device.capabilities()[evdev.ecodes.EV_ABS])
    self.x_max = ev_abs_dict[evdev.ecodes.ABS_MT_POSITION_X].max
    self.y_max = ev_abs_dict[evdev.ecodes.ABS_MT_POSITION_Y].max
    logging.info('get device %s spec right_btn = %s, x_max = %s, y_max = %s',
                 self.touchpad_device_name, self.touchpad_has_right_btn,
                 self.x_max, self.y_max)

  def HandleEvent(self, event):
    """Handles evdev events."""
    self.ProcessMoveEvent(event)
    self.ProcessClickEvent(event)

  def ProcessLeftAndRightClickEvent(self):
    """Draws left click event or right click event."""
    self.DrawLeftClick(self.click_event.btn_left)
    self.click_event.ClearBtnLeft()
    self.DrawRightClick(self.click_event.btn_right)
    self.click_event.ClearBtnRight()

  def ProcessSingleAndDoubleClickEvent(self):
    """Draws single click event or double click event."""
    if self.click_event.double_tap == UpDown.Down:
      self.DrawDoubleClick(self.click_event.btn_left)
      self.click_event.ClearBtnLeft()
    else:
      self.DrawSingleClick(self.click_event.btn_left)
      self.click_event.ClearBtnLeft()

  def ProcessClickEvent(self, event):
    """Processes a click event.

    Args:
      event: the event to process.
    """
    if event.code == evdev.ecodes.BTN_TOOL_DOUBLETAP:
      self.click_event.double_tap = event.value
    elif event.code == evdev.ecodes.BTN_LEFT:
      self.click_event.btn_left = event.value
    elif event.code == evdev.ecodes.BTN_RIGHT:
      self.click_event.btn_right = event.value

    if self.touchpad_has_right_btn:
      self.ProcessLeftAndRightClickEvent()
    else:
      self.ProcessSingleAndDoubleClickEvent()

  def ProcessMoveEvent(self, event):
    """Processes a move event.

    Args:
      event: the event to process.
    """
    if event.code == evdev.ecodes.ABS_MT_POSITION_X:
      if self.args.reverse_x_value:
        self.move_event.x = self.x_max - event.value
      else:
        self.move_event.x = event.value
    elif event.code == evdev.ecodes.ABS_MT_POSITION_Y:
      if self.args.reverse_y_value:
        self.move_event.y = self.y_max - event.value
      else:
        self.move_event.y = event.value
    elif event.code == evdev.ecodes.ABS_MT_SLOT:
      self.move_event.scroll = event.value
    elif event.code == evdev.ecodes.SYN_REPORT:
      self.move_event.sync = True

    if self.move_event.sync:
      self.DrawMoveEvent()
      self.move_event.Clear()

  def DrawMoveEvent(self):
    """Marks a scroll sector as tested or a move sector as tested."""
    if self.move_event.x:
      x_ratio = float(self.move_event.x) / float(self.x_max)
    if self.move_event.y:
      y_ratio = float(self.move_event.y) / float(self.y_max)

    if self.move_event.x and self.move_event.y:
      self.quadrant.UpdateQuadrant(x_ratio, y_ratio)

    if self.move_event.scroll and self.move_event.y:
      self.MarkScrollSectorTested(y_ratio)
    elif self.move_event.x and self.move_event.y:
      self.MarkSectorTested(x_ratio, y_ratio)

  def DrawSingleClick(self, up_down):
    """Draws single click event by calling javascript function.

    Args:
      up_down: UpDown.Up or Updown.Down or None.
    """
    if up_down == UpDown.Up:
      logging.info('mark single click up')
      self.ui.CallJSFunction('markSingleClickUp', self.quadrant.quadrant)
    elif up_down == UpDown.Down:
      logging.info('mark single click down')
      self.ui.CallJSFunction('markSingleClickDown', self.quadrant.quadrant)

  def DrawDoubleClick(self, up_down):
    """Draws double click event by calling javascript function.

    Args:
      up_down: UpDown.Up or Updown.Down or None.
    """
    if up_down == UpDown.Up:
      logging.info('mark double click up')
      self.ui.CallJSFunction('markDoubleClickUp')
    elif up_down == UpDown.Down:
      logging.info('mark double click down')
      self.ui.CallJSFunction('markDoubleClickDown')

  def DrawLeftClick(self, up_down):
    """Draw left click event. For now we reuse DrawSingleClick.

    Args:
      up_down: UpDown.Up or Updown.Down or None.
    """
    self.DrawSingleClick(up_down)

  def DrawRightClick(self, up_down):
    """Draw right click event. For now we reuse DrawDoubleClick.

    Args:
      up_down: UpDown.Up or Updown.Down or None.
    """
    self.DrawDoubleClick(up_down)

  def MarkScrollSectorTested(self, y_ratio):
    """Marks a scroll sector tested.

    Gets the scroll sector from y_ratio then calls Javascript to mark the sector
    as tested.
    """
    y_segment = int(y_ratio * self.args.y_segments)
    logging.info('mark %d scroll segment tested', y_segment)
    self.ui.CallJSFunction('markScrollSectorTested', y_segment)

  def MarkSectorTested(self, x_ratio, y_ratio):
    """Marks a touch sector tested.

    Gets the segment from x_ratio and y_ratio then calls Javascript to
    mark the sector as tested.
    """
    x_segment = int(x_ratio * self.args.x_segments)
    y_segment = int(y_ratio * self.args.y_segments)
    logging.info('mark x-%d y-%d sector tested', x_segment, y_segment)
    self.ui.CallJSFunction('markSectorTested', x_segment, y_segment)

  def MarkSectorsSkipTest(self, skip_sectors):
    for x, y in skip_sectors:
      self.ui.CallJSFunction('markSectorTested', x, y)

  def runTest(self):
    self.ui.Run()
