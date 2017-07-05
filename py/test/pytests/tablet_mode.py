# -*- coding: utf-8 -*-
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests that certain conditions are met when in tablet mode.

Currently, the only thing checked is that the lid switch is not triggered.
"""

import asyncore
import evdev
import unittest

import factory_common  # pylint: disable=W0611

from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.countdown_timer import StartCountdownTimer
from cros.factory.test.pytests.tablet_mode_ui import TabletModeUI
from cros.factory.test.utils import evdev_utils
from cros.factory.utils.process_utils import StartDaemonThread


_DEFAULT_TIMEOUT = 30

_ID_COUNTDOWN_TIMER = 'countdown-timer'

_HTML_COUNTDOWN_TIMER = '<div id="%s" class="countdown-timer"></div>' % (
    _ID_COUNTDOWN_TIMER)

_CSS_COUNTDOWN_TIMER = """
.countdown-timer {
  position: absolute;
  bottom: .3em;
  right: .5em;
  font-size: 2em;
}
"""


class TabletModeTest(unittest.TestCase):
  """Tablet mode factory test."""
  ARGS = [
      Arg('timeout_secs', int, 'Timeout value for the test.',
          default=_DEFAULT_TIMEOUT, optional=True),
      Arg('lid_event_id', int, 'Event ID for lid evdev. None for auto probe.',
          default=None, optional=True),
      Arg('tablet_event_id', int,
          'Event ID for tablet evdev. None for auto probe.',
          default=None, optional=True),
      Arg('prompt_flip_notebook', bool,
          'After the test, prompt the operator to flip back into notebook '
          'mode. (This is useful to unset if the next test requires tablet '
          'mode.)',
          default=True, optional=True),
  ]

  def setUp(self):
    self.ui = test_ui.UI()
    self.tablet_mode_ui = TabletModeUI(self.ui,
                                       _HTML_COUNTDOWN_TIMER,
                                       _CSS_COUNTDOWN_TIMER)

    self.tabletModeEnabled = None
    if self.args.lid_event_id:
      self.lid_event_dev = evdev.InputDevice('/dev/input/event%d' %
                                             self.args.lid_event_id)
    else:
      event_devices = evdev_utils.GetLidEventDevices()
      assert len(event_devices) == 1, (
          'Multiple lid event devices or none detected')
      self.lid_event_dev = event_devices[0]

    if self.args.tablet_event_id:
      self.tablet_event_dev = evdev.InputDevice('/dev/input/event%d' %
                                                self.args.tablet_event_id)
    else:
      event_devices = evdev_utils.GetTabletEventDevices()
      assert len(event_devices) < 2, (
          'Multiple tablet event devices detected')
      self.tablet_event_dev = None
      # There might be no evdev for SW_TABLET_MODE
      if len(event_devices) == 1:
        self.tablet_event_dev = event_devices[0]

    self.tablet_mode_ui.AskForTabletMode(self.HandleConfirmTabletMode)

    # Create a thread to monitor evdev events.
    self.lid_dispatcher = None
    StartDaemonThread(target=self.MonitorLidEvdevEvent)
    # It is possible that a single input device can support both of SW_LID and
    # SW_TABLET_MODE therefore we can just use the first thread above to monitor
    # these two EV_SW events. Or we need this second thread.
    self.tablet_dispatcher = None
    if self.tablet_event_dev and self.tablet_event_dev != self.lid_event_dev:
      StartDaemonThread(target=self.MonitorTabletEvdevEvent)

    # Create a thread to run countdown timer.
    StartCountdownTimer(
        self.args.timeout_secs,
        lambda: self.ui.Fail('Lid switch test failed due to timeout.'),
        self.ui,
        _ID_COUNTDOWN_TIMER)

  def MonitorLidEvdevEvent(self):
    """Creates a process to monitor evdev event and checks for lid events."""
    self.lid_dispatcher = evdev_utils.InputDeviceDispatcher(
        self.lid_event_dev, self.HandleSwitchEvent)
    asyncore.loop()

  def MonitorTabletEvdevEvent(self):
    """Creates a process to monitor evdev event and checks for tablet events."""
    self.tablet_dispatcher = evdev_utils.InputDeviceDispatcher(
        self.tablet_event_dev, self.HandleSwitchEvent)
    asyncore.loop()

  def HandleSwitchEvent(self, event):
    if event.type == evdev.ecodes.EV_SW and event.code == evdev.ecodes.SW_LID:
      if event.value == 0:  # LID_OPEN
        self.tablet_mode_ui.FlashFailure()
        self.ui.Fail('Lid switch was triggered unexpectedly')

    if (event.type == evdev.ecodes.EV_SW and
        event.code == evdev.ecodes.SW_TABLET_MODE):
      self.tabletModeEnabled = event.value == 1

  def HandleConfirmTabletMode(self, _):
    if self.tablet_event_dev and not self.tabletModeEnabled:
      self.tablet_mode_ui.FlashFailure()
      self.ui.Fail("Tablet mode switch doesn't be triggered")
      return

    self.tablet_mode_ui.FlashSuccess()
    if self.args.prompt_flip_notebook:
      self.tablet_mode_ui.AskForNotebookMode(self.HandleConfirmNotebookMode)
    else:
      self.ui.Pass()

  def HandleConfirmNotebookMode(self, _):
    if self.tablet_event_dev and self.tabletModeEnabled:
      self.tablet_mode_ui.FlashFailure()
      self.ui.Fail('Tablet mode switch is still triggered')
      return

    self.tablet_mode_ui.FlashSuccess()
    self.ui.Pass()

  def runTest(self):
    self.ui.Run()

  def tearDown(self):
    self.lid_dispatcher.close()
    if self.tablet_dispatcher:
      self.tablet_dispatcher.close()
