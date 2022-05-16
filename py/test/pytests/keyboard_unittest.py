#!/usr/bin/env python3
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.pytests import keyboard


class FakeArgs:

  def __init__(self):
    self.repeat_times = {}
    self.skip_keycodes = [3]
    self.vivaldi_keyboard = False
    self.has_numpad = False
    self.allow_multi_keys = False
    self.sequential_press = False
    self.multi_keys_delay = 0
    self.layout = None
    self.strict_sequential_press = False
    self.board = ''
    self.device_filter = None
    self.skip_power_key = False
    self.skip_keycodes = []
    self.replacement_keymap = {}
    self.detect_long_press = None

class KeyboardUnitTest(unittest.TestCase):

  def MockFunction(self, function_name, return_value=None):
    if return_value is None:
      patcher = mock.patch(function_name)
    else:
      patcher = mock.patch(function_name, return_value=return_value)
    patcher.start()
    self.addCleanup(patcher.stop)

  def setUp(self):
    self.test = keyboard.KeyboardTest()
    self.test.args = FakeArgs()
    self.test.event_loop = mock.Mock()
    self.MockFunction('cros.factory.test.utils.evdev_utils.FindDevice')
    self.MockFunction(
        'cros.factory.test.utils.evdev_utils.InputDeviceDispatcher')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction('cros.factory.test.test_case.TestCase.ui')
    self.MockFunction('cros.factory.testlog.testlog.UpdateParam')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.PassTask')
    all_keys = [1, 2, 3, 4]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.ReadBindings',
                      {key: {}
                       for key in all_keys})

  def PressKey(self, keycode):
    self.test.OnKeydown(keycode)
    self.test.OnKeyup(keycode)

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  @mock.patch(f'{keyboard.__name__}.KeyboardTest.ReadKeyOrder')
  def testStrictSequentialPress(self, mock_key_order, mock_pass):
    self.test.args.repeat_times = {
        'default': 2,
        '1': 1,
        '3': 1,
        '4': 3
    }
    self.test.args.strict_sequential_press = True
    mock_key_order.return_value = [1, 2, 3]
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(1)
    self.PressKey(2)
    self.PressKey(4)
    self.PressKey(2)
    self.PressKey(3)
    self.PressKey(4)
    mock_pass.assert_called_once()

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.ReadKeyOrder')
  def testStrictSequentialPressWrongOrder(self, mock_key_order):
    self.test.args.repeat_times = {
        '1': 1,
        '3': 2
    }
    self.test.args.strict_sequential_press = True
    mock_key_order.return_value = [1, 3, 2]
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(1)
    self.PressKey(3)
    with self.assertRaisesRegex(Exception, 'Expect keycode 3 but get 2'):
      self.PressKey(2)

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  @mock.patch(f'{keyboard.__name__}.KeyboardTest.ReadKeyOrder')
  def testSequentialPress(self, mock_key_order, mock_pass):
    self.test.args.sequential_press = True
    mock_key_order.return_value = [1, 2, 3]
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(3)
    self.PressKey(2)
    self.PressKey(1)
    mock_pass.assert_not_called()
    self.PressKey(2)
    self.PressKey(3)
    mock_pass.assert_called_once()

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  def testSkipKeycodes(self, mock_pass):
    self.test.args.skip_keycodes = [1, 2, 3]
    self.test.setUp()

    self.PressKey(4)
    mock_pass.assert_called_once()

if __name__ == '__main__':
  unittest.main()
