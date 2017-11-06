#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import glob
import json
import mock
import os
import shutil
import tempfile
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test import device_data
from cros.factory.test import state
from cros.factory.test.test_lists import manager
from cros.factory.utils import config_utils
from cros.factory.utils import type_utils


class TestListConfigTest(unittest.TestCase):
  def testTestListConfig(self):
    json_object = {'a': 1, 'b': 2}
    resolved_config = config_utils.ResolvedConfig(json_object)
    test_list_id = 'test_list_id'

    config = manager.TestListConfig(
        resolved_config=resolved_config,
        test_list_id=test_list_id)

    self.assertEqual(config.test_list_id, test_list_id)
    # TestListConfig object should act like a dict.
    self.assertEqual({k: config[k] for k in config}, json_object)


class TestListLoaderTest(unittest.TestCase):
  def setUp(self):
    test_lists_dir = os.path.abspath(os.path.dirname(__file__))
    self.temp_dir = tempfile.mkdtemp(prefix='cros-factory.manager_unittest.')

    self.loader = manager.Loader(config_dir=self.temp_dir)
    self.manager = manager.Manager(loader=self.loader)

    # copy necessary files into self.temp_dir
    for filepath in glob.glob(os.path.join(test_lists_dir,
                                           'manager_unittest',
                                           '*.test_list.json')):
      shutil.copy(filepath, self.temp_dir)
    shutil.copy(os.path.join(test_lists_dir, 'base.test_list.json'),
                self.temp_dir)
    shutil.copy(os.path.join(test_lists_dir, 'test_list.schema.json'),
                self.temp_dir)

  def tearDown(self):
    shutil.rmtree(self.temp_dir, ignore_errors=True)

  def testGetTestListByID(self):
    test_list = self.manager.GetTestListByID('a')

    factory_test_list = test_list.ToFactoryTestList()
    self.assertListEqual(
        ['SMT.FirstLEDTest', 'SMT.SecondLEDTest', 'SMT.VerifyComponents',
         'SMT.Halt', 'SMT.LEDTest', 'SMT.LEDTest_2'],
        [test.path for test in factory_test_list.Walk() if test.IsLeaf()])
    self.assertEqual('a', factory_test_list.test_list_id)
    options = {
        'engineering_password_sha1': 'dummy_password_sha1',
        'ui_locale': 'zh-CN',
        'sync_event_log_period_secs': 0,
    }

    for key in options:
      self.assertEqual(
          options[key],
          getattr(factory_test_list.options, key))

  @mock.patch.object(state, 'get_instance')
  def testResolveTestArgs(self, state_get_instance):
    state_proxy = state.StubFactoryState()
    state_get_instance.side_effect = lambda *args, **kwargs: state_proxy

    device_data.UpdateDeviceData({'vpd.ro.region': 'us'})

    test_args = {
        'a': 'eval! \'eval! \'',
        'b': 'eval! constants.timestamp',
        'c': 'eval! constants.timestamp + 3',
        'd': 'eval! options.ui_locale.upper()',
        'e': 'eval! [x * x for x in xrange(3)]',
        'f': 'eval! constants.some_label',
        'g': 'eval! state_proxy.data_shelf.device.vpd.ro.region.Get()',
        'h': 'eval! device.vpd.ro.region + "_testing"', }

    test_list = self.manager.GetTestListByID('a')
    constants = test_list.ToTestListConfig()['constants']
    options = test_list.ToTestListConfig()['options']
    resolved_test_args = test_list.ResolveTestArgs(test_args, None, None)

    self.assertDictEqual(
        {'a': 'eval! ',
         'b': constants['timestamp'],
         'c': constants['timestamp'] + 3,
         'd': options['ui_locale'].upper(),
         'e': [x * x for x in xrange(3)],
         'f': {'en-US': 'us', 'zh-CN': 'cn'},
         'g': 'us',
         'h': 'us_testing', },
        resolved_test_args)

    # We expect test arguments to be type dict instead of AttrDict, so yaml
    # serialization of test metadata would work.
    self.assertEqual(dict, type(resolved_test_args['f']))

  def testListTestListIDs(self):
    self.assertItemsEqual(
        ['a', 'b', 'base', 'locals', 'override_args', 'flatten_group',
         'skipped_waived_tests', 'invalid'],
        self.loader.FindTestListIDs())

  def testBuildAllTestLists(self):
    test_lists, unused_error = self.manager.BuildAllTestLists()
    self.assertItemsEqual(
        ['a', 'b', 'locals', 'override_args', 'flatten_group',
         'skipped_waived_tests'], test_lists)

  def testChildActionOnFailure(self):
    """Test if `child_action_on_failure` is properly propagated."""
    test_list = self.manager.GetTestListByID('b')
    factory_test_list = test_list.ToFactoryTestList()

    expected = collections.OrderedDict([
        ('SMT.RebootStep', 'PARENT'),
        ('SMT.Group.RebootStep', 'PARENT'),
        ('SMT.Group.RebootStep_2', 'PARENT'),
        ('SMT.Group_2.RebootStep', 'STOP'),
        ('SMT.Group_2.RebootStep_2', 'STOP'),
        ('SMT.RebootStep_2', 'PARENT'),
        ('SMT.RebootStep_3', 'PARENT'),
        ('SMT.RebootStep_4', 'STOP')])

    self.assertListEqual(
        expected.keys(),
        [test.path for test in factory_test_list.Walk() if test.IsLeaf()])

    for key, value in expected.iteritems():
      self.assertEqual(
          value,
          factory_test_list.LookupPath(key).action_on_failure)

    self.assertEqual(
        'NEXT',
        factory_test_list.LookupPath('SMT.Group').action_on_failure)

  def testOverrideArgs(self):
    test_list = self.manager.GetTestListByID('override_args')
    test_list = test_list.ToFactoryTestList()

    expected = {
        'SMT.FirstLEDTest': ['RED'],
        'SMT.SecondLEDTest': ['BLUE'],
        'SMT.LEDTest': ['GREEN'],
        'SMT.LEDTest_2': ['WHITE'],
    }

    for path, colors in expected.iteritems():
      self.assertEqual(
          colors, test_list.LookupPath(path).dargs['colors'])

  def testModifiedDetection(self):
    test_list = self.manager.GetTestListByID('b')
    self.assertFalse(test_list.modified)

    # 'b' is modified
    os.utime(self.loader.GetConfigPath('b'), None)
    self.assertTrue(test_list.modified)

    # let's go back in time
    os.utime(self.loader.GetConfigPath('b'), (0, 0))
    self.assertTrue(test_list.modified)

    # b inherits base
    os.utime(self.loader.GetConfigPath('base'), None)
    self.assertTrue(test_list.modified)

  def testAutoReloadTestList(self):
    # load test list config
    test_list = self.manager.GetTestListByID('a')

    self.assertTrue(test_list.LookupPath('SMT'))

    # modified content
    with open(self.loader.GetConfigPath('a'), 'r') as f:
      json_object = json.load(f)
    with open(self.loader.GetConfigPath('a'), 'w') as f:
      json_object['constants']['timestamp'] = 123
      json_object['tests'] = [
          {
              'id': 'RunIn',
              'subtests': []
          }
      ]
      json.dump(json_object, f)
    os.utime(self.loader.GetConfigPath('a'), None)

    # test list should be automatically reloaded
    self.assertIsNone(test_list.LookupPath('SMT'))
    self.assertTrue(test_list.LookupPath('RunIn'))
    self.assertEqual(test_list.constants.timestamp, 123)

  def testLocals(self):
    test_list = self.manager.GetTestListByID('locals')
    self.assertEqual(
        test_list.LookupPath('SMT.NOP').locals_,
        {'foo': 'FOO', 'bar': 'BAR'})
    self.assertEqual(
        test_list.LookupPath('SMT.NOP_2').locals_,
        {'foo': 'FOO', 'bar': 'BAZ'})
    self.assertEqual(
        test_list.LookupPath('SMT.NOP_3').locals_,
        {'foo': 'BAR', 'bar': 'BAZ'})

  def testFailedAutoReloadTestList(self):
    # load test list config
    test_list = self.manager.GetTestListByID('a')

    self.assertTrue(test_list.LookupPath('SMT'))

    # modified content
    with open(self.loader.GetConfigPath('a'), 'r') as f:
      json_object = json.load(f)
    with open(self.loader.GetConfigPath('a'), 'w') as f:
      json_object['constants']['timestamp'] = 123
      json_object['tests'] = [
          {
              'id': 'RunIn',
              "invalid_key": "invalid_value",
              'subtests': []
          }
      ]
      json.dump(json_object, f)
    os.utime(self.loader.GetConfigPath('a'), None)

    # test list reloading should fail, and will keep getting old value
    self.assertEqual(test_list.constants.timestamp, 1)
    self.assertTrue(test_list.LookupPath('SMT'))
    # reloading invalid test list should be prevented
    self.assertFalse(test_list.modified)

  def testFlattenGroup(self):
    test_list = self.manager.GetTestListByID('flatten_group')

    expected = collections.OrderedDict([
        ("NOP", {"foo": "FOO"}),
        ("NOP_2", {"foo": "FOO", "bar": "BAR"}),
        ("NOP_3", {"foo": "FOO", "bar": "BAR"}),
        ("Group3.NOP", {"foo": "FOO", "baz": "BAZ"}),
        ("Group3.NOP_2", {"baz": "BAZ"}),
    ])

    self.assertListEqual(
        expected.keys(),
        [test.path for test in test_list.Walk() if test.IsLeaf()])

    for test in test_list.Walk():
      if test.IsLeaf():
        self.assertEqual(test.locals_, expected[test.path])


class EvaluateRunIfTest(unittest.TestCase):
  def setUp(self):
    state_instance = state.StubFactoryState()
    constants = {}

    self.test = type_utils.AttrDict(run_if=None, path='path.to.test')
    # run_if function should only use these attributes
    self.test_list = type_utils.AttrDict(state_instance=state_instance,
                                         constants=constants)

  def _EvaluateRunIf(self):
    return manager.ITestList.EvaluateRunIf(self.test, self.test_list)

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

  def testComplexExpression(self):
    self.test.run_if = 'not device.foo.bar or constants.x.y'

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


if __name__ == '__main__':
  unittest.main()
