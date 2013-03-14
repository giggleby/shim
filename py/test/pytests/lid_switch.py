# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a factory test to check the functionality of the lid switch.

dargs:
  timeout: the test runs at most #seconds (default: 30 seconds).
  ok_audio_path: (optional) an audio file's path to notify an operator to open
      the lid.
  audio_volume: (optional) volume to play the ok audio. Default 100%.
"""

import asyncore
import evdev
import unittest

from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.countdown_timer import StartCountdownTimer
from cros.factory.test.ui_templates import OneSection
from cros.factory.test.utils import StartDaemonThread

_DEFAULT_TIMEOUT = 10

_MSG_PROMPT_CLOSE = test_ui.MakeLabel(
    'Close then open the lid', u'关上接着打开上盖', 'lid-test-info')
_MSG_PROMPT_OPEN = test_ui.MakeLabel(
    'Open the lid', u'请打开上盖', 'lid-test-info')

_ID_PROMPT = 'lid-test-prompt'
_ID_COUNTDOWN_TIMER = 'lid-test-timer'
_HTML_LID_SWITCH = ('<div id="%s"></div>\n'
                    '<div id="%s" class="lid-test-info"></div>\n' %
                    (_ID_PROMPT, _ID_COUNTDOWN_TIMER))

_LID_SWITCH_TEST_DEFAULT_CSS = '.lid-test-info { font-size: 2em; }'


class InputDeviceDispatcher(asyncore.file_dispatcher):
  def __init__(self, device, event_handler):
    self.device = device
    self.event_handler = event_handler
    asyncore.file_dispatcher.__init__(self, device)

  def recv(self, ign=None): # pylint:disable=W0613
    return self.device.read()

  def handle_read(self):
    for event in self.recv():
      self.event_handler(event)

class LidSwitchTest(unittest.TestCase):
  ARGS = [
    Arg('timeout_secs', int, 'Timeout value for the test.',
        default=_DEFAULT_TIMEOUT),
    Arg('ok_audio_path', (str, unicode),
        'Path to the OK audio file which is played after detecting lid close'
        'signal. Defaults to play ok_*.ogg in /sounds.',
        default=None, optional=True),
    Arg('audio_volume', int, 'Audio volume to use when playing OK audio file.',
        default=100),
    Arg('event_id', int, 'Event ID for evdev. None for auto probe.',
        default=None, optional=True)
  ]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    if self.args.event_id:
      self.event_dev = evdev.InputDevice('/dev/input/event%d' %
                                         self.args.event_id)
    else:
      self.event_dev = self.ProbeLidEventSource()
    self.ui.AppendCSS(_LID_SWITCH_TEST_DEFAULT_CSS)
    self.template.SetState(_HTML_LID_SWITCH)
    self.ui.SetHTML(_MSG_PROMPT_CLOSE, id=_ID_PROMPT)
    self.dispatcher = None
    # Create a thread to monitor evdev events.
    StartDaemonThread(target=self.MonitorEvdevEvent)
    # Create a thread to run countdown timer.
    StartCountdownTimer(
        self.args.timeout_secs,
        lambda: self.ui.Fail('Lid switch test failed due to timeout.'),
        self.ui,
        _ID_COUNTDOWN_TIMER)

  def tearDown(self):
    self.TerminateLoop()

  def ProbeLidEventSource(self):
    """Probe for lid event source."""
    for dev in map(evdev.InputDevice, evdev.list_devices()):
      for event_type, event_codes in dev.capabilities().iteritems():
        if (event_type == evdev.ecodes.EV_SW and
            evdev.ecodes.SW_LID in event_codes):
          return dev

  def HandleEvent(self, event):
    if event.type == evdev.ecodes.EV_SW and event.code == evdev.ecodes.SW_LID:
      if event.value == 1: # LID_CLOSED
        self.ui.SetHTML(_MSG_PROMPT_OPEN, id=_ID_PROMPT)
        self.PlayOkAudio()
      elif event.value == 0: # LID_OPEN
        self.ui.Pass()

  def MonitorEvdevEvent(self):
    """Creates a process to monitor evdev event and checks for lid events."""
    self.dispatcher = InputDeviceDispatcher(self.event_dev, self.HandleEvent)
    asyncore.loop()

  def TerminateLoop(self):
    self.dispatcher.close()

  def PlayOkAudio(self):
    if self.args.ok_audio_path:
      self.ui.PlayAudioFile(self.args.ok_audio_path)
    else:
      self.ui.PlayAudioFile('ok_%s.ogg' % self.ui.GetUILanguage())

  def runTest(self):
    self.ui.Run()
