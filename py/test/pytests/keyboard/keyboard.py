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
from cros.factory.test import evdev_utils
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
    '.keyboard-test-keyup { background-color: green; opacity: 0.5; }\n')

_POWER_KEY_CODE = '116'


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
    Arg('timeout_secs', int, 'Timeout for the test.', default=30),
    Arg('sequential_press', bool, 'Indicate whether keycodes need to be '
        'pressed sequentially or not.', default=False, optional=True),
    Arg('board', str,
        'If presents, in filename, the board name is appended after layout.',
        default=''),
    Arg('skip_power_key', bool, 'Skip power button testing', default=False),
  ]

  def setUp(self):
    self.assertTrue(not (self.args.allow_multi_keys and
                         self.args.sequential_press),
                    'Sequential press requires one key one time.')

    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    self.ui.AppendCSS(_KEYBOARD_TEST_DEFAULT_CSS)

    # Get the keyboard input device.
    keyboard_devices = evdev_utils.GetKeyboardDevices()
    assert len(keyboard_devices) == 1, 'Multiple keyboards detected.'
    self.keyboard_device = keyboard_devices[0]

    # Initialize keyboard layout and bindings
    self.layout = self.GetKeyboardLayout()
    if self.args.board:
      self.layout += '_%s' % self.args.board
    self.bindings, self.key_pressed_count = self.ReadBindings(self.layout)
    if self.args.skip_power_key:
      self.bindings.pop(_POWER_KEY_CODE)

    self.key_order_list = None
    if self.args.sequential_press:
      self.key_order_list = self.ReadKeyOrder(self.layout)

    self.key_down = set()
    # Initialize frontend presentation
    self.template.SetState(_HTML_KEYBOARD)
    self.ui.CallJSFunction('setUpKeyboardTest', self.layout, self.bindings,
                           _ID_IMAGE, self.key_order_list,
                           self.args.allow_multi_keys)

    self.dispatchers = []
    self.keyboard_device.grab()
    StartDaemonThread(target=self.MonitorEvdevEvent)
    StartCountdownTimer(self.args.timeout_secs,
                        lambda: self.ui.CallJSFunction('failTest'),
                        self.ui,
                        _ID_COUNTDOWN_TIMER)

  def tearDown(self):
    """Terminates the running process or we'll have trouble stopping the test.
    """
    for dispatcher in self.dispatchers:
      dispatcher.close()
    self.keyboard_device.ungrab()

  def GetKeyboardLayout(self):
    """Uses the given keyboard layout or auto-detect from VPD."""
    kml_mapping = dict((x.keyboard, x.keyboard_mechanical_layout)
                       for x in regions.REGIONS.itervalues())
    if self.args.layout:
      return self.args.layout
    vpd_layout = CheckOutput(['vpd', '-g', 'keyboard_layout']).strip()
    if vpd_layout:
      return kml_mapping[vpd_layout]
    else:
      return 'ANSI'

  def ReadBindings(self, layout):
    """Reads in key bindings and their associates figure regions."""
    bindings = None
    key_pressed_count = {}
    base = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), 'static')
    bindings_filename = os.path.join(base, layout + '.bindings')
    with open(bindings_filename, 'r') as f:
      bindings = eval(f.read())
    # Convert all integer keys to strings since we can have keycodes like '57_1'
    # in bindings dict.
    for k in bindings.keys():
      if isinstance(k, int):
        bindings[str(k)] = bindings[k]
        del bindings[k]
    for k in bindings:
      # Convert single tuple to list of tuples
      if not isinstance(bindings[k], list):
        bindings[k] = [bindings[k],]
      key_pressed_count[k] = 0
    return bindings, key_pressed_count

  def ReadKeyOrder(self, layout):
    """Reads in key order that must be followed when press key."""
    key_order_list = None
    base = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), 'static')
    key_order_list_filename = os.path.join(base, layout + '.key_order')
    with open(key_order_list_filename, 'r') as f:
      key_order_list = eval(f.read())
    return key_order_list


  def MonitorEvdevEvent(self):
    """Monitors keyboard events from evdev."""
    self.dispatchers.append(
        evdev_utils.InputDeviceDispatcher(
            self.keyboard_device, self.HandleEvent))
    asyncore.loop()

  def HandleEvent(self, event):
    if event.type == evdev.ecodes.EV_KEY:
      if event.value == 1:
        self.MarkKeydown(event.code)
      elif event.value == 0:
        self.MarkKeyup(event.code)

  def _IsKeycodeInBindings(self, keycode):
    """Checks if the keycode is in the bindings dict.

    The keycode in bindings dict can be either <keycode> or
    <keycode>_<sequence_number>.
    """
    return any(re.search(r'%s_?' % keycode, b) for b in self.bindings)

  def MarkKeydown(self, keycode):
    """Calls Javascript to mark the given keycode as keydown."""
    if not self._IsKeycodeInBindings(keycode):
      return True
    key_pressed_count = self.key_pressed_count[str(keycode)]
    keycode_sequence = (
        '%s_%s' % (keycode, key_pressed_count)
        if key_pressed_count else keycode)

    # Fails the test if got two key pressed at the same time.
    if not self.args.allow_multi_keys and len(self.key_down):
      factory.console.error(
          'Got key down event on keycode %r but there is other key pressed: %r',
          keycode_sequence, self.key_down)
      self.ui.CallJSFunction('failTest')
    self.ui.CallJSFunction('markKeydown', keycode_sequence)
    self.key_down.add(keycode_sequence)
    logging.info('Mark key down %s', keycode_sequence)

  def MarkKeyup(self, keycode):
    """Calls Javascript to mark the given keycode as keyup."""
    if not self._IsKeycodeInBindings(keycode):
      return True
    key_pressed_count = self.key_pressed_count[str(keycode)]
    keycode_sequence = (
        '%s_%s' % (keycode, key_pressed_count)
        if key_pressed_count else keycode)

    if keycode_sequence not in self.key_down:
      factory.console.error(
          'Got key up event for keycode %r but did not get key down event',
          keycode_sequence)
      self.ui.CallJSFunction('failTest')
    else:
      self.key_down.remove(keycode_sequence)

    self.key_pressed_count[str(keycode)] += 1
    self.ui.CallJSFunction('markKeyup', keycode_sequence)
    logging.info('Mark key up %s', keycode_sequence)

  def runTest(self):
    self.ui.Run()
