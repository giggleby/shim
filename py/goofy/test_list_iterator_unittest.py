#!/usr/bin/env python
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import cPickle as pickle
import logging
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.goofy import test_list_iterator
from cros.factory.test import factory
from cros.factory.test import state
from cros.factory.test.test_lists import test_lists
from cros.factory.utils import shelve_utils


class TestListIteratorTest(unittest.TestCase):
  OPTIONS = ''  # Overriden by subclasses
  TEST_LIST = ''  # Overriden by subclasses

  def setUp(self):
    self.test_list = self._BuildTestList(self.TEST_LIST, self.OPTIONS)

  def _BuildTestList(self, test_list_code, options_code):
    return test_lists.BuildTestListFromString(test_list_code, options_code)

  def _SetStubStateInstance(self, test_list):
    state_instance = state.StubFactoryState()
    test_list.state_instance = state_instance
    for test in test_list.GetAllTests():
      test.UpdateState(update_parent=False, visible=False)
    return test_list

  def _testPickleSerializable(self, iterator):
    """A TestListIterator object should be pickleable.

    Call this function after some operations to check if the object persists
    after `pickle.dump()` and `pickle.load()`.
    """
    pickled_string = pickle.dumps(iterator)
    deserialized_object = pickle.loads(pickled_string)
    self.assertTrue(isinstance(deserialized_object,
                               test_list_iterator.TestListIterator))
    self.assertListEqual(
        [frame.__dict__ for frame in iterator.stack],
        [frame.__dict__ for frame in deserialized_object.stack])
    self.assertEqual(iterator.status_filter,
                     deserialized_object.status_filter)
    return deserialized_object

  def _AssertTestSequence(self, test_list, expected_sequence,
                          root=None, test_persistency=False, aux_data=None,
                          run_test=None, set_state=True, status_filter=None):
    """Helper function to check the test order.

    Args:
      test_list: the test_list to run
      expected_sequence: the expected test order
      root: starting from which test
      test_persistency: will serialize and deserialize the iterator between each
          next call.
      aux_data: initial stub aux_data
      run_test: a function will be called for each test returned by the
          iterator.  The signature is run_test(test_path, current_aux_data).
          This function must return True if the test is considered passed, False
          otherwise.  This function can modify current_aux_data or cause other
          side effects to affect the next or following tests.
      set_state: override current state of test_list
    """
    if not root:
      root = test_list
    if set_state:
      test_list = self._SetStubStateInstance(test_list)
    iterator = test_list_iterator.TestListIterator(
        root, test_list=test_list, status_filter=status_filter)
    actual_sequence = []
    if not run_test:
      run_test = lambda unused_path, unused_aux_data: True

    aux_data = aux_data or {}
    # mock CheckRunIf
    def _MockedCheckRunIf(path):
      data_shelf = shelve_utils.DictShelfView(shelve_utils.InMemoryShelf())
      data_shelf.SetValue('', aux_data)

      return test_list_iterator.TestListIterator.CheckRunIf(
          iterator,
          path,
          test_arg_env={},
          get_data=data_shelf.GetValue)
    iterator.CheckRunIf = _MockedCheckRunIf

    max_iteration = len(expected_sequence) + 1

    try:
      with self.assertRaises(StopIteration):
        for unused_i in xrange(max_iteration):
          test_path = iterator.next()
          actual_sequence.append(test_path)
          test = test_list.LookupPath(test_path)
          if run_test(test_path, aux_data):
            test.UpdateState(status=factory.TestState.PASSED)
          else:
            test.UpdateState(status=factory.TestState.FAILED)
          if test_persistency:
            iterator = self._testPickleSerializable(iterator)
            # the persistency of state instance is provided by
            # `cros.factory.goofy.goofy`
            # and `cros.factory.test.state`.  We assume that it just works.
            # So the test list itself won't be changed.
            iterator.SetTestList(test_list)
    except Exception:
      logging.error('actual_sequence: %r', actual_sequence)
      raise
    self.assertListEqual(expected_sequence, actual_sequence)


class TestListIteratorBaseTest(TestListIteratorTest):
  """Test test_list_iterator.TestListIterator.

  https://chromium.googlesource.com/chromiumos/platform/factory/+/master/py/test/test_lists/TEST_LIST.md
  """

  OPTIONS = ''
  TEST_LIST = """
    test_lists.FactoryTest(id='a', pytest_name='t_a')
    test_lists.FactoryTest(id='b', pytest_name='t_b')
    with test_lists.FactoryTest(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb')
      with test_lists.TestGroup(id='G'):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
        test_lists.FactoryTest(id='b', pytest_name='t_GGb')
    test_lists.FactoryTest(id='c', pytest_name='t_c')
  """

  def testInitFromRoot(self):
    root_path = self.test_list.path
    iterator = test_list_iterator.TestListIterator(root_path)

    self._testPickleSerializable(iterator)
    self.assertListEqual([root_path], [frame.node for frame in iterator.stack])

    iterator = test_list_iterator.TestListIterator(self.test_list)
    self._testPickleSerializable(iterator)
    self.assertListEqual([root_path], [frame.node for frame in iterator.stack])

  def testInitFromNonRoot(self):
    # 1. specify starting test by path string
    root_path = self.test_list.subtests[0].path
    iterator = test_list_iterator.TestListIterator(root_path)
    self._testPickleSerializable(iterator)
    self.assertListEqual([root_path], [frame.node for frame in iterator.stack])

    # 2. specify starting test by test object
    iterator = test_list_iterator.TestListIterator(self.test_list.subtests[0])
    self._testPickleSerializable(iterator)
    self.assertListEqual([root_path], [frame.node for frame in iterator.stack])

  def testInitWithStatusFilter(self):
    for status_filter in ([],
                          [factory.TestState.FAILED],
                          [factory.TestState.FAILED,
                           factory.TestState.UNTESTED]):
      iterator = test_list_iterator.TestListIterator(
          root=self.test_list, status_filter=status_filter)
      self.assertListEqual(status_filter, iterator.status_filter)
      self._testPickleSerializable(iterator)

  def testStop(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', iterations=2):
      with test_lists.FactoryTest(id='G', iterations=2):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga', iterations=2)
          test_lists.FactoryTest(id='b', pytest_name='t_Gb', iterations=2)
      with test_lists.FactoryTest(id='H', iterations=2):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga', iterations=2)
          test_lists.FactoryTest(id='b', pytest_name='t_Gb', iterations=2)
        """, self.OPTIONS)
    test_list = self._SetStubStateInstance(test_list)
    iterator = test_list_iterator.TestListIterator(
        root=test_list, test_list=test_list)
    self.assertEqual('G.G.a', iterator.next())
    self.assertEqual('G.G.a', iterator.next())
    iterator.Stop('G.G')
    self.assertEqual('G.H.a', iterator.next())
    self.assertEqual('G.H.a', iterator.next())

  def testNext(self):
    self._AssertTestSequence(
        self.test_list,
        ['a', 'b', 'G.a', 'G.b', 'G.G.a', 'G.G.b', 'c'],
        test_persistency=False)
    self._AssertTestSequence(
        self.test_list,
        ['a', 'b', 'G.a', 'G.b', 'G.G.a', 'G.G.b', 'c'],
        test_persistency=True)

  def testNextStartFromNonRoot(self):
    self._AssertTestSequence(
        self.test_list,
        ['G.a', 'G.b', 'G.G.a', 'G.G.b'],
        root='G',
        test_persistency=True)
    self._AssertTestSequence(
        self.test_list,
        ['G.a', 'G.b', 'G.G.a', 'G.G.b'],
        root='G',
        test_persistency=False)
    self._AssertTestSequence(
        self.test_list,
        ['G.G.a', 'G.G.b'],
        root='G.G',
        test_persistency=False)
    self._AssertTestSequence(
        self.test_list,
        ['a'],
        root='a',
        test_persistency=False)
    self._AssertTestSequence(
        self.test_list,
        ['G.a'],
        root='G.a',
        test_persistency=False)

  def testNextAndUpdateTestList(self):
    test_list = self._SetStubStateInstance(self.test_list)
    iterator = test_list_iterator.TestListIterator(
        test_list, test_list=test_list)
    actual_sequence = []

    for unused_i in xrange(3):
      test_path = iterator.next()
      actual_sequence.append(test_path)
      test = test_list.LookupPath(test_path)
      test.UpdateState(status=factory.TestState.PASSED)

    self.assertListEqual(['a', 'b', 'G.a'], actual_sequence)

    # switch to new test list
    test_list = self._BuildTestList(
        """
    test_lists.FactoryTest(id='a', pytest_name='t_a')
    test_lists.FactoryTest(id='b', pytest_name='t_b')
    with test_lists.FactoryTest(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga')  # <- at here
      # test_lists.FactoryTest(id='b', pytest_name='t_Gb')  # removed
      with test_lists.TestGroup(id='G'):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
        test_lists.FactoryTest(id='b', pytest_name='t_GGb')
        test_lists.FactoryTest(id='c', pytest_name='t_GGc')  # new
    test_lists.FactoryTest(id='c', pytest_name='t_c')
        """, self.OPTIONS)
    test_list = self._SetStubStateInstance(test_list)
    iterator.SetTestList(test_list)

    with self.assertRaises(StopIteration):
      for unused_i in xrange(10):
        test_path = iterator.next()
        actual_sequence.append(test_path)
        test = test_list.LookupPath(test_path)
        test.UpdateState(status=factory.TestState.PASSED)

    self.assertListEqual(
        ['a', 'b', 'G.a', 'G.G.a', 'G.G.b', 'G.G.c', 'c'], actual_sequence)

  def testGet(self):
    self._SetStubStateInstance(self.test_list)
    iterator = test_list_iterator.TestListIterator(
        self.test_list, test_list=self.test_list)

    with self.assertRaises(StopIteration):
      for unused_i in xrange(10):
        test_path = iterator.next()
        # Get() shall return the same value as previous next()
        for unused_j in xrange(2):
          self.assertEqual(test_path, iterator.Get())
    # Get() shall return None when we reach the end (StopIteration).
    self.assertIsNone(iterator.Get())

  def testRunIf(self):
    test_list = self._BuildTestList(
        """
    test_lists.FactoryTest(id='a', pytest_name='t_a')
    with test_lists.FactoryTest(id='G', run_if='foo.a'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga')
      with test_lists.TestGroup(id='G'):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
    test_lists.FactoryTest(id='c', pytest_name='t_c')
        """, self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['a', 'c'],
        aux_data={
            'foo': {
                'a': False,
            },
        })
    self._AssertTestSequence(
        test_list,
        ['a', 'G.a', 'G.G.a', 'c'],
        aux_data={
            'foo': {
                'a': True,
            },
        })

    test_list = self._BuildTestList(
        """
    test_lists.FactoryTest(id='a', pytest_name='t_a')
    with test_lists.FactoryTest(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga', run_if='foo.a')
      with test_lists.TestGroup(id='G', run_if='!foo.a'):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
    test_lists.FactoryTest(id='c', pytest_name='t_c')
        """, self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['a', 'G.G.a', 'c'],
        aux_data={
            'foo': {
                'a': False,
            },
        })
    self._AssertTestSequence(
        test_list,
        ['a', 'G.a', 'c'],
        aux_data={
            'foo': {
                'a': True,
            },
        })

  def testStatusFilter(self):
    test_list = self._BuildTestList(
        """
    with test_lists.TestGroup(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga')
      with test_lists.TestGroup(id='G'):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
        test_lists.FactoryTest(id='b', pytest_name='t_GGa')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb')
        """, self.OPTIONS)

    # no filter, all tests should be run
    test_list = self._SetStubStateInstance(test_list)
    test_list.LookupPath('G.a').UpdateState(status=factory.TestState.PASSED)
    test_list.LookupPath('G.G.a').UpdateState(status=factory.TestState.FAILED)
    self._AssertTestSequence(
        test_list,
        ['G.a', 'G.G.a', 'G.G.b', 'G.b'],
        set_state=False,
        status_filter=None)

    # only UNTESTED tests will be run
    test_list = self._SetStubStateInstance(test_list)
    test_list.LookupPath('G.a').UpdateState(status=factory.TestState.PASSED)
    test_list.LookupPath('G.G.a').UpdateState(status=factory.TestState.FAILED)
    self._AssertTestSequence(
        test_list,
        ['G.G.b', 'G.b'],
        set_state=False,
        status_filter=[factory.TestState.UNTESTED])

    # UNTESTED or FAILED
    test_list = self._SetStubStateInstance(test_list)
    test_list.LookupPath('G.a').UpdateState(status=factory.TestState.PASSED)
    test_list.LookupPath('G.G.a').UpdateState(status=factory.TestState.FAILED)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.b', 'G.b'],
        set_state=False,
        status_filter=[factory.TestState.UNTESTED, factory.TestState.FAILED])

    # filter doesn't apply on non-leaf tests
    test_list = self._SetStubStateInstance(test_list)
    test_list.LookupPath('G.a').UpdateState(status=factory.TestState.PASSED)
    test_list.LookupPath('G.G.a').UpdateState(status=factory.TestState.FAILED)
    test_list.LookupPath('G').UpdateState(status=factory.TestState.FAILED)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.b', 'G.b'],
        set_state=False,
        status_filter=[factory.TestState.UNTESTED, factory.TestState.FAILED])

  def testTestGroup(self):
    """Tests if we can handle TestGroup correctly.

    A test group means that the subtests have no dependency, for example,

      G
      |- G.a
      `- G.b

    If we passed G.a and failed G.b, we can retest G.b without running G.a
    again.

    On the other hand, if G is not a TestGroup, then it is an AutomatedSequence,
    which means that the subtests depend on each other.  Retesting G.b must
    retest G.a too.
    """
    test_list = self._BuildTestList(
        """
    with test_lists.TestGroup(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb')
    with test_lists.FactoryTest(id='H'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ha')
      test_lists.FactoryTest(id='b', pytest_name='t_Hb')
        """, self.OPTIONS)

    # G is a test group, H is an AutomatedSequence
    test_list = self._SetStubStateInstance(test_list)
    test_list.LookupPath('G.a').UpdateState(status=factory.TestState.PASSED)
    test_list.LookupPath('G.b').UpdateState(status=factory.TestState.FAILED)
    test_list.LookupPath('H.a').UpdateState(status=factory.TestState.PASSED)
    test_list.LookupPath('H.b').UpdateState(status=factory.TestState.FAILED)
    self._AssertTestSequence(
        test_list,
        ['G.b', 'H.a', 'H.b'],
        set_state=False,
        # since tests will be reset to UNTESTED, so untested must be included
        status_filter=[factory.TestState.FAILED, factory.TestState.UNTESTED])

  def testRunIfCannotSkipParent(self):
    """Make sure we cannot skip a parent test.

    If a test group starts running, changing to its run_if state won't make the
    reset of its child stop running.
    """
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', run_if='foo.a'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga', run_if='foo.a')
      with test_lists.TestGroup(id='G', run_if='foo.a'):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
        test_lists.FactoryTest(id='b', pytest_name='t_GGa')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb')
        """, self.OPTIONS)

    def run_test_1(path, aux_data):
      if path == 'G.G.a':
        aux_data['foo']['a'] = False
      return True
    self._AssertTestSequence(
        test_list,
        ['G.a', 'G.G.a', 'G.G.b', 'G.b'],
        aux_data={
            'foo': {
                'a': True,
            },
        },
        run_test=run_test_1)

    def run_test_2(path, aux_data):
      if path == 'G.a':
        aux_data['foo']['a'] = False
      return True
    self._AssertTestSequence(
        test_list,
        ['G.a', 'G.b'],
        aux_data={
            'foo': {
                'a': True,
            },
        },
        run_test=run_test_2)

  def testRunIfSetByOtherTest(self):
    """Changing aux data also changes run_if result for other tests.

    Test A that is prior to test B can change aux data and turn on / off test
    B.
    """
    test_list = self._BuildTestList(
        """
    test_lists.FactoryTest(id='a', pytest_name='t_a')
    test_lists.FactoryTest(id='b', pytest_name='t_b', run_if='foo.a')
        """, self.OPTIONS)

    # case 1: test 'a' set foo.a to True
    def run_test_1(path, aux_data):
      if path == 'a':
        aux_data['foo'] = {
            'a': True
        }
      return True
    self._AssertTestSequence(
        test_list,
        ['a', 'b'],
        run_test=run_test_1)

    # case 2: normal case
    self._AssertTestSequence(
        test_list,
        ['a'])

    # case 3: foo.a was True, but test 'a' set it to False
    def run_test_3(path, aux_data):
      if path == 'a':
        aux_data['foo'] = {
            'a': False
        }
      return True
    self._AssertTestSequence(
        test_list,
        ['a'],
        aux_data={
            'foo': {
                'a': True
            },
        },
        run_test=run_test_3)


class TestListIteratorParallelTest(TestListIteratorTest):
  TEST_LIST = """
    test_lists.FactoryTest(id='a', pytest_name='t_a')
    test_lists.FactoryTest(id='b', pytest_name='t_b')
    with test_lists.FactoryTest(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb')
      with test_lists.FactoryTest(id='G', parallel=True):
        test_lists.FactoryTest(id='a', pytest_name='t_GGa')
        test_lists.FactoryTest(id='b', pytest_name='t_GGb')
      with test_lists.FactoryTest(id='H'):
        test_lists.FactoryTest(id='a', pytest_name='t_GHa')
        test_lists.FactoryTest(id='b', pytest_name='t_GHb')
    test_lists.FactoryTest(id='c', pytest_name='t_c')
  """
  def testParallel(self):
    """Test cases for FactoryTest.parallel option.

    https://chromium.googlesource.com/chromiumos/platform/factory/+/master/py/test/test_lists/TEST_LIST.md#Parallel-Tests
    """
    self._AssertTestSequence(
        self.test_list,
        ['a', 'b', 'G.a', 'G.b', 'G.G', 'G.H.a', 'G.H.b', 'c'])


class TestListIteratorActionOnFailureTest(TestListIteratorTest):
  """Test behavior of action_on_failure attribute.

  https://chromium.googlesource.com/chromiumos/platform/factory/+/master/py/test/test_lists/TEST_LIST.md#Action-On-Failure
  """
  def testActionOnFailureNext(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga',
                             action_on_failure='NEXT')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb',
                             action_on_failure='NEXT')
    test_lists.FactoryTest(id='c', pytest_name='t_Gc',
                           action_on_failure='NEXT')
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.a', 'G.b', 'c'],
        run_test=lambda path, unused_aux_data: path not in set(['G.a']))

  def testActionOnFailureParentOneLayer(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G'):
      test_lists.FactoryTest(id='a', pytest_name='t_Ga',
                             action_on_failure='PARENT')
      test_lists.FactoryTest(id='b', pytest_name='t_Gb')
    test_lists.FactoryTest(id='c', pytest_name='t_Gc')
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.a', 'c'],
        run_test=lambda path, unused_aux_data: path not in set(['G.a']))

  def testActionOnFailureParentTwoLayer(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G'):
      with test_lists.FactoryTest(id='G', action_on_failure='PARENT'):
        test_lists.FactoryTest(id='a', pytest_name='t_Ga',
                               action_on_failure='PARENT')
        test_lists.FactoryTest(id='b', pytest_name='t_Gb')
      test_lists.FactoryTest(id='c', pytest_name='t_Gc')
    test_lists.FactoryTest(id='d', pytest_name='t_Gd')
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'd'],
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))

  def testActionOnFailureStop(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G'):
      with test_lists.FactoryTest(id='G', action_on_failure='STOP'):
        test_lists.FactoryTest(id='a', pytest_name='t_Ga',
                               action_on_failure='STOP')
        test_lists.FactoryTest(id='b', pytest_name='t_Gb')
      test_lists.FactoryTest(id='c', pytest_name='t_Gc')
    test_lists.FactoryTest(id='d', pytest_name='t_Gd')
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.G.a'],
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))

    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.b'],
        run_test=lambda path, unused_aux_data: path not in set(['G.G.b']))


class TestListIteratorTeardownTest(TestListIteratorTest):
  """Test handling teardown processes.

  https://chromium.googlesource.com/chromiumos/platform/factory/+/master/py/test/test_lists/TEST_LIST.md#Teardown
  """
  def testTeardown(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G'):
      with test_lists.FactoryTest(id='G'):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga')
          test_lists.FactoryTest(id='b', pytest_name='t_Gb')
        with test_lists.Teardowns():
          test_lists.FactoryTest(id='w', pytest_name='t_W')
          test_lists.FactoryTest(id='x', pytest_name='t_X')
          with test_lists.FactoryTest(id='TG'):
            # the subtests of teardown test are teardown tests as well
            test_lists.FactoryTest(id='y', pytest_name='t_Y')
            test_lists.FactoryTest(id='z', pytest_name='t_Z')
      test_lists.FactoryTest(id='c', pytest_name='t_Gc')
      with test_lists.Teardowns():
        test_lists.FactoryTest(id='T', pytest_name='t_T')
    test_lists.FactoryTest(id='d', pytest_name='t_Gd')
        """,
        self.OPTIONS)

    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.b', 'G.G.w', 'G.G.x', 'G.G.TG.y', 'G.G.TG.z', 'G.c',
         'G.T', 'd'],
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))

  def testTeardownAfterStop(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G'):
      with test_lists.FactoryTest(id='G'):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga',
                                 action_on_failure='STOP')
          test_lists.FactoryTest(id='b', pytest_name='t_Gb')
        with test_lists.Teardowns():
          test_lists.FactoryTest(id='w', pytest_name='t_W')
          test_lists.FactoryTest(id='x', pytest_name='t_X')
          with test_lists.FactoryTest(id='TG'):
            # the subtests of teardown test are teardown tests as well
            test_lists.FactoryTest(id='y', pytest_name='t_Y')
            test_lists.FactoryTest(id='z', pytest_name='t_Z')
      test_lists.FactoryTest(id='c', pytest_name='t_Gc')
      with test_lists.Teardowns():
        test_lists.FactoryTest(id='T', pytest_name='t_T')
    test_lists.FactoryTest(id='d', pytest_name='t_Gd')
        """,
        self.OPTIONS)

    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.w', 'G.G.x', 'G.G.TG.y', 'G.G.TG.z', 'G.T'],
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))


class TestListIteratorIterationTest(TestListIteratorTest):
  def testIterations(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', iterations=2):
      with test_lists.FactoryTest(id='G', iterations=2):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga', iterations=2)
          test_lists.FactoryTest(id='b', pytest_name='t_Gb', iterations=2)
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.a', 'G.G.b', 'G.G.b'] * 4)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.a', 'G.G.b', 'G.G.b'] * 4,
        root='G')

  def testRetries(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', retries=1):
      with test_lists.FactoryTest(id='G', retries=1):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga', retries=1)
          test_lists.FactoryTest(id='b', pytest_name='t_Gb', retries=1)
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.a', 'G.G.b', 'G.G.b'] * 4,
        run_test=lambda unused_path, unused_aux_data: False)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.a', 'G.G.b', 'G.G.b'] * 4,
        root='G',
        run_test=lambda unused_path, unused_aux_data: False)

  def testRetriesWithTeardown(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', retries=1):
      with test_lists.FactoryTest(id='G', retries=1):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga', retries=1)
        with test_lists.Teardowns():
          test_lists.FactoryTest(id='b', pytest_name='t_Ga', retries=1)
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.a', 'G.G.b'] * 4,
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))
    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.a', 'G.G.b'] * 4,
        root='G',
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))

  def testActionOnFailureStop(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', retries=1):
      with test_lists.FactoryTest(id='G', retries=1,
                                  action_on_failure='STOP'):
        test_lists.FactoryTest(id='a',
                               pytest_name='t_Ga',
                               action_on_failure='STOP')
        test_lists.FactoryTest(id='b', pytest_name='t_Gb')
      test_lists.FactoryTest(id='c', pytest_name='t_Gc')
    test_lists.FactoryTest(id='d', pytest_name='t_Gd')
        """,
        self.OPTIONS)
    self._AssertTestSequence(
        test_list,
        ['G.G.a'] * 4,
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))

    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.b'] * 4,
        run_test=lambda path, unused_aux_data: path not in set(['G.G.b']))

  def testTeardownAfterStop(self):
    test_list = self._BuildTestList(
        """
    with test_lists.FactoryTest(id='G', retries=1):
      with test_lists.FactoryTest(id='G'):
        with test_lists.Subtests():
          test_lists.FactoryTest(id='a', pytest_name='t_Ga',
                                 action_on_failure='STOP')
          test_lists.FactoryTest(id='b', pytest_name='t_Gb')
        with test_lists.Teardowns():
          test_lists.FactoryTest(id='w', pytest_name='t_W')
          test_lists.FactoryTest(id='x', pytest_name='t_X')
          with test_lists.FactoryTest(id='TG'):
            # the subtests of teardown test are teardown tests as well
            test_lists.FactoryTest(id='y', pytest_name='t_Y')
            test_lists.FactoryTest(id='z', pytest_name='t_Z')
      test_lists.FactoryTest(id='c', pytest_name='t_Gc')
      with test_lists.Teardowns():
        test_lists.FactoryTest(id='T', pytest_name='t_T')
    test_lists.FactoryTest(id='d', pytest_name='t_Gd')
        """,
        self.OPTIONS)

    self._AssertTestSequence(
        test_list,
        ['G.G.a', 'G.G.w', 'G.G.x', 'G.G.TG.y', 'G.G.TG.z', 'G.T'] * 2,
        run_test=lambda path, unused_aux_data: path not in set(['G.G.a']))


if __name__ == '__main__':
  unittest.main()
