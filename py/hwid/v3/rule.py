# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Base classes of rule language implementation.

For metaclasses used to provide constructors and representers to the YAML
parser, please reference:

http://pyyaml.org/wiki/PyYAMLDocumentation#Constructorsrepresentersresolvers

for some examples.
"""

import abc
import collections
import functools
import logging
import re
import threading
import time
from typing import Mapping, Optional, Sequence, Tuple, Union

from cros.factory.utils import type_utils


_rule_functions = {}


class RuleException(Exception):
  pass


class RuleLogger:
  """A logger for tracing the evaluation of rules.

  Attributes:
    info: Logs with INFO tag.
    warning: Logs with WARNING tag.
    error: Logs with ERROR tag.
  """
  VALID_TAGS = set(['info', 'warning', 'error'])
  LogEntry = collections.namedtuple('LogEntry', ['time_stamp', 'message'])

  def __init__(self):
    self.info = []
    self.warning = []
    self.error = []

  def Log(self, tag, message):
    """Log a message with the given tag with a timestamp.

    Args:
      tag: The tag of the given message. Must be one of ('info', 'warning',
          'error').
      message: A string indicating the message to log.
    """
    if tag not in RuleLogger.VALID_TAGS:
      raise RuleException(f'Invalid logging tag: {tag!r}')
    getattr(self, tag).append(
        RuleLogger.LogEntry(time.time(), f'{tag.upper()}: {message}'))

  def Info(self, message):
    self.Log('info', message)

  def Warning(self, message):
    self.Log('warning', message)

  def Error(self, message):
    self.Log('error', message)

  def Dump(self):
    """Dumps the log in chronological order to a string."""
    logs = sorted(self.info + self.warning + self.error)
    return '\n' + '\n'.join(log.message for log in logs)

  def Reset(self):
    """Resets the logger by cleaning all the log messages."""
    self.info = []
    self.warning = []
    self.error = []


class Context:
  """A class for holding the context objects for evaluating rule functions.

  It converts its constructor's input key-value pairs to the object's
  attributes.
  """

  def __init__(self, **kwargs):
    for key, value in kwargs.items():
      setattr(self, key, value)


# A thread-local object to hold the context object and a logger for rule
# evaluation.
_context = threading.local()
_context.value = None
_context.logger = RuleLogger()


def GetContext():
  """API to get the Context object."""
  return _context.value


def GetLogger():
  """API to get the RuleLogger object."""
  return _context.logger


def SetContext(context):
  """API to set the Context object. Logger should also be cleared."""
  if not isinstance(context, (type(None), Context)):
    raise RuleException('SetContext only accepts Context object')
  _context.value = context
  _context.logger.Reset()


def RuleFunction(ctx_list):
  """Decorator method to specify and check context for rule functions.

  It also registers the decorated rule function to the _rule_functions dict.
  The dict can then be used as the globals to evaluate Python expressions of
  rule functions.

  For example:

    @RuleFunction(['foo'])
    def RuleFunctionBar(...)
      ...

  This will do:
    1. Register 'RuleFunctionBar' to _rule_functions so it'll be parsed as a
       valid rule function.
    2. Before 'RuleFunctionBar' is evaluated, it'll check that the Context
       object has an attribute 'foo' in it.

  Args:
    ctx_list: A list of strings indicating the context that the rule function
        operates under. The Context object being loaded during the rule function
        evaluation must have these context attributes.

  Raises:
    ValueError if the Context object does not have all the required context
    attributes.
  """

  def Wrapped(fn):

    def RuleFunctionRepr(*args, **kwargs):
      """A method to dump a string to represent the rule function being called.
      """
      result = ''.join([
          f'{fn.__name__}(', ', '.join(f'{arg!r}' for arg in args),
          ', '.join(f'{key!r}={value!r}' for key, value in kwargs.items()), ')'
      ])
      return result

    @functools.wraps(fn)
    def ContextAwareFunction(*args, **kwargs):
      context = GetContext()
      for ctx in ctx_list:
        if not getattr(context, ctx, None):
          raise ValueError(f'{ctx!r} not found in context')
      result = fn(*args, **kwargs)
      # Log the rule function being evaluated and its result.
      GetLogger().Info(f'  {RuleFunctionRepr(*args, **kwargs)}: {result!r}')
      return result

    if fn.__name__ in _rule_functions:
      raise KeyError(f'Re-defining rule function {fn.__name__!r}')
    _rule_functions[fn.__name__] = ContextAwareFunction
    return ContextAwareFunction

  return Wrapped


class Rule:
  """The Rule class.

  Rule objects should be called through the Evaluate method. Depending on the
  rule functions being called, proper Context objects could be needed to
  evaluate some Rule objects.

  Args:
    name: The name of this rule as a string.
    when: A Python expression as the execution condition of the rule. The
        expression should evaluate to True or False.
    evaluate: A list of Python expressions to evaluate if 'when' evalutes to
        True.
    otherwise: A list of Python expressions to evaluate if 'when' evaluates to
        False.
  """

  def __init__(self, name, evaluate, when=None, otherwise=None):
    if otherwise and not when:
      raise RuleException(
          f"'when' must be specified along with 'otherwise' in {name!r}")

    self.name = name
    self.when = when
    self.evaluate = evaluate
    self.otherwise = otherwise

  def __eq__(self, rhs):
    return isinstance(rhs, Rule) and self.__dict__ == rhs.__dict__

  def __ne__(self, rhs):
    return not self == rhs

  @classmethod
  def CreateFromDict(cls, rule_dict):
    """Creates a Rule object from the given dict.

    The dict should look like:

      {
        'name': 'namespace.rule.name'
        'when': 'SomeRuleFunction(...)'
        'evaluate': [
            'RuleFunction1(...)',
            'RuleFunction2(...)'
        ]
        'otherwise': [
            'RuleFunction3(...)',
            'RuleFunction4(...)'
        ]
      }

    with 'when' and 'otherwise' being optional.
    """
    for field in ('name', 'evaluate'):
      if not rule_dict.get(field):
        raise RuleException(f'Required field {field!r} not specified')
    return Rule(rule_dict['name'], rule_dict['evaluate'],
                when=rule_dict.get('when'),
                otherwise=rule_dict.get('otherwise'))

  def ExportToDict(self):
    """Exports this rule to a dict.

    Returns:
      A dictionary which can be converted to an instance of Rule back by
      `CreateFromDict` method.
    """
    ret = {}
    ret['name'] = self.name
    ret['evaluate'] = self.evaluate
    if self.when is not None:
      ret['when'] = self.when
    if self.otherwise is not None:
      ret['otherwise'] = self.otherwise
    return ret

  def Validate(self):
    otherwise = (
        type_utils.MakeList(self.otherwise)
        if self.otherwise is not None else [])
    for expr in (type_utils.MakeList(self.when) +
                 type_utils.MakeList(self.evaluate) + otherwise):
      try:
        _Eval(expr, {})
      except KeyError:
        continue

  def Evaluate(self, context):
    """Evalutes the Rule object.

    Args:
      context: A Context object.

    Raises:
      RuleException if evaluation fails.
    """
    logger = GetLogger()

    def EvaluateAllFunctions(function_list):
      for function in function_list:
        try:
          logger.Info(function)
          _Eval(function, {})
        except Exception as e:
          raise RuleException(
              f'Evaluation of {function!r} in rule {self.name!r} failed: {e!r}'
          ) from None

    try:
      SetContext(context)
      logger.Info(f'Checking rule {self.name!r}')
      if self.when is not None:
        logger.Info("Evaluating 'when':")
        logger.Info(f'{self.when}')
        if _Eval(self.when, {}):
          logger.Info("Evaluating 'evaluate':")
          EvaluateAllFunctions(type_utils.MakeList(self.evaluate))
        elif self.otherwise is not None:
          logger.Info("Evaluating 'otherwise':")
          EvaluateAllFunctions(type_utils.MakeList(self.otherwise))
      else:
        logger.Info("Evaluating 'evaluate':")
        EvaluateAllFunctions(type_utils.MakeList(self.evaluate))
    finally:
      if logger.error:
        raise RuleException(logger.Dump() +
                            f'\nEvaluation of rule {self.name!r} failed')
      logging.debug(logger.Dump())
      SetContext(None)

  @classmethod
  def EvaluateOnce(cls, expr, context):
    """Evaluate the given expr under the given context once.

    Args:
      expr: A string of Python expression.
      context: A Context object.

    Returns:
      The retrun value of evaluation of expr.
    """
    logger = GetLogger()
    try:
      SetContext(context)
      return _Eval(expr, {})
    finally:
      if logger.error:
        raise RuleException(logger.Dump())
      logging.debug(logger.Dump())
      SetContext(None)


class Value:
  """A class to hold a value for expression evaluation.

  The value can be a plain string or a regular expression.

  Attributes:
    raw_value: A string of value or None.
    is_re: If True, raw_value is treated as a regular expression in expression
        evaluation.
  """

  def __init__(self, raw_value, is_re=False):
    self.raw_value = raw_value
    self.is_re = is_re

  def Matches(self, operand):
    """Matches the value of operand.

    The value to be matched depends on the type of operand. If it is Value,
    matches its 'raw_value'; otherwise, matches itself.

    The way to match operand depends on the instance's 'is_re' attribute. If
    'is_re' is True, it checks if the target matches the regular expression.
    Otherwise, a string comparison is used.

    Args:
      operand: The operand to match with.

    Returns:
      True if self matches operand, False otherwise.
    """
    if isinstance(operand, Value):
      if operand.is_re:
        # If operand is a regular expression Value object, compare with __eq__
        # directly.
        return self.__eq__(operand)
      operand = operand.raw_value
    if self.is_re:
      return re.fullmatch(self.raw_value, operand) is not None
    return self.raw_value == operand

  def __eq__(self, operand):
    return isinstance(operand, Value) and self.__dict__ == operand.__dict__

  def __ne__(self, operand):
    return not self == operand

  def __repr__(self):
    return (
        f'{self.__class__.__name__}({self.raw_value!r}, is_re={self.is_re!r})')


class InternalTags:
  """A parent class of internal tags."""


class _NoneCheckable(abc.ABC):

  @abc.abstractmethod
  def NoneCheck(self, method_name: str):
    """Check if the wrapped value is None."""


def _WrapWithNonCheck(method):

  @functools.wraps(method)
  def _WrappedMethod(self: _NoneCheckable, *args, **kwargs):
    self.NoneCheck(method.__name__)
    return method(self, *args, **kwargs)

  return _WrappedMethod


def _NoneCheckMethodsWrapper(method_names: Tuple[str, ...]):

  def _ClassWrapper(cls):
    for method_name in method_names:
      original_method = getattr(cls, method_name)
      setattr(cls, method_name, _WrapWithNonCheck(original_method))
    return cls

  return _ClassWrapper


_COMMON_ORDEREDDICT_METHODS = (
    '__contains__',
    '__delitem__',
    '__getitem__',
    '__iter__',
    '__len__',
    '__setitem__',
    'clear',
    'get',
    'items',
    'keys',
    'move_to_end',
    'pop',
    'popitem',
    'setdefault',
    'update',
    'values',
)


@_NoneCheckMethodsWrapper(_COMMON_ORDEREDDICT_METHODS)
class AVLProbeValue(collections.OrderedDict, InternalTags, _NoneCheckable):
  """A class which holds the probe values linked with the ones on AVL.

  To be compatible with the OrderedDict as in ComponentInfo.values, this class
  adds a field `value_is_none` which is set to True when it wraps a None value.

  To avoid incorrectly calling methods of an AVLProbeValue instance wrapping a
  None value, this class adds checks to most of the dict related methods which
  will raise ValueError when `value_is_none` is True.
  """

  def __init__(self, identifier: Optional[str], probe_value_matched: bool,
               values: Optional[collections.OrderedDict], *args, **kwargs):
    # As the __init__ method might call __setitem__, we need to set
    # the _value_is_none field before it, or the NoneCheck method in __setitem__
    # call might raise AttributeError.
    self._value_is_none = IsComponentValueNone(values)
    if self._value_is_none:
      values = {}
    super().__init__(values, *args, **kwargs)
    self._converter_identifier = identifier
    self._probe_value_matched = probe_value_matched

  def __eq__(self, rhs):
    return (self.__class__ is rhs.__class__ and
            self._value_is_none == rhs._value_is_none and
            super().__eq__(rhs) and
            self.converter_identifier == rhs.converter_identifier and
            self.probe_value_matched == rhs.probe_value_matched)

  @property
  def converter_identifier(self) -> Optional[str]:
    return self._converter_identifier

  @property
  def probe_value_matched(self) -> bool:
    return self._probe_value_matched

  @property
  def value_is_none(self) -> bool:
    return self._value_is_none

  def __reduce__(self):
    # As we raise ValueError when self._value_is_none is True, the state we
    # serialized is customized instead of calling super().__reduce__() which
    # will call self.items().

    # A callable object to create the instance.
    state_0 = self.__class__

    # Arguments for the callable object.
    state_1 = (self._converter_identifier, self._probe_value_matched,
               None if self._value_is_none else collections.OrderedDict(self))

    # The instance state.
    state_2 = self.__dict__

    return (state_0, state_1, state_2)

  def NoneCheck(self, method_name: str):
    if self._value_is_none:
      raise ValueError(f'None check fails at method {method_name!r}.  Use '
                       '`ComponentInfo.value_is_none` instead of '
                       '`ComponentInfo.value is None` to check if this value '
                       'is None.')


def IsComponentValueNone(
    values: Union[AVLProbeValue, Optional[Mapping]]) -> bool:
  return values is None or (isinstance(values, AVLProbeValue) and
                            values.value_is_none)


class FromFactoryBundle(collections.OrderedDict, InternalTags):
  """A class indicates the component is extracted from a factory bundle."""

  def __init__(self, bundle_uuids: Optional[Sequence[str]], *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._bundle_uuids = bundle_uuids or []

  @property
  def bundle_uuids(self):
    return self._bundle_uuids

  def __eq__(self, rhs):
    return (self.__class__ is rhs.__class__ and super().__eq__(rhs) and
            set(self.bundle_uuids) == set(rhs.bundle_uuids))


def _Eval(expr, local):
  # Lazy import to avoid circular import problems.
  # These imports are needed to make sure all the rule functions needed by
  # HWID-related operations are loaded and initialized.
  import cros.factory.hwid.v3.common_rule_functions  # pylint: disable=unused-import
  import cros.factory.hwid.v3.hwid_rule_functions
  return eval(expr, _rule_functions, local)  # pylint: disable=eval-used
