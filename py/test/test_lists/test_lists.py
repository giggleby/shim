# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Test list builder."""


import glob
import importlib
import logging
import os
import re
import sys
import threading
import yaml
from collections import namedtuple
from contextlib import contextmanager

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import paths
from cros.factory.test import factory


# Directory for new-style test lists.
TEST_LISTS_PATH = os.path.join(
    paths.FACTORY_PACKAGE_PATH, 'test', 'test_lists')

# File identifying the active test list.
ACTIVE_PATH = os.path.join(TEST_LISTS_PATH, 'ACTIVE')

# File listing test list modules to be ignored.
IGNORE_PATH = os.path.join(TEST_LISTS_PATH, 'IGNORE')

# Main test list name.
MAIN_TEST_LIST_ID = 'main'

# Old symlinked custom directory (which may contain test lists).
# For backward compatibility only.
CUSTOM_DIR = os.path.join(paths.FACTORY_PATH, 'custom')

# State used to build test lists.
#
# Properties:
#   stack: A stack of items being built.  stack[0] is always a TestList
#       (if one is currently being built).
#   test_lists: A dictionary (id, test_list_object) of all test lists
#       that have been built or are being built.
#   in_teardown: A boolean, we are in a subtree of teardown tests.
builder_state = threading.local()

# Sampling is the helper class to control sampling of tests in test list.
# key: The key used in device_data which will be evaluated in run_if argument.
# rate:
#   0.0: 0% sampling rate
#   1.0: 100% sampling rate
SamplingRate = namedtuple('SamplingRate', ['key', 'rate'])


class TestListError(Exception):
  """TestList exception"""
  pass


@contextmanager
def Context(test):
  """Creates the context manager for a test (or test list) with subtests.

  This appends test to the stack when it is entered, and pops it from the stack
  when exited.
  """
  try:
    builder_state.stack.append(test)
    yield test
  finally:
    popped = builder_state.stack.pop()
    assert test == popped


def Add(test):
  """Adds a test to the current item on the state.

  Returns a context that can be used to add subtests.
  """
  if not builder_state.stack:
    raise TestListError('Cannot add test %r: not within a test list' % test.id)
  if builder_state.in_teardown:
    test.set_teardown()
  builder_state.stack[-1].subtests.append(test)
  return Context(test)


@contextmanager
def Subtests():
  """New tests added in this context will be appended as subtests.

  By default, tests are always appended to 'subtests', this function is just for
  making APIs symmetric.
  """
  if not builder_state.stack:
    raise TestListError('Cannot switch to subtests: not within a test list')
  if builder_state.in_teardown:
    raise TestListError('Subtests of teardown tests must be teardown tests')
  yield


@contextmanager
def Teardowns():
  """New tests added in this context will be appended as teardown tests.

  Tests added with in this context will be marked as teardown.
  """
  if not builder_state.stack:
    raise TestListError('Cannot switch to teardowns: not within a test list')
  if builder_state.in_teardown:
    raise TestListError('You don\'t need to switch to teardown test again')
  builder_state.in_teardown = True
  yield
  builder_state.in_teardown = False


#####
#
# Builders for test steps/object in cros.factory.test.factory.
#
# See the respective class definitions in that module for docs.
#
#####

def FactoryTest(*args, **kwargs):
  """Adds a factory test to the test list.

  Args:
    label: A i18n label.
    label_en: Deprecated. An English label.
    label_zh: Deprecated. A Chinese label.
    pytest_name: The name of the pytest to run (relative to
      cros.factory.test.pytests).
    invocation_target: The function to execute to run the test
      (within the Goofy process).
    kbd_shortcut: The keyboard shortcut for the test.
    dargs: pytest arguments.
    parallel: Whether the subtests should run in parallel.
    subtests: A list of tests to run inside this test.  In order
      to make conditional construction easier, this may contain None items
      (which are removed) or nested arrays (which are flattened).
    id: A unique ID for the test.
    has_ui: True if the test has a UI. (This defaults to True for
      OperatorTest.) If has_ui is not True, then when the test is
      running, the statuses of the test and its siblings will be shown in
      the test UI area instead.
    never_fails: True if the test never fails, but only returns to an
      untested state.
    disable_abort: True if the test can not be aborted
      while it is running.
    exclusive_resources: Resources that the test may require exclusive access
      to. May be a list or a single string. Items must all be in
      `cros.factory.goofy.plugins.plugin.RESOURCE`.
    enable_services: Services to enable for the test to run correctly.
    disable_services: Services to disable for the test to run correctly.
    _default_id: A default ID to use if no ID is specified.
    require_run: A list of RequireRun objects indicating which
      tests must have been run (and optionally passed) before this
      test may be run.  If the specified path includes this test, then
      all tests up to (but not including) this test must have been run
      already. For instance, if this test is SMT.FlushEventLogs, and
      require_run is "SMT", then all tests in SMT before
      FlushEventLogs must have already been run. ALL may be used to
      refer to the root (i.e., all tests in the whole test list before
      this one must already have been run).

      Examples:
        require_run='x'                 # These three are equivalent;
        require_run=RequireRun('x')     # requires that X has been run
        require_run=[RequireRun('x')]   # (but not necessarily passed)

        require_run=Passed('x')         # These are equivalent;
        require_run=[Passed('x')]       # requires that X has passed

        require_run=Passed(ALL)         # Requires that all previous tests
                                        # have passed

        require_run=['x', Passed('y')]  # Requires that x has been run
                                        # and y has passed
    run_if: Condition under which the test should be run.  This
      must be either a function taking a single argument (an
      invocation.TestArgsEnv object), or a string of the format

        table_name.col
        !table_name.col

      If the auxiliary table 'table_name' is available, then its column 'col'
      is used to determine whether the test should be run.
    iterations: Number of times to run the test.
    retries: Maximum number of retries allowed to pass the test.
      If it's 0, then no retries are allowed (the usual case). If, for example,
      iterations=60 and retries=2, then the test would be run up to 62 times
      and could fail up to twice.
    prepare: A callback function before test starts to run.
    finish: A callback function when test case completed.
      This function has one parameter indicated test result: TestState.PASSED
      or TestState.FAILED.
    _root: True only if this is the root node (for internal use
      only).
  """
  return Add(factory.FactoryTest(*args, **kwargs))


def AutomatedSequence(*args, **kwargs):
  return Add(factory.AutomatedSequence(*args, **kwargs))


def TestGroup(*args, **kwargs):
  """Adds a test group to the current test list.

  This should always be used inside a ``with`` keyword, and tests
  to be included in that test group should be placed inside the
  contained block, e.g.::

    with TestGroup(id='some_test_group'):
      FactoryTest(id='foo', ...)
      OperatorTest(id='bar', ...)

  This creates a test group ``some_test_group`` containing the ``foo``
  and ``bar`` tests.  The top-level nodes ``foo`` and ``bar`` can be
  independently run.

  Args:
    id: The ID of the test (see :ref:`test-paths`).
    label: The i18n label of the group.
    label_en: Deprecated. The label of the group, in English.  This defaults
      to the value of ``id`` if none is specified.
    label_zh: Deprecated. The label of the group, in Chinese.  This defaults
      to the value of ``label_en`` if none is specified.
    run_if: Condition under which the test should be run. Checks the docstring
      of FactoryTest.
  """
  return Add(factory.TestGroup(*args, **kwargs))


def OperatorTest(*args, **kwargs):
  """Adds an operator test (a test with a UI) to the test list.

  This is simply a synonym for
  :py:func:`cros.factory.test.test_lists.test_lists.FactoryTest`, with
  ``has_ui=True``.  It should be used instead of ``FactoryTest`` for
  tests that have a UI to be displayed to the operator.

  See :py:func:`cros.factory.test.test_lists.FactoryTest` for a
  description of all arguments.
  """
  return Add(factory.OperatorTest(*args, **kwargs))


def HaltStep(*args, **kwargs):
  return Add(factory.HaltStep(*args, **kwargs))


def ShutdownStep(*args, **kwargs):
  return Add(factory.ShutdownStep(*args, **kwargs))


def RebootStep(*args, **kwargs):
  return Add(factory.RebootStep(*args, **kwargs))


def FullRebootStep(*args, **kwargs):
  return Add(factory.FullRebootStep(*args, **kwargs))


def Passed(name):
  return factory.RequireRun(name, passed=True)


@contextmanager
def TestList(id, label_en):  # pylint: disable=redefined-builtin
  """Context manager to create a test list.

  This should be used inside a ``CreateTestLists`` function,
  as the target of a ``with`` statement::

    def CreateTestLists():
      with TestList('main', 'Main Test List') as test_list:
        # First set test list options.
        test_list.options.auto_run_on_start = False
        # Now start creating tests.
        FactoryTest(...)
        OperatorTest(...)

  If you wish to modify the test list options (see
  :ref:`test-list-options`), you can use the ``as`` keyword to capture
  the test list into an object (here, ``test_list``).  You can then
  use ``test_list.options`` to refer to the test list options.

  Args:
    id: The ID of the test list.  By convention, the default test list
      is called 'main'.
    label_en: An English label for the test list.
  """
  if id in builder_state.test_lists:
    raise TestListError('Duplicate test list with id %r' % id)
  if builder_state.stack:
    raise TestListError(
        'Cannot create test list %r within another test list %r',
        id, builder_state.stack[0].id)
  test_list = factory.FactoryTestList(
      [], None, factory.Options(), id, label_en, finish_construction=False)
  builder_state.test_lists[id] = test_list
  try:
    builder_state.stack.append(test_list)
    # Proceed with subtest construction.
    yield test_list
    # We're done: finalize it (e.g., to check for duplicate path
    # elements).
    test_list.FinishConstruction()
  finally:
    popped = builder_state.stack.pop()
    assert test_list == popped


def BuildTestLists(module):
  """Creates test lists from a module.

  This runs the CreateTestLists function in the module, which should look like:

  def CreateTestLists():
    # Add tests for the 'main' test list
    with TestList('main', 'All Tests'):
      with TestGroup(...):
        ...
      OperatorTest(...)

    # Add tests for the 'alternate' test list
    with TestList('alternate', 'Alternate'):
      ...

  Args:
    module: The name of the module to load the tests from, or any module
      or object with a CreateTestLists method.  If None, main.py will be
      read (from the overlay) if it exists; otherwise generic.py will be
      read (from the factory repo).
  """
  builder_state.stack = []
  builder_state.test_lists = {}
  builder_state.in_teardown = False

  try:
    if isinstance(module, str):
      module = __import__(module, fromlist=['CreateTestLists'])
    module.CreateTestLists()
    if not builder_state.test_lists:
      raise TestListError('No test lists were created by %r' %
                          getattr(module, '__name__', module))

    for v in builder_state.test_lists.values():
      # Set the source path, replacing .pyc with .py
      v.source_path = re.sub(r'\.pyc$', '.py', module.__file__)
    return builder_state.test_lists
  finally:
    # Clear out the state, to avoid unnecessary references or
    # accidental reuse.
    builder_state.__dict__.clear()


def BuildAllTestLists(force_generic=False):
  """Builds all test lists in this package.

  See README for an explanation of the test-list loading process.

  Args:
    force_generic: Whether to force loading generic test list.  Defaults to
      False so that generic test list is loaded only when there is no main test
      list.

  Returns:
    A 2-element tuple, containing: (1) A dict mapping test list IDs to test list
    objects.  Values are TestList objects.  (2) A dict mapping files that failed
    to load to the output of sys.exc_info().
  """
  test_lists = {}
  failed_files = {}

  def IsGenericTestList(f):
    return os.path.basename(f) == 'generic.py'

  def MainTestListExists():
    return ('main' in test_lists or
            os.path.exists(os.path.join(TEST_LISTS_PATH, 'main.py')))

  ignored_test_list_modules = GetIgnoredTestListModules()

  test_list_files = glob.glob(os.path.join(TEST_LISTS_PATH, '*.py'))
  test_list_files.sort(key=lambda f: (IsGenericTestList(f), f))
  for f in test_list_files:
    if f.endswith('_unittest.py') or os.path.basename(f) == '__init__.py':
      continue
    # Skip generic test list if there is already a main test list loaded
    # and generic test list is not forced.
    if (IsGenericTestList(f) and MainTestListExists() and
        not force_generic):
      continue
    # Skip any test lists listed in the IGNORE file.
    if os.path.splitext(os.path.basename(f))[0] in ignored_test_list_modules:
      continue

    module_name = ('cros.factory.test.test_lists.' +
                   os.path.splitext(os.path.basename(f))[0])
    try:
      module = importlib.import_module(module_name)
    except:  # pylint: disable=bare-except
      logging.exception('Unable to import %s', module_name)
      failed_files[f] = sys.exc_info()
      continue

    method = getattr(module, 'CreateTestLists', None)
    if method:
      try:
        new_test_lists = BuildTestLists(module)
        dups = set(new_test_lists) & set(test_lists.keys())
        if dups:
          logging.warning('Duplicate test lists: %s', dups)
        test_lists.update(new_test_lists)
      except:  # pylint: disable=bare-except
        logging.exception('Unable to read test lists from %s', module_name)
        failed_files[f] = sys.exc_info()

  return test_lists, failed_files


def DescribeTestLists(test_lists):
  """Returns a friendly description of a dict of test_lists.

  Args:
    test_lists: A dict of test_list_id->test_lists (as returned by
        BuildAllTestLists)

  Returns:
    A string like "bar, foo (old-style), main".
  """
  ret = []
  for k in sorted(test_lists.keys()):
    ret.append(k)
  return ', '.join(ret)


def BuildTestList(id):  # pylint: disable=redefined-builtin
  """Builds only a single test list.

  Args:
    id: ID of the test list to build.

  Raises:
    KeyError: If the test list cannot be found.
  """
  test_lists, _ = BuildAllTestLists()
  test_list = test_lists.get(id)
  if not test_list:
    raise KeyError('Unknown test list %r; available test lists are: [%s]' % (
        id, DescribeTestLists(test_lists)))
  return test_list


def GetActiveTestListId():
  """Returns the ID of the active test list.

  This is read from the py/test/test_lists/ACTIVE file, if it exists.
  If there is no ACTIVE file, then 'main' is returned.
  """
  # Make sure it's a real file (and the user isn't trying to use the
  # old symlink method).
  if os.path.islink(ACTIVE_PATH):
    raise TestListError(
        '%s is a symlink (should be a file containing a '
        'test list ID)' % ACTIVE_PATH)

  # Make sure "active" doesn't exist; it should be ACTIVE.
  wrong_caps_file = os.path.join(os.path.dirname(ACTIVE_PATH),
                                 os.path.basename(ACTIVE_PATH).lower())
  if os.path.lexists(wrong_caps_file):
    raise TestListError('Wrong spelling (%s) for active test list file ('
                        'should be %s)' % (wrong_caps_file, ACTIVE_PATH))

  if not os.path.exists(ACTIVE_PATH):
    return MAIN_TEST_LIST_ID

  with open(ACTIVE_PATH) as f:
    test_list_id = f.read().strip()
    if re.search(r'\s', test_list_id):
      raise TestListError('%s should contain only a test list ID' %
                          test_list_id)
    return test_list_id


def SetActiveTestList(id):  # pylint: disable=redefined-builtin
  """Sets the active test list.

  This writes the name of the new active test list to ACTIVE_PATH.
  """
  with open(ACTIVE_PATH, 'w') as f:
    f.write(id + '\n')
    f.flush()
    os.fdatasync(f)


def GetIgnoredTestListModules():
  """Returns module names of ignored test lists.

  This is read from the py/test/test_lists/IGNORE file, if it exists.  Any
  test list files can be listed in IGNORE, separated by spaces.  If there
  is no IGNORE file, then an empty list is returned.
  """
  # Make sure it's a real file.
  if os.path.islink(IGNORE_PATH):
    raise TestListError(
        '%s is a symlink (should be a file containing ignored '
        'test list module names)' % IGNORE_PATH)

  # Make sure "ignore" doesn't exist; it should be IGNORE.
  wrong_caps_file = os.path.join(os.path.dirname(IGNORE_PATH),
                                 os.path.basename(IGNORE_PATH).lower())
  if os.path.lexists(wrong_caps_file):
    raise TestListError('Wrong spelling (%s) for ignore test list file ('
                        'should be %s)' % (wrong_caps_file, IGNORE_PATH))

  if not os.path.exists(IGNORE_PATH):
    return []

  with open(IGNORE_PATH) as f:
    test_list_modules = f.read().split()
    for module in test_list_modules:
      if re.search(r'\s', module):
        raise TestListError('Invalid ignore test list module %s' %
                            module)
    return test_list_modules


def SetIgnoredTestListModules(modules):
  """Sets the active test list.

  Args:
    modules: Array of strings representing test list modules that should be
      ignored.

  This writes the list of ignored test list modules to IGNORE_PATH.
  """
  with open(IGNORE_PATH, 'w') as f:
    f.write(' '.join(modules) + '\n')
    f.flush()
    os.fdatasync(f)


def YamlDumpTestListDestructive(test_list, stream=None):
  """Dumps a test list in YAML format.

  This modifies the test list in certain ways that makes it useless,
  hence "Destructive".

  Args:
    test_list: The test list to be dumped.
    stream: A stream to serialize into, or None to return a string
        (same as yaml.dump).
  """
  del test_list.path_map
  del test_list.state_instance
  del test_list.test_list_id
  for t in test_list.walk():
    del t.parent
    del t.root
    for r in t.require_run:
      # Delete the test object.  But r.path is still present, so we'll
      # still verify that.
      del r.test
    for k, v in t.dargs.items():
      if callable(v):
        # Replace all lambdas with "lambda: None" to make them
        # consistent
        t.dargs[k] = lambda: None
  return yaml.safe_dump(test_list, stream)
