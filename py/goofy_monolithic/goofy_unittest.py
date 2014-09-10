#!/usr/bin/python -u
#
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""The unittest for the main factory flow that runs the factory test."""


import factory_common  # pylint: disable=W0611

import logging
import math
import mox
import pickle
import re
import tempfile
import threading
import time
import unittest

from mox import IgnoreArg
from ws4py.client import WebSocketBaseClient

from cros.factory.goofy import goofy
from cros.factory.test import factory
from cros.factory.test import state

from cros.factory.goofy.connection_manager import ConnectionManager
from cros.factory.goofy import invocation
from cros.factory.goofy.goofy import Goofy
from cros.factory.goofy.test_environment import Environment
from cros.factory.test import shopfloor
from cros.factory.test.event import Event
from cros.factory.test.factory import TestState
from cros.factory.utils import test_utils
from cros.factory.utils.process_utils import Spawn


def init_goofy(env=None, test_list=None, options='', restart=True, ui='none'):
  """Initializes and returns a Goofy."""
  new_goofy = Goofy()
  args = ['--ui', ui]
  if restart:
    args.append('--restart')
  if test_list:
    out = tempfile.NamedTemporaryFile(prefix='test_list', delete=False)

    # Remove whitespace at the beginning of each line of options.
    options = re.sub('(?m)^\s+', '', options)
    out.write('TEST_LIST = [' + test_list + ']\n' + options)
    out.close()
    args.extend(['--test_list', out.name])
  logging.info('Running goofy with args %r', args)
  new_goofy.init(args, env or Environment())
  return new_goofy


def mock_autotest(env, name, passed, error_msg):
  """Adds a side effect that a mock autotest will be executed.

  Args:
    env: The mock Environment object.
    name: The name of the autotest to be mocked.
    passed: Whether the test should pass.
    error_msg: The error message.
  """
  def side_effect(unused_name, unused_args, unused_env_additions, result_file):
    with open(result_file, 'w') as out:
      pickle.dump((passed, error_msg), out)
      return Spawn(['true'])

  env.spawn_autotest(
      name, IgnoreArg(), IgnoreArg(), IgnoreArg()).WithSideEffects(side_effect)


def mock_pytest(spawn, name, test_state, error_msg, func=None):
  """Adds a side effect that a mock pytest will be executed.

  Args:
    spawn: The mock Spawn object.
    name: The name of the pytest to be mocked.
    test_state: The resulting test state.
    error_msg: The error message.
    func: Optional callable to run inside the side effect function.
  """
  def side_effect(args, **kwargs):
    info = pickle.load(open(args[-1]))
    assert info.pytest_name == name
    if func:
      func()
    with open(info.results_path, 'w') as out:
      pickle.dump((test_state, error_msg), out)
    return Spawn(['true'], **kwargs)

  spawn(IgnoreArg(), env=IgnoreArg(), stdin=IgnoreArg(), stdout=IgnoreArg(),
        stderr=IgnoreArg()).WithSideEffects(side_effect)


class GoofyTest(unittest.TestCase):
  """Base class for Goofy test cases."""
  options = ''
  ui = 'none'
  expected_create_connection_manager_args = (
      [], factory.Options.scan_wifi_period_secs)
  test_list = None  # Overridden by subclasses

  def setUp(self):
    # Log the name of the test we're about to run, to make it easier
    # to grok the logs.
    logging.info('*** Running test %s', type(self).__name__)
    state.DEFAULT_FACTORY_STATE_PORT = test_utils.FindUnusedTCPPort()
    logging.info('Using port %d for factory state',
                 state.DEFAULT_FACTORY_STATE_PORT)
    self.mocker = mox.Mox()
    self.env = self.mocker.CreateMock(Environment)
    self.state = state.get_instance()
    self.connection_manager = self.mocker.CreateMock(ConnectionManager)
    self.env.create_connection_manager(
      *self.expected_create_connection_manager_args).AndReturn(
      self.connection_manager)
    self.before_init_goofy()
    self.mocker.ReplayAll()
    self.goofy = init_goofy(self.env, self.test_list, self.options,
                ui=self.ui)
    self.mocker.VerifyAll()
    self.mocker.ResetAll()

  def tearDown(self):
    self.goofy.destroy()

    # Make sure we're not leaving any extra threads hanging around
    # after a second.
    for _ in range(10):
      extra_threads = [t for t in threading.enumerate()
               if t != threading.current_thread()]
      if not extra_threads:
        break
      logging.info('Waiting for %d threads to die', len(extra_threads))

      # Wait another 100 ms
      time.sleep(.1)

    self.assertEqual([], extra_threads)

  def _wait(self):
    """Waits for any pending invocations in Goofy to complete.

    Waits for any pending invocations in Goofy to complete,
    and verifies and resets all mocks.
    """
    self.goofy.wait()
    self.mocker.VerifyAll()
    self.mocker.ResetAll()

  def before_init_goofy(self):
    """Hook invoked before init_goofy."""

  def check_one_test(self, test_id, name, passed, error_msg, trigger=None,
                     does_not_start=False, setup_mocks=True, expected_count=1):
    """Runs a single autotest, waiting for it to complete.

    Args:
      test_id: The ID of the test expected to run.
      name: The autotest name of the test expected to run.
      passed: Whether the test should pass.
      error_msg: The error message, if any.
      trigger: An optional callable that will be executed after mocks are
        set up to trigger the autotest.  If None, then the test is
        expected to start itself.
      does_not_start: If True, checks that the test is not expected to start
        (e.g., due to an unsatisfied require_run).
      setup_mocks: If True, sets up mocks for the test runs.
      expected_count: The expected run count.
    """
    if setup_mocks and not does_not_start:
      mock_autotest(self.env, name, passed, error_msg)
    self.mocker.ReplayAll()
    if trigger:
      trigger()
    self.assertTrue(self.goofy.run_once())
    self.assertEqual([] if does_not_start else [test_id],
                     [test.path for test in self.goofy.invocations])
    self._wait()
    test_state = self.state.get_test_state(test_id)
    self.assertEqual(TestState.PASSED if passed else TestState.FAILED,
             test_state.status)
    self.assertEqual(0 if does_not_start else expected_count, test_state.count)
    self.assertEqual(error_msg, test_state.error_msg)


# A simple test list with three tests.
ABC_TEST_LIST = """
  OperatorTest(id='a', autotest_name='a_A'),
  OperatorTest(id='b', autotest_name='b_B'),
  OperatorTest(id='c', autotest_name='c_C'),
"""


class BasicTest(GoofyTest):
  """A simple test case that checks that tests are run in the correct order."""
  test_list = ABC_TEST_LIST
  def runTest(self):
    self.check_one_test('a', 'a_A', True, '')
    self.check_one_test('b', 'b_B', False, 'Uh-oh')
    self.check_one_test('c', 'c_C', False, 'Uh-oh')
    self.assertEqual(
        'id: null\n'
        'path: null\n'
        'subtests:\n'
        '- {count: 1, error_msg: null, id: a, path: a, status: PASSED}\n'
        '- {count: 1, error_msg: Uh-oh, id: b, path: b, status: FAILED}\n'
        '- {count: 1, error_msg: Uh-oh, id: c, path: c, status: FAILED}\n',
        self.goofy.test_list.as_yaml(
            factory.get_state_instance().get_test_states()))


class WebSocketTest(GoofyTest):
  """A test case that checks the behavior of web sockets."""
  test_list = ABC_TEST_LIST
  ui = 'chrome'

  def __init__(self, *args, **kwargs):
    super(WebSocketTest, self).__init__(*args, **kwargs)
    self.events = None
    self.ws_done = None

  def before_init_goofy(self):
    # Keep a record of events we received
    self.events = []
    # Trigger this event once the web socket closes
    self.ws_done = threading.Event()

    class MyClient(WebSocketBaseClient):
      """The web socket client class."""
      # pylint: disable=E0213
      def handshake_ok(socket_self):
        pass

      def received_message(socket_self, message):
        event = Event.from_json(str(message))
        logging.info('Test client received %s', event)
        self.events.append(event)
        if event.type == Event.Type.HELLO:
          socket_self.send(Event(Event.Type.KEEPALIVE,
                                 uuid=event.uuid).to_json())

    ws = MyClient(
      'ws://localhost:%d/event' % state.DEFAULT_FACTORY_STATE_PORT,
      protocols=None, extensions=None)

    def open_web_socket():
      ws.connect()
      # Simulate setting the test widget size/position, since goofy
      # waits for it.
      factory.set_shared_data('test_widget_size', [100, 200],
                              'test_widget_position', [300, 400])
      ws.run()
      self.ws_done.set()
    # pylint: disable=W0108
    self.env.launch_chrome().WithSideEffects(
      lambda: threading.Thread(target=open_web_socket).start()
      ).AndReturn(None)

  def runTest(self):
    self.check_one_test('a', 'a_A', True, '')
    self.check_one_test('b', 'b_B', False, 'Uh-oh')
    self.check_one_test('c', 'c_C', False, 'Uh-oh')

    # Kill Goofy and wait for the web socket to close gracefully
    self.goofy.destroy()
    self.ws_done.wait()

    events_by_type = {}
    for event in self.events:
      events_by_type.setdefault(event.type, []).append(event)

    # There should be one hello event
    self.assertEqual(1, len(events_by_type[Event.Type.HELLO]))

    # Each test should have a transition to active, a transition to
    # active + visible, and then to its final state
    for path, final_status in (('a', TestState.PASSED),
                               ('b', TestState.FAILED),
                               ('c', TestState.FAILED)):
      statuses = [
        event.state['status']
        for event in events_by_type[Event.Type.STATE_CHANGE]
        if event.path == path]
      self.assertEqual(
        ['ACTIVE', 'ACTIVE', final_status],
        statuses)


class ShutdownTest(GoofyTest):
  """A test case that checks the behavior of shutdown."""
  test_list = """
    RebootStep(id='shutdown', iterations=3),
    OperatorTest(id='a', autotest_name='a_A')
  """
  def runTest(self):
    # Stub out invocation.Spawn to mock pytest invocation.
    invocation.Spawn = self.mocker.CreateMock(Spawn)

    # Expect a reboot request.
    mock_pytest(invocation.Spawn, 'shutdown', TestState.ACTIVE, '',
                func=lambda: self.goofy.shutdown('reboot'))
    self.env.shutdown('reboot').AndReturn(True)
    self.mocker.ReplayAll()
    self.assertTrue(self.goofy.run_once())
    self._wait()

    # That should have enqueued a task that will cause Goofy
    # to shut down.
    self.assertFalse(self.goofy.run_once())

    # There should be a list of tests to run on wake-up.
    self.assertEqual(
        ['a'], self.state.get_shared_data('tests_after_shutdown'))
    self._wait()

    # Kill and restart Goofy to simulate the first two shutdown iterations.
    # Goofy should call for another shutdown.
    for _ in range(2):
      self.mocker.ResetAll()
      self.env.create_connection_manager(
          [], factory.Options.scan_wifi_period_secs).AndReturn(
              self.connection_manager)
      # Goofy should invoke shutdown test to do post-shutdown verification.
      mock_pytest(invocation.Spawn, 'shutdown', TestState.PASSED, '')
      # Goofy should invoke shutdown again to start next iteration.
      mock_pytest(invocation.Spawn, 'shutdown', TestState.ACTIVE, '',
                  func=lambda: self.goofy.shutdown('reboot'))
      self.env.shutdown('reboot').AndReturn(True)
      self.mocker.ReplayAll()
      self.goofy.destroy()
      self.goofy = init_goofy(self.env, self.test_list, restart=False)
      self.goofy.run_once()
      self._wait()

    # The third shutdown iteration.
    self.mocker.ResetAll()
    self.env.create_connection_manager(
        [], factory.Options.scan_wifi_period_secs).AndReturn(
            self.connection_manager)
    # Goofy should invoke shutdown test to do post-shutdown verification.
    mock_pytest(invocation.Spawn, 'shutdown', TestState.PASSED, '')
    self.mocker.ReplayAll()
    self.goofy.destroy()
    self.goofy = init_goofy(self.env, self.test_list, restart=False)
    self.goofy.run_once()
    self._wait()

    # No more shutdowns - now 'a' should run.
    self.check_one_test('a', 'a_A', True, '')


class RebootFailureTest(GoofyTest):
  """A test case that checks the behavior of reboot failure."""
  test_list = """
    RebootStep(id='shutdown'),
  """
  def runTest(self):
    # Stub out invocation.Spawn to mock pytest invocation.
    invocation.Spawn = self.mocker.CreateMock(Spawn)

    # Expect a reboot request
    mock_pytest(invocation.Spawn, 'shutdown', TestState.ACTIVE, '',
                func=lambda: self.goofy.shutdown('reboot'))
    self.env.shutdown('reboot').AndReturn(True)
    self.mocker.ReplayAll()
    self.assertTrue(self.goofy.run_once())
    self._wait()

    # That should have enqueued a task that will cause Goofy
    # to shut down.
    self.mocker.ReplayAll()
    self.assertFalse(self.goofy.run_once())
    self._wait()

    # Something pretty close to the current time should be written
    # as the shutdown time.
    shutdown_time = self.state.get_shared_data('shutdown_time')
    self.assertTrue(math.fabs(time.time() - shutdown_time) < 2)

    # Kill and restart Goofy to simulate a reboot.
    # Goofy should fail the test since it has been too long.
    self.goofy.destroy()

    self.mocker.ResetAll()
    self.env.create_connection_manager(
        [], factory.Options.scan_wifi_period_secs).AndReturn(
            self.connection_manager)
    # Mock a failed shutdown post-shutdown verification.
    mock_pytest(invocation.Spawn, 'shutdown', TestState.FAILED,
                'Reboot failed.')
    self.mocker.ReplayAll()
    self.goofy = init_goofy(self.env, self.test_list, restart=False)
    self.goofy.run_once()
    self._wait()

    test_state = factory.get_state_instance().get_test_state('shutdown')
    self.assertEquals(TestState.FAILED, test_state.status)
    logging.info('%s', test_state.error_msg)
    self.assertTrue(test_state.error_msg.startswith(
        'Reboot failed.'))


class NoAutoRunTest(GoofyTest):
  """A test case that checks the behavior when auto_run_on_start is False."""
  test_list = ABC_TEST_LIST
  options = 'options.auto_run_on_start = False'

  def _runTestB(self):
    # There shouldn't be anything to do at startup, since auto_run_on_start
    # is unset.
    self.mocker.ReplayAll()
    self.goofy.run_once()
    self.assertEqual({}, self.goofy.invocations)
    self._wait()

    # Tell Goofy to run 'b'.
    self.check_one_test(
      'b', 'b_B', True, '',
      trigger=lambda: self.goofy.handle_switch_test(
        Event(Event.Type.SWITCH_TEST, path='b')))

  def runTest(self):
    self._runTestB()
    # No more tests to run now.
    self.mocker.ReplayAll()
    self.goofy.run_once()
    self.assertEqual({}, self.goofy.invocations)


class AutoRunKeypressTest(NoAutoRunTest):
  """A test case that checks the behavior of auto_run_on_keypress."""
  test_list = ABC_TEST_LIST
  options = """
    options.auto_run_on_start = False
    options.auto_run_on_keypress = True
  """

  def runTest(self):
    self._runTestB()
    # Unlike in NoAutoRunTest, C should now be run.
    self.check_one_test('c', 'c_C', True, '')


class PyTestTest(GoofyTest):
  """Tests the Python test driver.

  Note that no mocks are used here, since it's easy enough to just have the
  Python driver run a 'real' test (execpython).
  """
  test_list = """
    OperatorTest(id='a', pytest_name='execpython',
           dargs={'script': 'assert "Tomato" == "Tomato"'}),
    OperatorTest(id='b', pytest_name='execpython',
           dargs={'script': ("assert 'Pa-TAY-to' == 'Pa-TAH-to', "
                             "'Let\\\\\'s call the whole thing off'")})
  """
  def runTest(self):
    self.goofy.run_once()
    self.assertEquals(['a'],
              [test.id for test in self.goofy.invocations])
    self.goofy.wait()
    self.assertEquals(
      TestState.PASSED,
      factory.get_state_instance().get_test_state('a').status)

    self.goofy.run_once()
    self.assertEquals(['b'],
              [test.id for test in self.goofy.invocations])
    self.goofy.wait()
    failed_state = factory.get_state_instance().get_test_state('b')
    self.assertEquals(TestState.FAILED, failed_state.status)
    self.assertTrue(
      """Let's call the whole thing off""" in failed_state.error_msg,
      failed_state.error_msg)


class PyLambdaTest(GoofyTest):
  """A test case that checks the behavior of execpython."""
  test_list = """
    OperatorTest(id='a', pytest_name='execpython',
           dargs={'script': lambda env: 'raise ValueError("It"+"Failed")'})
  """
  def runTest(self):
    self.goofy.run_once()
    self.goofy.wait()
    failed_state = factory.get_state_instance().get_test_state('a')
    self.assertEquals(TestState.FAILED, failed_state.status)
    self.assertTrue(
      """ItFailed""" in failed_state.error_msg,
      failed_state.error_msg)


class MultipleIterationsTest(GoofyTest):
  """Tests running a test multiple times."""
  test_list = """
    OperatorTest(id='a', autotest_name='a_A'),
    OperatorTest(id='b', autotest_name='b_B', iterations=3),
    OperatorTest(id='c', autotest_name='c_C', iterations=3),
    OperatorTest(id='d', autotest_name='d_D'),
  """
  def runTest(self):
    self.check_one_test('a', 'a_A', True, '')

    mock_autotest(self.env, 'b_B', True, '')
    mock_autotest(self.env, 'b_B', True, '')
    mock_autotest(self.env, 'b_B', True, '')
    self.check_one_test('b', 'b_B', True, '', setup_mocks=False,
                        expected_count=3)

    mock_autotest(self.env, 'c_C', True, '')
    mock_autotest(self.env, 'c_C', False, 'I bent my wookie')
    # iterations=3, but it should stop after the first failed iteration.
    self.check_one_test('c', 'c_C', False, 'I bent my wookie',
                        setup_mocks=False, expected_count=2)

    self.check_one_test('d', 'd_D', True, '')


class ConnectionManagerTest(GoofyTest):
  """Tests connection manager."""
  options = """
    options.wlans = [WLAN('foo', 'psk', 'bar')]
  """
  test_list = """
    OperatorTest(id='a', autotest_name='a_A'),
    TestGroup(id='b', exclusive='NETWORKING', subtests=[
      OperatorTest(id='b1', autotest_name='b_B1'),
      OperatorTest(id='b2', autotest_name='b_B2'),
    ]),
    OperatorTest(id='c', autotest_name='c_C'),
  """
  expected_create_connection_manager_args = (mox.Func(
    lambda arg: (len(arg) == 1 and
           arg[0].__dict__ == dict(ssid='foo',
                       security='psk',
                       passphrase='bar'))),
    factory.Options.scan_wifi_period_secs)

  def runTest(self):
    self.check_one_test('a', 'a_A', True, '')
    self.connection_manager.DisableNetworking()
    self.check_one_test('b.b1', 'b_B1', False, 'Uh-oh')
    self.check_one_test('b.b2', 'b_B2', False, 'Uh-oh')
    self.connection_manager.EnableNetworking()
    self.check_one_test('c', 'c_C', True, '')


class RequireRunTest(GoofyTest):
  """Tests FactoryTest require_run argument."""
  options = """
    options.auto_run_on_start = False
  """
  test_list = """
    OperatorTest(id='a', autotest_name='a_A'),
    OperatorTest(id='b', autotest_name='b_B', require_run='a'),
  """
  def runTest(self):
    self.goofy.restart_tests(
      root=self.goofy.test_list.lookup_path('b'))
    self.check_one_test('b', 'b_B', False,
              'Required tests [a] have not been run yet',
              does_not_start=True)

    self.goofy.restart_tests()
    self.check_one_test('a', 'a_A', True, '')
    self.check_one_test('b', 'b_B', True, '')


class RequireRunPassedTest(GoofyTest):
  """Tests FactoryTest require_run argument with Passed syntax."""
  options = """
    options.auto_run_on_start = True
  """
  test_list = """
    OperatorTest(id='a', autotest_name='a_A'),
    OperatorTest(id='b', autotest_name='b_B', require_run=Passed('a')),
  """
  def runTest(self):
    self.check_one_test('a', 'a_A', False, '')
    self.check_one_test('b', 'b_B', False,
              'Required tests [a] have not been run yet',
              does_not_start=True)

    self.goofy.restart_tests()
    self.check_one_test('a', 'a_A', True, '', expected_count=2)
    self.check_one_test('b', 'b_B', True, '')


class RunIfTest(GoofyTest):
  """Tests FactoryTest run_if argument."""
  options = """
    options.auto_run_on_start = True
  """
  test_list = """
    OperatorTest(id='a', autotest_name='a_A', run_if='foo.bar'),
    OperatorTest(id='b', autotest_name='b_B', run_if='!foo.bar'),
    OperatorTest(id='c', autotest_name='c_C'),
  """
  def runTest(self):
    state_instance = factory.get_state_instance()

    # Set foo.bar in the state server.
    shopfloor.save_aux_data('foo', 'MLB00001', {'bar': True})
    self.goofy.update_skipped_tests()
    a_state = state_instance.get_test_state('a')
    self.assertEquals(False, a_state.skip)
    b_state = state_instance.get_test_state('b')
    self.assertEquals(True, b_state.skip)

    self.check_one_test('a', 'a_A', True, '')
    self.check_one_test('c', 'c_C', True, '')
    a_state = state_instance.get_test_state('a')
    self.assertEquals(TestState.PASSED, a_state.status)
    self.assertEquals('', a_state.error_msg)
    b_state = state_instance.get_test_state('b')
    self.assertEquals(TestState.PASSED, b_state.status)
    self.assertEquals(TestState.SKIPPED_MSG, b_state.error_msg)

    # Set foo.bar=False.  The state of b_B should switch to untested.
    shopfloor.save_aux_data('foo', 'MLB00001', {'bar': False})
    self.goofy.update_skipped_tests()
    a_state = state_instance.get_test_state('a')
    self.assertEquals(TestState.PASSED, a_state.status)
    self.assertEquals('', a_state.error_msg)
    b_state = state_instance.get_test_state('b')
    self.assertEquals(TestState.UNTESTED, b_state.status)
    self.assertEquals('', b_state.error_msg)


class GroupRunIfTest(GoofyTest):
  """Tests TestGroup run_if argument."""
  options = """
    options.auto_run_on_start = True
  """
  test_list = """
    TestGroup(id='G1', run_if='foo.g1', subtests=[
      OperatorTest(id='T1', autotest_name='a_A', run_if='foo.t1'),
      OperatorTest(id='T2', autotest_name='a_A', run_if='foo.t2'),
      OperatorTest(id='T3', autotest_name='a_A', run_if='foo.t3'),
      OperatorTest(id='T4', autotest_name='a_A'),
    ])
  """
  def runTest(self):
    state_instance = factory.get_state_instance()

    def _check_state(id_state_dict):
      for test_id, skip_status_msg in id_state_dict.iteritems():
        test_state = state_instance.get_test_state(test_id)
        skip, status, msg = skip_status_msg
        self.assertEquals(skip, test_state.skip)
        self.assertEquals(status, test_state.status)
        self.assertEquals(msg, test_state.error_msg)

    # Keeps group G1 but skips G1.T1.
    # G1.T1 should be the only test to skip.
    shopfloor.save_aux_data('foo', 'MLB00001',
        {'g1': True,
         't1': False,
         't2': True,
         't3': True})
    self.goofy.update_skipped_tests()
    _check_state(
      {'G1': (False, TestState.UNTESTED, None),
       'G1.T1': (True, TestState.UNTESTED,None),
       'G1.T2': (False, TestState.UNTESTED,None),
       'G1.T3': (False, TestState.UNTESTED,None),
       'G1.T4': (False, TestState.UNTESTED,None)})

    # Disables group G1. All tests are skipped.
    shopfloor.save_aux_data('foo', 'MLB00001',
        {'g1' : False,
         't1' : False,
         't2' : True,
         't3' : True})
    self.goofy.update_skipped_tests()
    _check_state(
      {'G1': (True, TestState.UNTESTED, None),
       'G1.T1': (True, TestState.UNTESTED, None),
       'G1.T2': (True, TestState.UNTESTED, None),
       'G1.T3': (True, TestState.UNTESTED, None ),
       'G1.T4': (True, TestState.UNTESTED, None)})

    # Runs group G1. All tests are skipped and passed.
    for _ in range(4):
      self.assertTrue(self.goofy.run_once())
      self.goofy.wait()
    _check_state(
      {'G1': (True, TestState.PASSED, None),
       'G1.T1': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T2': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T3': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T4': (True, TestState.PASSED, TestState.SKIPPED_MSG)})

    # Re-enable group G1, but skips G1.T1.
    # G1, G1.T2, G1.T3, G1.T4 should not be skipped now. Also, they
    # should be untested.
    shopfloor.save_aux_data('foo', 'MLB00001',
        {'g1' : True,
         't1' : False,
         't2' : True,
         't3' : True})
    self.goofy.update_skipped_tests()
    _check_state(
      {'G1': (False, TestState.UNTESTED, None),
       'G1.T1': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T2': (False, TestState.UNTESTED, ''),
       'G1.T3': (False, TestState.UNTESTED, ''),
       'G1.T4': (False, TestState.UNTESTED, '')})


class GroupRunIfSkipTest(GoofyTest):
  """Tests TestGroup run_if argument and skip method."""
  options = """
    options.auto_run_on_start = False
  """
  test_list = """
    TestGroup(id='G1', run_if='foo.g1', subtests=[
      OperatorTest(id='T1', autotest_name='a_A', run_if='foo.t1'),
      OperatorTest(id='T2', autotest_name='a_A', run_if='foo.t2'),
      OperatorTest(id='T3', autotest_name='a_A', run_if='foo.t3'),
      OperatorTest(id='T4', autotest_name='a_A'),
    ])
  """
  def runTest(self):
    state_instance = factory.get_state_instance()

    def _check_state(id_state_dict):
      for test_id, skip_status_msg in id_state_dict.iteritems():
        test_state = state_instance.get_test_state(test_id)
        skip, status, msg = skip_status_msg
        self.assertEquals(skip, test_state.skip)
        self.assertEquals(status, test_state.status)
        self.assertEquals(msg, test_state.error_msg)

    # Enables group G1, but skips G1.T1.
    # G1, G1.T2, G1.T3, G1.T4 should not be skipped. Also, they
    # should be untested.
    shopfloor.save_aux_data('foo', 'MLB00001',
        {'g1' : True,
         't1' : False,
         't2' : True,
         't3' : True})
    self.goofy.update_skipped_tests()
    _check_state(
      {'G1': (False, TestState.UNTESTED, None),
       'G1.T1': (True, TestState.UNTESTED, None),
       'G1.T2': (False, TestState.UNTESTED, None),
       'G1.T3': (False, TestState.UNTESTED, None),
       'G1.T4': (False, TestState.UNTESTED, None)})

    # Runs and Fails G1.T3 test.
    self.check_one_test('G1.T3', 'a_A', False, 'Uh-oh',
        trigger=lambda: self.goofy.handle_switch_test(
        Event(Event.Type.SWITCH_TEST, path='G1.T3')))
    # Runs and Passes G1.T4 test.
    self.check_one_test('G1.T4', 'a_A', True, '',
        trigger=lambda: self.goofy.handle_switch_test(
        Event(Event.Type.SWITCH_TEST, path='G1.T4')))
    # Now G1.T3 status is FAILED, and G1.T4 status is PASSED.
    # Now G1 status is FAILED because G1.T3 status is FAILED.
    _check_state(
      {'G1': (False, TestState.FAILED, None),
       'G1.T1': (True, TestState.UNTESTED, None),
       'G1.T2': (False, TestState.UNTESTED, None),
       'G1.T3': (False, TestState.FAILED, 'Uh-oh'),
       'G1.T4': (False, TestState.PASSED, '')})

    # Skips G1 on purpose. Then all tests should be skipped.
    # G1.T4 has already passed, so its error_msg should not be modified.
    self.goofy.test_list.lookup_path('G1').skip()
    _check_state(
      {'G1': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T1': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T2': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T3': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T4': (False, TestState.PASSED, '')})

    # update_skipped_tests should not re-enable G1 test group.
    # It only modifies the skip status of G1.T4 from False to True.
    self.goofy.update_skipped_tests()
    _check_state(
      {'G1': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T1': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T2': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T3': (True, TestState.PASSED, TestState.SKIPPED_MSG),
       'G1.T4': (True, TestState.PASSED, '')})


class StopOnFailureTest(GoofyTest):
  """A unittest that checks if the goofy will stop after a test fails."""
  test_list = ABC_TEST_LIST
  options = """
    options.auto_run_on_start = True
    options.stop_on_failure = True
  """
  def runTest(self):
    mock_autotest(self.env, 'a_A', True, '')
    mock_autotest(self.env, 'b_B', False, 'Oops!')
    self.mocker.ReplayAll()
    # Make sure events are all processed.
    for _ in range(3):
      self.assertTrue(self.goofy.run_once())
      self.goofy.wait()

    state_instance = factory.get_state_instance()
    self.assertEquals(
        [TestState.PASSED, TestState.FAILED, TestState.UNTESTED],
        [state_instance.get_test_state(x).status for x in ['a', 'b', 'c']])
    self._wait()

if __name__ == "__main__":
  factory.init_logging('goofy_unittest')
  goofy._inited_logging = True
  goofy.suppress_chroot_warning = True

  unittest.main()
