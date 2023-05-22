#!/usr/bin/env python3
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.test import state
from cros.factory.test.test_lists import manager
from cros.factory.test.test_lists import test_list as test_list_module
from cros.factory.utils import type_utils


KEY_ENGINEERING_MODE = 'engineering_mode'


class FactoryTestListTest(unittest.TestCase):
  def testGetNextSibling(self):
    test_list = manager.BuildTestListForUnittest(
        test_list_config={
            'tests': [
                {'id': 'G',
                 'subtests': [
                     {'id': 'G',
                      'subtests': [
                          {'id': 'a', 'pytest_name': 't_GGa'},
                          {'id': 'b', 'pytest_name': 't_GGb'},
                      ]},
                     {'id': 'b', 'pytest_name': 't_Gb'},
                 ]}
            ]
        })
    test = test_list.LookupPath('G.G')
    self.assertEqual(test.GetNextSibling(), test_list.LookupPath('G.b'))
    test = test_list.LookupPath('G.G.a')
    self.assertEqual(test.GetNextSibling(), test_list.LookupPath('G.G.b'))
    test = test_list.LookupPath('G.G.b')
    self.assertIsNone(test.GetNextSibling())

  def testResolveRequireRun(self):
    self.assertEqual(
        'e.f',
        test_list_module.FactoryTestList.ResolveRequireRun('a.b.c.d', 'e.f'))
    self.assertEqual(
        'a.b.c.e.f',
        test_list_module.FactoryTestList.ResolveRequireRun('a.b.c.d', '.e.f'))
    self.assertEqual(
        'a.b.e.f',
        test_list_module.FactoryTestList.ResolveRequireRun('a.b.c.d', '..e.f'))
    self.assertEqual(
        'a.e.f',
        test_list_module.FactoryTestList.ResolveRequireRun('a.b.c.d', '...e.f'))

  def testDetectCircularDependency(self):
    _FAKE_TEST_LIST_CONFIG = {
        'definitions': {
            'A': {
                'subtests': [
                    'AA',
                    {
                        'id':
                            'AB',
                        'subtests': [{
                            'id': 'ABA',
                            'pytest_name': 't_aba'
                        }, {
                            'id': 'ABB',
                            'pytest_name': 't_abb'
                        }]
                    },
                ]
            },
            'AA': {
                'subtests': [
                    {
                        'id': 'AAA',
                        'pytest_name': 't_aaa'
                    },
                    'AAB',
                ]
            },
            'AAB': {
                'subtests': [{
                    'id': 'AABA',
                    'pytest_name': 't_aaba'
                }, 'A']
            }
        },
        'tests': ['A']
    }
    test_list = manager.BuildTestListForUnittest(
        test_list_config=_FAKE_TEST_LIST_CONFIG)
    self.assertRaises(test_list_module.CircularError,
                      test_list.ToFactoryTestList)

  # TODO(jeffulin): This test should be removed when skipped_test and
  # waived_tests are removed.
  def testSetSkipWaiveTestsAndConditionalPatches(self):
    _FAKE_TEST_LIST_CONFIG = {
        'definitions': {
            'A': {}
        },
        'options': {
            'skipped_tests': {
                'device.factory.end_FT': [],
                'device.factory.end_RUNIN': [],
                'EVT': [],
                'DVT': []
            },
            'conditional_patches': [{
                'action': 'skip',
                'conditions': {
                    'phases': ['EVT', 'DVT', 'PVT'],
                    'patterns': ['*.AB']
                }
            }, {
                'action': 'skip',
                'conditions': {
                    'patterns': ['*.AB'],
                    'run_if': ['device.factory.end_FT']
                }
            }, {
                'action': 'skip',
                'conditions': {
                    'phases': 'EVT',
                    'patterns': '*.AA'
                }
            }]
        },
        'tests': ['A']
    }
    test_list = manager.BuildTestListForUnittest(
        test_list_config=_FAKE_TEST_LIST_CONFIG)
    self.assertRaises(type_utils.TestListError, test_list.ToFactoryTestList)


class ConditionalPatchTest(unittest.TestCase):

  def testSetRetries(self):
    _FAKE_TEST_LIST_CONFIG = {
        'options': {
            'conditional_patches': [{
                'action': 'set_retries',
                'args': {
                    'times': 3
                },
                'conditions': {
                    'patterns': ['A.*', '*.BA.*']
                }
            }]
        },
        'definitions': {
            'A': {
                'subtests': ['AA', 'AB']
            },
            'B': {
                'subtests': ['BA', 'BB']
            },
            'C': {
                'subtests': ['BA']
            },
            'AA': {
                "inherit": "TestGroup",
                'subtests': ['AAA']
            },
            'AB': {},
            'BA': {
                'subtests': ['BAA']
            },
            'BB': {},
            'AAA': {},
            'BAA': {},
        },
        'tests': ['A', 'B', 'C']
    }
    test_list = manager.BuildTestListForUnittest(_FAKE_TEST_LIST_CONFIG)
    test_list.ApplyConditionalPatchesToTests()

    test = test_list.LookupPath('A')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('A.AA')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('A.AB')
    self.assertEqual((test.retries, test.default_retries), (3, 3))
    test = test_list.LookupPath('A.AA.AAA')
    self.assertEqual((test.retries, test.default_retries), (3, 3))
    test = test_list.LookupPath('B')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('B.BA')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('B.BB')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('B.BA.BAA')
    self.assertEqual((test.retries, test.default_retries), (3, 3))
    test = test_list.LookupPath('C')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('C.BA')
    self.assertEqual((test.retries, test.default_retries), (0, 0))
    test = test_list.LookupPath('C.BA.BAA')
    self.assertEqual((test.retries, test.default_retries), (3, 3))


class EvaluateRunIfTest(unittest.TestCase):
  def setUp(self):
    state_instance = state.StubFactoryState()
    constants = {}

    self.test = type_utils.AttrDict(run_if=None, path='path.to.test')
    # run_if function should only use these attributes
    self.test_list = type_utils.AttrDict(state_instance=state_instance,
                                         constants=constants)

  def _EvaluateRunIf(self):
    return test_list_module.ITestList.EvaluateRunIf(self.test, self.test_list)

  def _ReplaceIsEngineeringModeInRunIf(self, is_engineering_mode):
    return test_list_module.ITestList.ReplaceIsEngineeringModeInRunIf(
        self.test.run_if, is_engineering_mode)

  def testReplaceIsEngineeringModeInRunIf_Match(self):
    is_engineering_mode = True

    self.test.run_if = 'is_engineering_mode'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode), 'True')

    self.test.run_if = ' is_engineering_mode'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode), ' True')

    self.test.run_if = 'is_engineering_mode '
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode), 'True ')

    self.test.run_if = ' is_engineering_mode '
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode), ' True ')

    self.test.run_if = 'is_engineering_mode or device.foo.bar'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'True or device.foo.bar')

    self.test.run_if = ' is_engineering_mode or device.foo.bar'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        ' True or device.foo.bar')

    self.test.run_if = 'device.foo.bar or is_engineering_mode'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'device.foo.bar or True')

    self.test.run_if = 'device.foo.bar or is_engineering_mode '
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'device.foo.bar or True ')

    self.test.run_if = 'device.foo.bar or is_engineering_mode or constants.foo'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'device.foo.bar or True or constants.foo')

  def testReplaceIsEngineeringModeInRunIf_NotMatch(self):
    is_engineering_mode = True

    self.test.run_if = 'not_is_engineering_mode'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'not_is_engineering_mode')

    self.test.run_if = 'is_engineering_mode_and_something'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'is_engineering_mode_and_something')

    self.test.run_if = 'device.foo.is_engineering_mode'
    self.assertEqual(
        self._ReplaceIsEngineeringModeInRunIf(is_engineering_mode),
        'device.foo.is_engineering_mode')

  def testInvalidRunIfString(self):
    self.test.run_if = '!device.foo.bar'
    self.assertTrue(self._EvaluateRunIf())

  def testDeviceData(self):
    self.test.run_if = 'device.foo.bar'

    self.assertFalse(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(True)
    self.assertTrue(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(False)
    self.assertFalse(self._EvaluateRunIf())

  def testConstant(self):
    self.test.run_if = 'constants.foo.bar'

    self.assertFalse(self._EvaluateRunIf())

    self.test_list.constants['foo'] = {'bar': True}
    self.assertTrue(self._EvaluateRunIf())

    self.test_list.constants['foo'] = {'bar': False}
    self.assertFalse(self._EvaluateRunIf())

  def testIsEngineeringMode(self):
    self.test.run_if = 'is_engineering_mode'

    self.assertIsNone(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf[KEY_ENGINEERING_MODE].Set(False)
    self.assertFalse(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf[KEY_ENGINEERING_MODE].Set(True)
    self.assertTrue(self._EvaluateRunIf())

  def testExpression(self):
    self.test.run_if = 'constants.phase == "PVT"'

    self.assertFalse(self._EvaluateRunIf())

    self.test_list.constants['phase'] = 'DVT'
    self.assertFalse(self._EvaluateRunIf())

    self.test_list.constants['phase'] = 'PVT'
    self.assertTrue(self._EvaluateRunIf())

  def testComplexExpression(self):
    self.test.run_if = ('not device.foo.bar or constants.x.y '
                        'and is_engineering_mode')

    self.test_list.state_instance.data_shelf[KEY_ENGINEERING_MODE].Set(True)

    self.assertTrue(self._EvaluateRunIf())

    self.test_list.constants['x'] = {'y': True}
    self.assertTrue(self._EvaluateRunIf())

    self.test_list.constants['x'] = {'y': False}
    self.assertTrue(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(True)
    self.test_list.constants['x'] = {'y': False}
    self.assertFalse(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(True)
    self.test_list.constants['x'] = {}
    self.assertFalse(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(True)
    self.test_list.constants['x'] = {'y': True}
    self.assertTrue(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(True)
    self.test_list.constants['x'] = {'y': False}
    self.test_list.state_instance.data_shelf[KEY_ENGINEERING_MODE].Set(False)
    self.assertFalse(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(True)
    self.test_list.constants['x'] = {'y': True}
    self.test_list.state_instance.data_shelf[KEY_ENGINEERING_MODE].Set(False)
    self.assertFalse(self._EvaluateRunIf())

    self.test_list.state_instance.data_shelf['device.foo.bar'].Set(False)
    self.test_list.constants['x'] = {'y': True}
    self.test_list.state_instance.data_shelf[KEY_ENGINEERING_MODE].Set(False)
    self.assertTrue(self._EvaluateRunIf())


if __name__ == '__main__':
  unittest.main()
