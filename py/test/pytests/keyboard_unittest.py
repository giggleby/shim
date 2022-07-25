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
    self.fn_keycodes = []
    self.key_order = []
    self.has_power_key = True
    self.key_combinations = []


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
    self.MockFunction('cros.factory.test.test_case.TestCase.ui')
    self.MockFunction('cros.factory.testlog.testlog.UpdateParam')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.PassTask')
    all_keys = [[1], [2, 3], [4]]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetLayoutKeycodes',
                      all_keys)

  def PressKey(self, keycode):
    self.PressKeys([keycode])

  def PressKeys(self, keycodes):
    for keycode in keycodes:
      self.test.OnKeydown(keycode)
    for keycode in keycodes:
      self.test.OnKeyup(keycode)

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  def testPressAllKeys(self, mock_pass):
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeycodesInFirstRow',
                      [])
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(3)
    self.PressKey(1)
    self.PressKey(4)
    mock_pass.assert_not_called()
    self.PressKey(2)
    mock_pass.assert_called_once()

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  def testStrictSequentialPress(self, mock_pass):
    self.test.args.repeat_times = {
        'default': 2,
        '1': 1,
        '3': 1,
        '4': 3
    }
    self.test.args.strict_sequential_press = True
    self.test.args.key_order = [1, 2, 3]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeycodesInFirstRow',
                      [])
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(1)
    self.PressKey(2)
    self.PressKey(4)
    self.PressKey(2)
    self.PressKey(3)
    mock_pass.assert_not_called()
    self.PressKey(4)
    mock_pass.assert_called_once()

  def testStrictSequentialPressWrongOrder(self):
    self.test.args.repeat_times = {
        '1': 1,
        '3': 2
    }
    self.test.args.strict_sequential_press = True
    self.test.args.key_order = [1, 3, 2]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeycodesInFirstRow',
                      [])
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(1)
    self.PressKey(3)
    with self.assertRaisesRegex(Exception, 'Expect keycode 3 but get 2'):
      self.PressKey(2)

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  def testSequentialPress(self, mock_pass):
    self.test.args.sequential_press = True
    self.test.args.key_order = [1, 2, 3]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeycodesInFirstRow',
                      [])
    self.test.setUp()

    self.PressKey(4)
    self.PressKey(3)
    self.PressKey(2)
    self.PressKey(1)
    self.PressKey(2)
    mock_pass.assert_not_called()
    self.PressKey(3)
    mock_pass.assert_called_once()

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  def testKeyCombinations(self, mock_pass):
    self.test.args.key_combinations = [[3], [1, 2]]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeycodesInFirstRow',
                      [])
    self.test.setUp()

    self.PressKey(3)
    self.PressKey(1)
    self.PressKey(2)
    mock_pass.assert_not_called()
    self.PressKeys([2, 1])
    mock_pass.assert_called_once()

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.PassTask')
  def testSkipKeycodes(self, mock_pass):
    self.test.args.skip_keycodes = [1, 2, 3]
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeyboardLayout')
    self.MockFunction(f'{keyboard.__name__}.KeyboardTest.GetKeycodesInFirstRow',
                      [])
    self.test.setUp()

    self.PressKey(4)
    mock_pass.assert_called_once()

  def testLayoutAndBoard(self):
    self.test.args.layout = 'layout'
    self.test.args.board = 'board'

    self.assertEqual('layout_board', self.test.GetKeyboardLayout())

  def testLayoutArg(self):
    self.test.args.layout = 'layout'

    self.assertEqual('layout', self.test.GetKeyboardLayout())

  @mock.patch('cros.factory.utils.process_utils.CheckOutput')
  def testLayoutVPD(self, mock_output):
    # The mapping is defined in platform2/regions/regions.py
    for param, expect in {
        'us': 'ANSI',
        'jp': 'JIS',
        'es': 'ISO'
    }.items():
      with self.subTest(param=param):
        mock_output.return_value = param
        self.assertEqual(expect, self.test.GetKeyboardLayout())
        mock_output.assert_called_with(['vpd', '-g', 'region'])
        mock_output.reset_mock()

  @mock.patch(f'{keyboard.__name__}.KeyboardTest.GetVivaldiKeycodes')
  def testVivaldiKeyboard(self, mock_vivaldi_keycodes):
    mock_vivaldi_keycodes.return_value = [61, 62]
    self.test.args.vivaldi_keyboard = True
    self.test.args.fn_keycodes = [63]  # should be ignored

    self.assertEqual(self.test.GetKeycodesInFirstRow(), [1, 61, 62, 116])

  def testFnKeycodes(self):
    self.test.args.fn_keycodes = [61, 62]

    self.assertEqual(self.test.GetKeycodesInFirstRow(), [1, 61, 62, 116])

  def testFnKeycodesNotHasPowerKey(self):
    self.test.args.has_power_key = False
    self.test.args.fn_keycodes = [61, 62]

    self.assertEqual(self.test.GetKeycodesInFirstRow(), [1, 61, 62, 142])

  def testDefaultNotHasPowerKey(self):
    self.test.args.has_power_key = False

    self.assertEqual(self.test.GetKeycodesInFirstRow(),
                     [1, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 142])

  def testDefaultHasPowerKey(self):
    self.assertEqual(self.test.GetKeycodesInFirstRow(),
                     [1, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 116])


if __name__ == '__main__':
  unittest.main()
