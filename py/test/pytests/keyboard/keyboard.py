# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests keyboard functionality."""

from __future__ import print_function

import asyncore
import evdev
import logging
import os
import re
import unittest

import factory_common   # pylint: disable=W0611
from cros.factory.l10n import regions
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.countdown_timer import StartCountdownTimer
from cros.factory.test.ui_templates import OneSection
from cros.factory.test.utils import StartDaemonThread
from cros.factory.utils.process_utils import CheckOutput


_RE_EVTEST_EVENT = re.compile(
    r'^Event: time .*?, type .*? \((.*?)\), code (.*?) \(.*?\), value (.*?)$')

_ID_IMAGE = 'keyboard-test-image'
_ID_COUNTDOWN_TIMER = 'keyboard-test-timer'
_HTML_KEYBOARD = (
    '<div id="%s" style="position: relative"></div>\n<div id="%s"></div>\n' %
        (_ID_IMAGE, _ID_COUNTDOWN_TIMER))

_KEYBOARD_TEST_DEFAULT_CSS = (
    '#keyboard-test-timer { font-size: 2em; }\n'
    '.keyboard-test-key-untested { display: none; }\n'
    '.keyboard-test-keydown { background-color: yellow; opacity: 0.5; }\n'
    '.keyboard-test-keyup { background-color: green; opacity: 0.5; }\n'
    '.keyboard-test-key-skip { background-color: gray; opacity: 0.5; }\n')

_POWER_KEY_CODE = 116


class InputDeviceDispatcher(asyncore.file_dispatcher):
  """Extends asyncore.file_dispatcher to read input device."""
  def __init__(self, device, event_handler):
    self.device = device
    self.event_handler = event_handler
    asyncore.file_dispatcher.__init__(self, device)

  def recv(self, ign=None): # pylint:disable=W0613
    return self.device.read()

  def handle_read(self):
    for event in self.recv():
      self.event_handler(event)

  def writable(self):
    return False

class KeyboardTest(unittest.TestCase):
  """Tests if all the keys on a keyboard are functioning. The test checks for
  keydown and keyup events for each key, following certain order if required,
  and passes if both events of all keys are received.
  """
  ARGS = [
    Arg('allow_multi_keys', bool, 'Allow multiple keys pressed simultaneously. '
        '(Less strictly checking with shorter cycle time)', default=False),
    Arg('layout', (str, unicode),
        ('Use specified layout other than derived from VPD. '
         'If None, the layout from the VPD is used.'),
        default=None, optional=True),
    Arg('keyboard_device_name', (str, unicode), 'Device name of keyboard.',
        default='AT Translated Set 2 keyboard'),
    Arg('timeout_secs', int, 'Timeout for the test.', default=30),
    Arg('sequential_press', bool, 'Indicate whether keycodes need to be '
        'pressed sequentially or not.', default=False, optional=True),
    Arg('board', str,
        'If presents, in filename, the board name is appended after layout. ',
        default=''),
    Arg('skip_power_key', bool, 'Skip power button testing', default=False),
    Arg('skip_keycodes', list, 'Key codes to skip', default=[])
  ]

  def setUp(self):
    self.assertTrue(not (self.args.allow_multi_keys and
                         self.args.sequential_press),
                    'Sequential press requires one key one time.')

    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    self.ui.AppendCSS(_KEYBOARD_TEST_DEFAULT_CSS)
    self.env = {
        'DISPLAY': ':0',
        'XAUTHORITY': '/home/chronos/.Xauthority'
    }

    # Initialize keyboard layout and bindings
    self.layout = self.GetKeyboardLayout()
    if self.args.board:
      self.layout += '_%s' % self.args.board
    self.bindings = self.ReadBindings(self.layout)

    keycodes_to_skip_strings = map(str, self.args.skip_keycodes)
    if self.args.skip_power_key:
      keycodes_to_skip_strings.append(str(_POWER_KEY_CODE))

    self.key_order_list = None
    if self.args.sequential_press:
      self.key_order_list = self.ReadKeyOrder(self.layout)

    self.key_down = set()
    # Initialize frontend presentation
    self.template.SetState(_HTML_KEYBOARD)
    self.ui.CallJSFunction('setUpKeyboardTest', self.layout, self.bindings,
                           keycodes_to_skip_strings, _ID_IMAGE,
                           self.key_order_list, self.args.allow_multi_keys)

    self.dispatchers = []
    self.EnableXKeyboard(False)
    StartDaemonThread(target=self.MonitorEvdevEvent)
    StartCountdownTimer(self.args.timeout_secs,
                        lambda: self.ui.CallJSFunction('failTest'),
                        self.ui,
                        _ID_COUNTDOWN_TIMER)

  def tearDown(self):
    """Terminates the running process or we'll have trouble stopping the
    test.
    """
    for dispatcher in self.dispatchers:
      dispatcher.close()
    self.EnableXKeyboard(True)

  def GetKeyboardLayout(self):
    """Uses the given keyboard layout or auto-detect from VPD."""
    kml_mapping = dict((x.keyboard, x.keyboard_mechanical_layout)
                       for x in regions.REGIONS.itervalues())
    if self.args.layout:
      return self.args.layout
    # Use the primary keyboard_layout for testing.
    vpd_layout = CheckOutput(
        ['vpd', '-g', 'keyboard_layout']).strip().partition(',')[0]
    if vpd_layout:
      return kml_mapping[vpd_layout]
    else:
      return 'ANSI'

  def ReadBindings(self, layout):
    """Reads in key bindings and their associates figure regions."""
    bindings = None
    base = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), 'static')
    bindings_filename = os.path.join(base, layout + '.bindings')
    with open(bindings_filename, 'r') as f:
      bindings = eval(f.read())
    for k in bindings:
      # Convert single tuple to list of tuples
      if not isinstance(bindings[k], list):
        bindings[k] = [bindings[k],]
    return bindings

  def ReadKeyOrder(self, layout):
    """Reads in key order that must be followed when press key."""
    key_order_list = None
    base = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), 'static')
    key_order_list_filename = os.path.join(base, layout + '.key_order')
    with open(key_order_list_filename, 'r') as f:
      key_order_list = eval(f.read())
    return key_order_list

  def EnableXKeyboard(self, enable):
    """Enables/Disables keyboard at the X server."""
    device = self.args.keyboard_device_name
    if device:
      CheckOutput(['xinput', 'set-prop', device,
                   'Device Enabled', '1' if enable else '0'],
                  env=self.env)

  def MonitorEvdevEvent(self):
    """Monitors keyboard events from evdev."""
    for dev in map(evdev.InputDevice, evdev.list_devices()):
      if evdev.ecodes.EV_KEY in dev.capabilities().iterkeys():
        self.dispatchers.append(InputDeviceDispatcher(dev, self.HandleEvent))
    asyncore.loop()

  def HandleEvent(self, event):
    if event.type == evdev.ecodes.EV_KEY:
      if event.value == 1:
        self.MarkKeydown(event.code)
      elif event.value == 0:
        self.MarkKeyup(event.code)

  def MarkKeydown(self, keycode):
    """Calls Javascript to mark the given keycode as keydown."""
    if not keycode in self.bindings:
      return True
    # Fails the test if got two key pressed at the same time.
    if not self.args.allow_multi_keys and len(self.key_down):
      factory.console.error(
          'Got key down event on keycode %r but there is other key pressed: %r',
          keycode, self.key_down)
      self.ui.CallJSFunction('failTest')
    self.ui.CallJSFunction('markKeydown', keycode)
    self.key_down.add(keycode)
    logging.info('Mark key down %d', keycode)

  def MarkKeyup(self, keycode):
    """Calls Javascript to mark the given keycode as keyup."""
    if not keycode in self.bindings:
      return True
    if keycode not in self.key_down:
      factory.console.error(
          'Got key up event for keycode %r but did not get key down event',
          keycode)
      self.ui.CallJSFunction('failTest')
    else:
      self.key_down.remove(keycode)
    self.ui.CallJSFunction('markKeyup', keycode)

  def runTest(self):
    self.ui.Run()
