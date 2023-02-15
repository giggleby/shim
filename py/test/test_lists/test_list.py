# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test list builder."""

import abc
import ast
import collections.abc
import copy
import json
import logging
import os
import re

from cros.factory.test import i18n
from cros.factory.test.i18n import translation
from cros.factory.test.rules import phase as phase_module
from cros.factory.test import state
from cros.factory.test.state import TestState
from cros.factory.test.test_lists import test_object as test_object_module
from cros.factory.test.utils import selector_utils
from cros.factory.utils import config_utils
from cros.factory.utils import debug_utils
from cros.factory.utils import shelve_utils
from cros.factory.utils import type_utils


# String prefix to indicate this value needs to be evaluated
EVALUATE_PREFIX = 'eval! '

# String prefix to indicate this value needs to be translated
TRANSLATE_PREFIX = 'i18n! '

# used for loop detection
_DUMMY_CACHE = object()

# logged name for debug_utils.CatchException
_LOGGED_NAME = 'TestListManager'


class CircularError(type_utils.TestListError):
  """Exception of circular dependency in test list."""


class ConditionalPatchError(type_utils.TestListError):
  """Exception of setting patches."""


class PatchArgumentError(ConditionalPatchError):
  """Exception of invalid arguments in patches."""


def MayTranslate(obj, force=False):
  """Translate a string if it starts with 'i18n! ' or force=True.

  Args:
    force: force translation even if the string does not start with 'i18n! '.

  Returns:
    A translation dict or string
  """
  if isinstance(obj, dict):
    return obj
  if not isinstance(obj, str):
    raise TypeError('not a string')
  if obj.startswith(TRANSLATE_PREFIX):
    return i18n.Translated(obj[len(TRANSLATE_PREFIX):])
  return i18n.Translated(obj) if force else obj


class Options:
  """Test list options.

  These may be set by assigning to the options variable in a test list,
  e.g.::

    test_list.options.auto_run_on_start = False
  """
  # Allowable types for an option (defaults to the type of the default
  # value).
  _types = {}

  auto_run_on_start = True
  """If set to True, then the test list is automatically started when
  the test harness starts.  If False, then the operator will have to
  manually start a test."""

  retry_failed_on_start = False
  """If set to True, then the failed tests are automatically retried
  when the test harness starts. It is effective when auto_run_on_start
  is set to True."""

  clear_state_on_start = False
  """If set to True, the state of all tests is cleared each time the
  test harness starts."""

  auto_run_on_keypress = False
  """If set to True, the test harness will perform an auto-run whenever
  the operator switches to any test."""

  ui_locale = translation.DEFAULT_LOCALE
  """The default UI locale."""

  engineering_password_sha1 = None
  """SHA1 hash for a engineering password in the UI.  Use None to
  always enable engingeering mode.

  To enter engineering mode, an operator may press Ctrl-Alt-0 and
  enter this password.  Certain special functions in the UI (such as
  being able to arbitrarily run any test) will be enabled.  Pressing
  Ctrl-Alt-0 will exit engineering mode.

  In order to keep the password hidden from operator (even if they
  happen to see the test list file), the actual password is not stored
  in the test list; rather, a hash is.  To generate the hash, run:

  .. parsed-literal::

    echo -n `password` | sha1sum

  For example, for a password of ``test0000``, run::

    echo -n test0000 | sha1sum

  This will display a hash of ``266abb9bec3aff5c37bd025463ee5c14ac18bfca``,
  so you should set::

    test.list.options.engineering_password_sha1 = \
        '266abb9bec3aff5c37bd025463ee5c14ac18bfca'
  """
  _types['engineering_password_sha1'] = (type(None), str)

  sync_event_log_period_secs = None
  """Send events to the factory server when it is reachable at this
  interval.  Set to ``None`` to disable."""
  _types['sync_event_log_period_secs'] = (type(None), int)

  update_period_secs = None
  """Automatically check for updates at the given interval.  Set to
  ``None`` to disable."""
  _types['update_period_secs'] = (type(None), int)

  stop_on_failure = False
  """Whether to stop on any failure."""

  hooks_class = 'cros.factory.goofy.hooks.Hooks'
  """Hooks class for the factory test harness.  Defaults to a dummy class."""
  testlog_hooks = 'cros.factory.testlog.hooks.Hooks'
  """Hooks class for Testlog event. Defaults to a dummy class."""

  phase = None
  """Name of a phase to set.  If None, the phase is unset and the
  strictest (PVT) checks are applied."""
  _types['phase'] = (type(None), str)

  dut_options = {}
  """Options for DUT target.  Automatically inherits from parent node.
  Valid options include::

    {'link_class': 'LocalLink'},  # To run tests locally.
    {'link_class': 'ADBLink'},  # To run tests via ADB.
    {'link_class': 'SSHLink', 'host': TARGET_IP},  # To run tests over SSH.

  See :py:attr:`cros.factory.device.device_utils` for more information."""

  plugin_config_name = 'goofy_plugin_chromeos'
  """Name of the config to be loaded for running Goofy plugins."""

  _types['plugin_config_name'] = (type(None), str)

  read_device_data_from_vpd_on_init = True
  """Read device data from VPD in goofy._InitStates()."""

  skipped_tests = {}
  """A list of tests that should be skipped.
  The content of ``skipped_tests`` should be::

      {
        "<phase>": [ <pattern> ... ],
        "<run_if expr>": [ <pattern> ... ]
      }

  For example::

      {
        "PROTO": [
          "SMT.AudioJack",
          "SMT.SpeakerDMic",
          "*.Fingerprint"
        ],
        "EVT": [
          "SMT.AudioJack",
        ],
        "not device.component.has_touchscreen": [
          "*.Touchscreen"
        ],
        "device.factory.end_SMT": [
          "SMT"
        ]
      }

  If the pattern starts with ``*``, then it will match for all tests with same
  suffix.  For example, ``*.Fingerprint`` matches ``SMT.Fingerprint``,
  ``FATP.FingerPrint``, ``FOO.BAR.Fingerprint``.  But it does not match for
  ``SMT.Fingerprint_2`` (Generated ID when there are duplicate IDs).
  """

  waived_tests = {}
  """Tests that should be waived according to current phase.
  See ``skipped_tests`` for the format"""

  conditional_patches = []
  """A list contains patches to apply to the tests.

  The action of each patch will be applied to all the test meeting the specified
  conditions.

  The structure of the patch list must be like::

      [
        {
          "action": "waive" | "skip",
          "args": { ... },
          "conditions": {
            "run_if": "<run_if expr>" | [ "<run_if expr>", ... ],
            "patterns": "<pattern>" | [ "<pattern>", ... ],
            "phases": "<phase>" | [ "<phase>", ... ],
          }
        },
        ...
      ]

  For example::

      [
        {
          "action": "skip",
          "conditions": {
            "run_if": "not device.component.has_touchscreen",
            "patterns": "*.Touchscreen"
          }
        },
        {
          "action": "skip",
          "conditions": {
            "patterns": [
              "SMT.AudioJack",
              "SMT.SpeakerDMic",
              "*.Fingerprint",
            ],
            "phases": ["PROTO", "EVT"],
          }
        },
        {
          "action": "skip",
          "conditions": {
            "patterns": "SMT.AudioJack",
            "phases": "EVT",
          }
        }
      ]

  Usage of each field:

  * **action**: The action to be applied to the tests.

    `action` is a string representing the action applied to the tests which meet
    the `conditions`. An action will be mapped to a action function.

  * **args**: Keyword arguments to be passed to action functions.

    `args` is an object containing keyword arguments which will be passed to the
    action functions.

  * **conditions**:

    * **patterns** (*required*): The patterns used to match the test list paths.

      If a `pattern` starts with ``*``, then it will match for all tests with
      same suffix. For example, ``*.Fingerprint`` matches ``SMT.Fingerprint``,
      ``FATP.FingerPrint``, ``FOO.BAR.Fingerprint``. But it does not match for
      ``SMT.Fingerprint_2`` (Generated ID when there are duplicate IDs). On the
      other hand, ``*`` can also be put at the end of a `pattern`, then it will
      match for all tests with the same prefix.

      ``*`` can be put at both the beginning and the end of a pattern (e.g.
      ``*.Fingerprint.*``), but not within a pattern.

      For single-pattern cases (only having one pattern to be matched), one can
      set the value of `patterns` as the pattern directly (without wrapping it
      as an array) for convenience.

      For multiple-pattern cases, the patterns included will be treated as a
      disjuction, that is, a test will pass `patterns` condition if it matches
      any one of the patterns.

    * **phases** (*optional*): The phases that will apply the patch.

      If `phases` is not set or it's empty, the patch will be applied to all
      phases (other condition like `patterns` still need to be checked).

      For single-phase cases (only having one phase to be included), one can set
      the value of `phases` as the phase directly.

      For multiple-phase cases, the phases included will be treated as a
      disjuction, that is, a test will pass `phases` condition if the DUT is on
      any one of the phases.

    * **run_if** (*optional*): A set of `run_if` expressions.

      The expressions in the array are to be evaluated and checked. Please check
      ``ITestList._EvaluateRunIf`` to see how an expression is evaluated.

      If `run_if` is not set or it's empty, this field will be ignore and check
      other fields only.

      For single-run_if cases (only having one run_if expre to be evaluated),
      one can set the value of `run_if` as the run_if directly.

      For multiple-phase cases, the run_if included will be treated as a
      disjuction, that is, a test will pass `run_if` condition if any one of the
      expressions is evaluated as `True`.
  """


  def CheckValid(self):
    """Throws a TestListError if there are any invalid options."""
    # Make sure no errant options, or options with weird types,
    # were set.
    default_options = Options()
    errors = []

    if ((getattr(self, 'skipped_tests') or getattr(self, 'waived_tests')) and
        getattr(self, 'conditional_patches')):
      raise type_utils.TestListError(
          'Only one of `skipped/waived_tests` and `conditional_patches` can be '
          'set in Option. `skipped_tests` and `waived_tests` are deprecated '
          'and going to be remove. Skipping or waiving tests can be done by '
          'setting `conditional_patches`.')

    for key in sorted(self.__dict__):
      if not hasattr(default_options, key):
        errors.append(f'Unknown option {key}')
        continue

      value = getattr(self, key)
      allowable_types = Options._types.get(
          key, [type(getattr(default_options, key))])
      if not any(isinstance(value, x) for x in allowable_types):
        errors.append(
            f'Option {key} has unexpected type {type(value)} (should be '
            f'{allowable_types})')
    if errors:
      raise type_utils.TestListError('\n'.join(errors))

  def ToDict(self):
    """Returns a dict containing all values of the Options.

    This include default values for keys not set on the Options.
    """
    result = {
        k: v
        for k, v in self.__class__.__dict__.items() if k[0].islower()
    }
    result.update(self.__dict__)
    return result


class FactoryTestList(test_object_module.FactoryTest):
  """The root node for factory tests.

  Properties:
    path_map: A map from test paths to FactoryTest objects.
    source_path: The path to the file in which the test list was defined,
        if known.  For new-style test lists only.
  """

  def __init__(self, subtests, state_instance, options, test_list_id,
               label=None, finish_construction=True, constants=None):
    """Constructor.

    Args:
      subtests: A list of subtests (FactoryTest instances).
      state_instance: The state instance to associate with the list.
          This may be left empty and set later.
      options: A TestListOptions object.  This may be left empty
          and set later (before calling FinishConstruction).
      test_list_id: An optional ID for the test list.  Note that this is
          separate from the FactoryTest object's 'id' member, which is always
          None for test lists, to preserve the invariant that a test's
          path is always starts with the concatenation of all 'id's of its
          ancestors.
      label: An optional label for the test list.
      finish_construction: Whether to immediately finalize the test
          list.  If False, the caller may add modify subtests and options and
          then call FinishConstruction().
      constants: A type_utils.AttrDict object, which will be used to resolve
          'eval! ' dargs.  See test.test_lists.manager.ITestList.ResolveTestArgs
          for how it is used.
    """
    super().__init__(_root=True, subtests=subtests)
    self.state_instance = state_instance
    self.subtests = list(filter(None, type_utils.FlattenList(subtests)))
    self.path_map = {}
    self.root = self
    self.test_list_id = test_list_id
    self.state_change_callback = None
    self.options = options
    self.label = label
    self.source_path = None
    self.constants = type_utils.AttrDict(constants or {})

    if finish_construction:
      self.FinishConstruction()

  def FinishConstruction(self):
    """Finishes construction of the test list.

    Performs final validity checks on the test list (e.g., resolve duplicate
    IDs, check if required tests exist) and sets up some internal data
    structures (like path_map).  This must be invoked after all nodes and
    options have been added to the test list, and before the test list is used.

    If finish_construction=True in the constructor, this is invoked in
    the constructor and the caller need not invoke it manually.

    When this function is called, self.state_instance might not be set
    (normally, it is set by goofy **after** FinishConstruction is called).

    Raises:
      TestListError: If the test list is invalid for any reason.
    """
    self._init(self.test_list_id + ':', self.path_map)

    # Resolve require_run paths to the actual test objects.
    for test in self.Walk():
      for requirement in test.require_run:
        requirement.test = self.LookupPath(
            self.ResolveRequireRun(test.path, requirement.path))
        if not requirement.test:
          raise type_utils.TestListError(
              f"Unknown test {requirement.path} in {test.path}'s require_run "
              f"argument (note that full paths are required)")

    self.options.CheckValid()
    self._check()

  @classmethod
  def ResolveRequireRun(cls, test_path, requirement_path):
    """Resolve the test path for a requirement in require_run.

    If the path for the requirement starts with ".", then it will be
    interpreted as relative path to parent of test similar to Python's relative
    import syntax.

    For example:

     test_path | requirement_path | returned path
    -----------+------------------+---------------
     a.b.c.d   | e.f              | e.f
     a.b.c.d   | .e.f             | a.b.c.e.f
     a.b.c.d   | ..e.f            | a.b.e.f
     a.b.c.d   | ...e.f           | a.e.f
    """
    if requirement_path.startswith('.'):
      while requirement_path.startswith('.'):
        test_path = shelve_utils.DictKey.GetParent(test_path)
        requirement_path = requirement_path[1:]
      requirement_path = shelve_utils.DictKey.Join(test_path, requirement_path)
    return requirement_path

  def GetAllTests(self):
    """Returns all FactoryTest objects."""
    return list(self.path_map.values())

  def GetStateMap(self):
    """Returns a map of all FactoryTest objects to their TestStates."""
    # The state instance may return a dict (for the XML/RPC proxy)
    # or the TestState object itself. Convert accordingly.
    return dict(
        (self.LookupPath(k), TestState.FromDictOrObject(v))
        for k, v in self.state_instance.GetTestStates().items())

  def LookupPath(self, path):
    """Looks up a test from its path."""
    if ':' not in path:
      path = self.test_list_id + ':' + path
    return self.path_map.get(path, None)

  def _UpdateTestState(self, path, **kwargs):
    """Updates a test state, invoking the state_change_callback if any.

    Internal-only; clients should call update_state directly on the
    appropriate TestState object.
    """
    ret, changed = self.state_instance.UpdateTestState(path=path, **kwargs)
    if changed and self.state_change_callback:
      self.state_change_callback(self.LookupPath(path), ret)
    return ret

  def ToTestListConfig(self, recursive=True):
    """Output a JSON object that is a valid test_lists.schema.json object."""
    config = {
        'inherit': [],
        'label': self.label,
        'options': self.options.ToDict(),
        'constants': dict(self.constants),
    }
    if recursive:
      config['tests'] = [subtest.ToStruct() for subtest in self.subtests]
    return config

  def __repr__(self, recursive=False):
    if recursive:
      return json.dumps(self.ToTestListConfig(recursive=True), indent=2,
                        sort_keys=True, separators=(',', ': '))
    return json.dumps(self.ToTestListConfig(recursive=False), sort_keys=True)


class ITestList(metaclass=abc.ABCMeta):
  """An interface of test list object."""

  # Declare instance variables to make __setattr__ happy.
  _checker = None

  def __init__(self, checker):
    self._checker = checker

  @abc.abstractmethod
  def ToFactoryTestList(self):
    """Convert this object to a FactoryTestList object.

    Returns:
      :rtype: cros.factory.test.test_lists.test_list.FactoryTestList
    """
    raise NotImplementedError

  def CheckValid(self):
    """Check if this can be convert to a FactoryTestList object."""
    if not self.ToFactoryTestList():
      raise type_utils.TestListError('Cannot convert to FactoryTestList')

  def __getattr__(self, name):
    """Redirects attribute lookup to ToFactoryTestList()."""
    logging.debug('getting: %s', name)
    return getattr(self.ToFactoryTestList(), name)

  def __setattr__(self, name, value):
    # Can only set an attribute that already exists.
    if hasattr(self, name):
      object.__setattr__(self, name, value)
    else:
      raise AttributeError(f'cannot set attribute {name!r}')

  @property
  @abc.abstractmethod
  def modified(self):
    raise NotImplementedError

  def ReloadIfModified(self):
    """Reloads the test list (when self.modified == True)."""
    # default behavior, does nothing
    return

  @property
  @abc.abstractmethod
  def constants(self):
    raise NotImplementedError

  def ResolveTestArgs(
      self, test_args, dut, station, constants=None, options=None,
      locals_=None, state_proxy=None):
    self._checker.AssertValidArgs(test_args)

    if constants is None:
      constants = self.constants
    if options is None:
      options = self.options
    if state_proxy is None:
      state_proxy = state.GetInstance()
    locals_ = type_utils.AttrDict(locals_ or {})

    def ConvertToBasicType(value):
      if isinstance(value, collections.abc.Mapping):
        return {k: ConvertToBasicType(v) for k, v in value.items()}
      if isinstance(value, str):
        return value
      if isinstance(value, (list, tuple)):
        return type(value)(ConvertToBasicType(v) for v in value)
      if isinstance(value, collections.abc.Sequence):
        return [ConvertToBasicType(v) for v in value]
      return value

    def ResolveArg(key, value):
      if isinstance(value, collections.abc.Mapping):
        return {k: ResolveArg(f'{key}[{k!r}]', v)
                for k, v in value.items()}

      if isinstance(value, collections.abc.Sequence):
        if not isinstance(value, str):
          return [
              ResolveArg(f'{key}[{int(i)}]', v) for i, v in enumerate(value)
          ]

      if not isinstance(value, str):
        return value

      if value.startswith(EVALUATE_PREFIX):
        logging.debug('Resolving argument %s: %s', key, value)
        expression = value[len(EVALUATE_PREFIX):]  # remove prefix

        return self.EvaluateExpression(expression, dut, station, constants,
                                       options, locals_, state_proxy)

      return MayTranslate(value)

    return ConvertToBasicType(
        {k: ResolveArg(k, v)
         for k, v in test_args.items()})

  @debug_utils.CatchException(_LOGGED_NAME)
  def ApplyConditionalPatchesToTests(self):
    """Applies the patches in the option to tests.

    For each patch, the action will be applied to all the test that meet the
    specified conditions. Please check `Option.conditional_patches` for details.
    """

    def _CheckRunIf(run_if_exprs):
      if isinstance(run_if_exprs, str):
        run_if_exprs = [run_if_exprs]

      if len(run_if_exprs) == 0:
        return True

      for expr in run_if_exprs:
        if self._EvaluateRunIf(run_if=expr, source='test list options',
                               test_list=self, default=False):
          return True

      return False

    def _CheckPhase(phases):
      if isinstance(phases, str):
        phases = [phases]

      if len(phases) == 0:
        return True

      return self.options.phase in phases

    def _CreateMatchFunction(pattern):
      pattern = pattern.split(':')[-1]  # To remove test_list_id

      if pattern.startswith('*') and pattern.endswith('*'):
        return lambda s: pattern[1:-1] in s
      if pattern.startswith('*'):
        return lambda s: s.endswith(pattern[1:])
      if pattern.endswith('*'):
        return lambda s: s.startswith(pattern[:-1])

      return lambda s: s == pattern

    def _PreprocessPatterns(patterns):
      """Converts the string patterns into matching functions."""

      if isinstance(patterns, str):
        patterns = [patterns]

      return list(map(_CreateMatchFunction, patterns))

    _PATCH_CLASS_MAP = {
        WaivePatch.action_name: WaivePatch,
        SkipPatch.action_name: SkipPatch,
        RetriesPatch.action_name: RetriesPatch
    }

    patch_instances = []
    for patch in self.options.conditional_patches:
      conditions = patch.get('conditions', {})
      args = patch.get('args', {})
      action = patch.get('action', "")

      if action not in _PATCH_CLASS_MAP:
        continue

      phases = conditions.get('phases', [])
      run_if_exprs = conditions.get('run_if', [])
      patterns = _PreprocessPatterns(conditions.get('patterns', []))

      if not _CheckRunIf(run_if_exprs) or not _CheckPhase(phases):
        continue

      for test_path, test in self.path_map.items():
        test_path = test_path.split(':')[-1]  # To remove test_list_id
        for pattern in patterns:
          if pattern(test_path):
            patch_instances.append(_PATCH_CLASS_MAP[action](test, args))
            break

    # After all the patches are ready, apply them sequentially
    for inst in patch_instances:
      inst.Apply()

  # TODO(jeffulin): skipped_test and waived_tests are deprecated. Use
  # conditional_patches instead.
  @debug_utils.CatchException(_LOGGED_NAME)
  def SetSkippedAndWaivedTests(self):
    """Set skipped and waived tests according to phase and options.

    Since SKIPPED status is saved in state_instance, self.state_instance must be
    available at this moment.  This functions reads skipped_tests and
    waived_tests options from self.options, for the format of these options,
    please check `cros.factory.test.test_lists.test_list.Options`.
    """
    assert self.state_instance is not None

    current_phase = self.options.phase
    patterns = []

    def _AddPattern(pattern, action):
      pattern = pattern.split(':')[-1]  # To remove test_list_id
      if pattern.startswith('*'):
        patterns.append((lambda s: s.endswith(pattern[1:]), action))
      else:
        patterns.append((lambda s: s == pattern, action))

    def _CollectPatterns(option, action):
      """Collect enabled patterns from test list options.

      Args:
        option: this should be `self.options.skipped_tests` or
          `self.options.waived_tests`
        action: the action that will be passed to _AddPattern
      """

      for key in option:
        if key in phase_module.PHASE_NAMES:
          if key != current_phase:
            continue
        else:  # Assume key is a run_if expression
          if not self._EvaluateRunIf(
              run_if=key,
              source='test list options',
              test_list=self,
              default=False):
            continue

        for pattern in option[key]:
          _AddPattern(pattern, action)

    def _MarkSkipped(test):
      """Mark a test as skipped.

      The test (and its subtests) statuses will become SKIPPED if they were not
      PASSED.  And test.run_if will become constant false.  So Goofy will always
      skip it.
      """
      test.Skip(forever=True)

    def _MarkWaived(test):
      """Mark all test and its subtests as waived.

      subtests should also be waived, so that subtests will become
      FAILED_AND_WAIVED when failed.  And the status will be propagated to
      parents (this test).
      """
      test.Waive()

    _CollectPatterns(self.options.skipped_tests, _MarkSkipped)
    _CollectPatterns(self.options.waived_tests, _MarkWaived)

    for test_path, test in self.path_map.items():
      test_path = test_path.split(':')[-1]  # To remove test_list_id
      for match, action in patterns:
        if match(test_path):
          action(test)

  @classmethod
  def ReplaceIsEngineeringModeInRunIf(cls, run_if, is_engineering_mode):
    """Replaces 'is_engineering_mode' in run_if by input boolean value.

    Replaces 'is_engineering_mode' in run_if statement by the boolean result of
    checking whether in engineering mode or not.
    """
    if 'is_engineering_mode' in run_if:
      run_if = re.sub(r'(?<!\S)is_engineering_mode(?!\S)',
                      str(is_engineering_mode), run_if)
    return run_if

  @classmethod
  def EvaluateExpression(cls, expression, dut, station, constants, options,
                         locals_, state_proxy):
    namespace = {
        'dut': dut,
        'station': station,
        'constants': constants,
        'options': options,
        'locals': locals_,
        'state_proxy': state_proxy,
        'device': state_proxy.data_shelf.device, }

    syntax_tree = ast.parse(expression, mode='eval')
    syntax_tree = NodeTransformer_AddGet(['device']).visit(syntax_tree)
    code_object = compile(syntax_tree, '<string>', 'eval')
    try:
      return eval(code_object, namespace)  # pylint: disable=eval-used
    except AttributeError as err:
      raise AttributeError(expression) from err

  @classmethod
  def EvaluateRunIf(cls, test, test_list):
    """Evaluate the run_if value of this test.

    Evaluates run_if argument to decide skipping the test or not.  If run_if
    argument is not set, the test will never be skipped.

    Args:
      test: a FactoryTest object whose run_if will be checked
      test_list: the test list which is currently running, will get
        state_instance and constants from it.

    Returns:
      True if this test should be run, otherwise False
    """
    return ITestList._EvaluateRunIf(
        test.run_if, test.path, test_list, default=True)

  @classmethod
  def _EvaluateRunIf(cls, run_if, source, test_list, default):
    """Real implementation of EvaluateRunIf.

    If anything went wrong, `default` will be returned.
    """
    if not isinstance(run_if, str):
      # run_if is not a function, not a string, just return default value
      return default

    state_instance = test_list.state_instance
    namespace = {
        'device': selector_utils.DataShelfSelector(
            state_instance, key='device'),
        'constants': selector_utils.DictSelector(value=test_list.constants),
    }

    is_engineering_mode = state_instance.IsEngineeringMode()
    run_if = ITestList.ReplaceIsEngineeringModeInRunIf(run_if,
                                                       is_engineering_mode)

    try:
      syntax_tree = ast.parse(run_if, mode='eval')
      syntax_tree = NodeTransformer_AddGet(
          ['device', 'constants']).visit(syntax_tree)
      code_object = compile(syntax_tree, '<string>', 'eval')
      return eval(code_object, namespace)  # pylint: disable=eval-used
    except Exception:
      logging.exception('Unable to evaluate run_if %r for %s', run_if, source)
      return default

  # the following properties are required by goofy
  @property
  @abc.abstractmethod
  def state_instance(self):
    raise NotImplementedError

  @state_instance.setter
  def state_instance(self, state_instance):
    raise NotImplementedError

  @property
  @abc.abstractmethod
  def state_change_callback(self):
    raise NotImplementedError

  @state_change_callback.setter
  def state_change_callback(self, state_change_callback):
    raise NotImplementedError


class NodeTransformer_AddGet(ast.NodeTransformer):
  """Given a list of names, we will call `Get` function for you.

  For example, name_list=['device']::

    "device.foo.bar"  ==> "device.foo.bar.Get(None)"

  where `None` is the default value for `Get` function.
  And `device.foo.bar.Get` will still be `device.foo.bar.Get`.
  """
  def __init__(self, name_list):
    super().__init__()
    if not isinstance(name_list, list):
      name_list = [name_list]
    self.name_list = name_list

  def visit_Attribute(self, node):
    """Convert the attribute.

    An attribute node will be: `var.foo.bar.baz`, and the node we got is the
    last attribute node (that is, we will visit `var.foo.bar.baz`, not
    `var.foo.bar` or its prefix).  And NodeTransformer will not recursively
    process a node if it is processed, so we only need to worry about process a
    node twice.

    This will fail for code like::

      "eval! any(v.baz.Get() for v in [device.foo, device.bar])"

    But you can always rewrite it to::

      "eval! any(v for v in [device.foo.baz, device.bar.baz])"

    So it should be fine.
    """
    if isinstance(node.ctx, ast.Load) and node.attr != 'Get':
      v = node
      while isinstance(v, ast.Attribute):
        v = v.value
      if isinstance(v, ast.Name) and v.id in self.name_list:
        new_node = ast.Call(
            func=ast.Attribute(
                attr='Get',
                value=node,
                ctx=node.ctx),
            # Use `None` as default value
            args=[ast.Name(id='None', ctx=ast.Load())],
            kwargs=None,
            keywords=[])
        ast.copy_location(new_node, node)
        return ast.fix_missing_locations(new_node)
    return node


class TestList(ITestList):
  """A test list object represented by test list config.

  This object should act like a
  ``cros.factory.test.test_lists.test_list.FactoryTestList`` object.
  """

  # Declare instance variables to make __setattr__ happy.
  _loader = None
  _config = None
  _state_instance = None
  _state_change_callback = None

  # variables starts with '_cached_' will be cleared by ReloadIfModified
  _cached_test_list = None
  _cached_options = None
  _cached_constants = None

  def __init__(self, config, checker, loader):
    super().__init__(checker)
    self._loader = loader
    self._config = config
    self._cached_test_list = None
    self._cached_options = None
    self._cached_constants = None
    self._state_instance = None
    self._state_change_callback = None

  def ToFactoryTestList(self):
    self.ReloadIfModified()
    if self._cached_test_list:
      return self._cached_test_list
    return self._ConstructFactoryTestList()

  @debug_utils.NoRecursion
  def _ConstructFactoryTestList(self):
    subtests = []
    cache = {}
    for test_object in self._config['tests']:
      subtests.append(self.MakeTest(test_object, cache))

    # this might cause recursive call if self.options is not implemented
    # correctly.  Put it in a single line for easier debugging.
    options = self.options

    self._cached_test_list = FactoryTestList(
        subtests, self._state_instance, options,
        test_list_id=self._config.test_list_id,
        label=MayTranslate(self._config['label'], force=True),
        finish_construction=True,
        constants=self.constants)

    # Handle override_args
    if 'override_args' in self._config:
      for key, override in self._config['override_args'].items():
        test = self._cached_test_list.LookupPath(key)
        if test:
          config_utils.OverrideConfig(test.dargs, override)

    self._cached_test_list.state_change_callback = self._state_change_callback
    self._cached_test_list.source_path = self._config.source_path

    if self._state_instance:
      # Make sure the state server knows about all the tests, defaulting to an
      # untested state.
      # TODO(stimim): this code is copied from goofy/goofy.py, we should check
      #               if we really need both.
      for test in self._cached_test_list.GetAllTests():
        test.UpdateState(update_parent=False)

    return self._cached_test_list

  def MakeTest(self, test_object, cache, default_action_on_failure=None,
               locals_=None, test_stack=None, loop_tests=None):
    """Converts a test_object to a `FactoryTest` object.

    Args:
      test_object: A string indicating the test ID or a `TestListConfig`.
      cache: A dictionary to keep the test objects that have once resolved.
      default_action_on_failure: Default action on failure when the action is
        not specified.
      locals_: A dictionary to keep the local constants or the expressions to
        be evaluated.
      test_stack: A stack to keep the current reference chain, used to determine
        if there is any circular dependency.
      loop_tests: A lists to store all the circular dependencies.

    Returns:
      A `FactoryTest` object or a string indicating the test name if this
      function fails to resolve the test (e.g. detect loop)

    Raises:
      TestListError if fails.
    """
    if test_stack is None:
      test_stack, loop_tests = [], []

    test_id = test_object if isinstance(test_object, str) else None
    if test_id:
      if test_id in test_stack:
        loop_chain = '->'.join(test_stack + [test_id])
        loop_tests.append(f'{test_id} ({loop_chain})')
        return test_id
      test_stack.append(test_id)

    test_object = self.ResolveTestObject(
        test_object=test_object,
        test_object_name=None,
        cache=cache)

    if locals_ is None:
      locals_ = {}

    if 'locals' in test_object:
      locals_ = config_utils.OverrideConfig(
          locals_,
          self.ResolveTestArgs(
              test_object.pop('locals'),
              dut=None,
              station=None,
              locals_=locals_),
          copy_on_write=True)

    if not test_object.get('action_on_failure', None):
      test_object['action_on_failure'] = default_action_on_failure
    default_action_on_failure = test_object.pop('child_action_on_failure',
                                                default_action_on_failure)
    kwargs = copy.deepcopy(test_object)
    class_name = kwargs.pop('inherit', 'FactoryTest')

    subtests = []
    for subtest in test_object.get('subtests', []):
      subtests.append(
          self.MakeTest(subtest, cache, default_action_on_failure, locals_,
                        test_stack, loop_tests))

    # replace subtests
    kwargs['subtests'] = subtests
    kwargs['dargs'] = kwargs.pop('args', {})
    kwargs['locals_'] = locals_
    kwargs.pop('__comment', None)

    if kwargs.get('label'):
      kwargs['label'] = MayTranslate(kwargs['label'], force=True)

    # check if expressions are valid.
    self._checker.AssertValidArgs(kwargs['dargs'])
    if 'run_if' in kwargs and isinstance(kwargs['run_if'], str):
      self._checker.AssertValidRunIf(kwargs['run_if'])

    if test_id:
      assert test_stack[-1] == test_id
      test_stack.pop()

    if len(test_stack) == 0 and len(loop_tests) > 0:
      raise CircularError(
          f'Detected circular dependency caused by tests {loop_tests}')

    return getattr(test_object_module, class_name)(**kwargs)

  def ResolveTestObject(self, test_object, test_object_name, cache):
    """Returns a test object inherits all its parents field."""
    if test_object_name in cache:
      if cache[test_object_name] == _DUMMY_CACHE:
        raise type_utils.TestListError(
            f'Detected loop inheritance dependency of {test_object_name}')
      return cache[test_object_name]

    # syntactic sugar: if a test_object is just a string, it's equivalent to
    # {"inherit": string}, e.g.:
    #   "test_object" === {"inherit": "test_object"}
    if isinstance(test_object, str):
      resolved = self.ResolveTestObject({'inherit': test_object},
                                        test_object_name, cache)
      return resolved

    parent_name = test_object.get('inherit', 'FactoryTest')
    if parent_name not in self._config['definitions']:
      raise type_utils.TestListError(
          f'{test_object_name} inherits {parent_name}, which is not defined')
    if parent_name == test_object_name:
      # this test object inherits itself, it means that this object is a class
      # defined in cros.factory.test.test_lists.test_object
      # just save the object and return
      cache[test_object_name] = test_object
      return test_object

    if test_object_name:
      cache[test_object_name] = _DUMMY_CACHE
      # syntax sugar, if id is not given, set id as test object name.
      #
      # According to test_object.py, considering I18n, the priority is:
      # 1. `label` must be specified, or it should come from pytest_name
      # 2. If not specified, `id` comes from label by stripping spaces and dots.
      # Resolved id may be changed in _init when there are duplicated id's found
      # in same path.
      #
      # However, in most of the case, test_object_name would be more like an ID,
      # for example,
      #     "ThermalSensors": {
      #       "pytest_name": "thermal_sensors"
      #     }
      # The label will be derived from pytest_name, "Thermal Sensors", while the
      # ID will be test_object_name, "ThermalSensors".
      if 'id' not in test_object:
        test_object['id'] = test_object_name

    parent_object = self._config['definitions'][parent_name]
    parent_object = self.ResolveTestObject(parent_object, parent_name, cache)
    test_object = config_utils.OverrideConfig(copy.deepcopy(parent_object),
                                              test_object)
    test_object['inherit'] = parent_object['inherit']
    if test_object_name:
      cache[test_object_name] = test_object
    return test_object

  def ToTestListConfig(self, recursive=True):
    if recursive:
      return self._config.ToDict()
    ret = self._config.ToDict()
    ret.pop('tests', None)
    return ret

  def ReloadIfModified(self):
    if not self.modified:
      return
    self._Reload()

  def ForceReload(self):
    """Bypass modification detection, force reload."""
    logging.info('Force reloading test list')
    self._Reload()

  @debug_utils.NoRecursion
  def _Reload(self):
    logging.debug('reloading test list %s', self._config.test_list_id)
    note = {
        'name': _LOGGED_NAME
    }

    try:
      new_config = self._loader.Load(self._config.test_list_id)

      # make sure the new test list is working, if it's not, will raise an
      # exception and self._config will not be changed.
      TestList(new_config, self._checker, self._loader).CheckValid()

      self._config = new_config
      for key in self.__dict__:
        if key.startswith('_cached_'):
          self.__dict__[key] = None
      self.SetSkippedAndWaivedTests()
      self.ApplyConditionalPatchesToTests()
      note['level'] = 'INFO'
      note['text'] = f'Test list {self._config.test_list_id} is reloaded.'
    except Exception:
      logging.exception('Failed to reload latest test list %s.',
                        self._config.test_list_id)
      self._PreventReload()

      note['level'] = 'WARNING'
      note['text'] = (
          f'Failed to reload latest test list {self._config.test_list_id}.')
    try:
      self._state_instance.AddNote(note)
    except Exception:
      pass

  def _PreventReload(self):
    """Update self._config to prevent reloading invalid test list."""
    self._config.UpdateDependTimestamp()

  @property
  def modified(self):
    """Return True if the test list is considered modified, need to be reloaded.

    self._config.timestamp is when was the config last modified, if the config
    file or any of config files it inherits is changed after the timestamp, this
    function will return True.

    Returns:
      True if the test list config is modified, otherwise False.
    """
    # Note that this method can't catch all kind of potential modification.
    # For example, this property won't become `True` if the user add an
    # additional test list in /var/factory/config/ to override an existing one.
    for config_file, timestamp in self._config.GetDepend().items():
      if os.path.exists(config_file):
        if timestamp != os.stat(config_file).st_mtime:
          return True
      elif timestamp is not None:
        # the file doesn't exist, and we think it should exist
        return True
    return False

  @property
  def constants(self):
    self.ReloadIfModified()

    if self._cached_constants:
      return self._cached_constants
    self._cached_constants = type_utils.AttrDict(self._config['constants'])
    return self._cached_constants

  # the following functions / properties are required by goofy
  @property
  def options(self):
    self.ReloadIfModified()
    if self._cached_options:
      return self._cached_options

    self._cached_options = Options()

    class NotAccessable:
      def __getattribute__(self, name):
        raise KeyError('options cannot depend on options')

    resolved_options = self.ResolveTestArgs(
        self._config['options'],
        constants=self.constants,
        options=NotAccessable(),
        dut=None,
        station=None)
    for key, value in resolved_options.items():
      setattr(self._cached_options, key, value)

    self._cached_options.CheckValid()
    return self._cached_options

  @property
  def state_instance(self):
    return self._state_instance

  @state_instance.setter
  def state_instance(self, state_instance):
    self._state_instance = state_instance
    self.ToFactoryTestList().state_instance = state_instance

  @property
  def state_change_callback(self):
    return self.ToFactoryTestList().state_change_callback

  @state_change_callback.setter
  def state_change_callback(self, state_change_callback):
    self._state_change_callback = state_change_callback
    self.ToFactoryTestList().state_change_callback = state_change_callback


class BasePatch(metaclass=abc.ABCMeta):
  """Base class of patches with different actions."""

  @type_utils.ClassProperty
  @abc.abstractmethod
  def action_name(self):
    raise NotImplementedError

  def __init__(self, test, args):
    if not self._CheckArguments(args):
      raise PatchArgumentError(
          f'Invalid arguments for {self.action_name}: {args:!r}')
    self.test = test
    self.args = args

  @abc.abstractmethod
  def _CheckArguments(self, args):
    raise NotImplementedError

  @abc.abstractmethod
  def Apply(self):
    raise NotImplementedError


class SkipPatch(BasePatch):
  """Patch class to handle skipping tests."""

  @type_utils.ClassProperty
  def action_name(self):
    return 'skip'

  def Apply(self):
    """Marks the test as skipped.

    The test (and its subtests) statuses will become SKIPPED if they were not
    PASSED.  And test.run_if will become constant false.  So Goofy will always
    skip it.
    """
    self.test.Skip(forever=True)

  def _CheckArguments(self, args):
    return args == {}


class WaivePatch(BasePatch):
  """Patch class to handle waiving tests."""

  @type_utils.ClassProperty
  def action_name(self):
    return 'waive'

  def Apply(self):
    """Marks the test and its subtests as waived.

    subtests should also be waived, so that subtests will become
    FAILED_AND_WAIVED when failed.  And the status will be propagated to
    parents (this test).
    """
    self.test.Waive()

  def _CheckArguments(self, args):
    return args == {}


class RetriesPatch(BasePatch):
  """Patch class to set retry times of tests."""

  @type_utils.ClassProperty
  def action_name(self):
    return 'set_retries'

  def Apply(self):
    """Sets the retry times of the given test.

      The argument `times` must be given, for example:

      {
        "action": "set_retries",
        "args": {
          "times": 5
        },
        "conditions": {
          "patterns": [
            "SMT.*"
          ]
        }
      }

      With the above patch, all the retry times of non-group tests with prefix
      `SMT.` will be set to 5.

      NOTE: setting retries with `conditional_patches` will only apply to
      the non-group tests.
    """
    times = self.args['times']

    if self.test.IsGroup():
      return

    self.test.SetRetries(times, set_default=True)

  def _CheckArguments(self, args):
    return args.get('times', False)
