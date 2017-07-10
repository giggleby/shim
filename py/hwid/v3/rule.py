# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Base classes of rule language implementation.

For metaclasses used to provide constructors and representers to the YAML
parser, please reference:

http://pyyaml.org/wiki/PyYAMLDocumentation#Constructorsrepresentersresolvers

for some examples.
"""

import collections
import inspect
import logging
import re
import threading
import time
import factory_common  # pylint: disable=W0611

from cros.factory.utils import type_utils
from cros.factory.utils import yaml_utils


_rule_functions = {}


class RuleException(Exception):
  pass


class RuleLogger(object):
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
      raise RuleException('Invalid logging tag: %r' % tag)
    getattr(self, tag).append(RuleLogger.LogEntry(
        time.time(), '%s: %s' % (tag.upper(), message)))

  def Info(self, message):
    self.Log('info', message)

  def Warning(self, message):
    self.Log('warning', message)

  def Error(self, message):
    self.Log('error', message)

  def Dump(self):
    """Dumps the log in chronological order to a string."""
    logs = sorted(self.info + self.warning + self.error)
    return '\n' + '\n'.join([log.message for log in logs])

  def Reset(self):
    """Resets the logger by cleaning all the log messages."""
    self.info = []
    self.warning = []
    self.error = []


class Context(object):
  """A class for holding the context objects for evaluating rule functions.

  It converts its constructor's input key-value pairs to the object's
  attributes.
  """

  def __init__(self, **kwargs):
    for key, value in kwargs.iteritems():
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
          '%s(' % fn.__name__,
          ', '.join(['%r' % arg for arg in args]),
          ', '.join(['%r=%r' % (key, value) for key, value in kwargs.items()]),
          ')'])
      return result

    def ContextAwareFunction(*args, **kwargs):
      context = GetContext()
      for ctx in ctx_list:
        if not getattr(context, ctx, None):
          raise ValueError('%r not found in context' % ctx)
      result = fn(*args, **kwargs)
      # Log the rule function being evaluated and its result.
      GetLogger().Info('  %s: %r' % (RuleFunctionRepr(*args, **kwargs), result))
      return result

    if fn.__name__ in _rule_functions:
      raise KeyError('Re-defining rule function %r' % fn.__name__)
    _rule_functions[fn.__name__] = ContextAwareFunction
    return ContextAwareFunction
  return Wrapped


class RuleMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """The metaclass for Rule class.

  This metaclass registers YAML constructor and representer to decode from YAML
  tag '!rule' and data to a Rule object, and to encode a Rule object to its
  corresponding YAML representation.
  """
  YAML_TAG = '!rule'

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    value = loader.construct_mapping(node, deep=True)
    for field in ('name', 'evaluate'):
      if not value.get(field):
        raise RuleException('Required field %r not specified' % field)
    if value.get('otherwise') and not value.get('when'):
      raise RuleException(
          "'when' must be specified along with 'otherwise' in %r" %
          value['name'])
    return Rule(value['name'], value.get('when'), value['evaluate'],
                value.get('otherwise'))

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_mapping(mcs.YAML_TAG, data.__dict__)


class Rule(object):
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
  __metaclass__ = RuleMetaclass

  def __init__(self, name, when, evaluate, otherwise):
    self.name = name
    self.when = when
    self.evaluate = type_utils.MakeList(evaluate)
    if otherwise:
      self.otherwise = type_utils.MakeList(otherwise)
    else:
      self.otherwise = None

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
        raise RuleException('Required field %r not specified' % field)
    if rule_dict.get('otherwise') and not rule_dict.get('when'):
      raise RuleException(
          "'when' must be specified along with 'otherwise' in %r" %
          rule_dict['name'])
    return Rule(rule_dict['name'], rule_dict.get('when'), rule_dict['evaluate'],
                rule_dict.get('otherwise'))

  def Validate(self):
    for expr in (type_utils.MakeList(self.when) + self.evaluate +
                 type_utils.MakeList(self.otherwise)):
      try:
        eval(expr, _rule_functions, {})  # pylint: disable=eval-used
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
          logger.Info('%s' % function)
          eval(function, _rule_functions, {})  # pylint: disable=eval-used
        except Exception as e:
          raise RuleException(
              'Evaluation of %r in rule %r failed: %r' %
              (function, self.name, e))
    try:
      SetContext(context)
      logger.Info('Checking rule %r' % self.name)
      if self.when is not None:
        logger.Info("Evaluating 'when':")
        logger.Info('%s' % self.when)
        if eval(self.when, _rule_functions, {}):  # pylint: disable=eval-used
          logger.Info("Evaluating 'evaluate':")
          EvaluateAllFunctions(self.evaluate)
        elif self.otherwise is not None:
          logger.Info("Evaluating 'otherwise':")
          EvaluateAllFunctions(self.otherwise)
      else:
        logger.Info("Evaluating 'evaluate':")
        EvaluateAllFunctions(self.evaluate)
    finally:
      if logger.error:
        raise RuleException(logger.Dump() +
                            '\nEvaluation of rule %r failed' % self.name)
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
      return eval(expr, _rule_functions, {})  # pylint: disable=eval-used
    finally:
      if logger.error:
        raise RuleException(logger.Dump())
      logging.debug(logger.Dump())
      SetContext(None)


class Value(object):
  """The base class to hold a value for expression evaluation.

  Attributes:
    raw_value: A string of value or None.
  """
  def __init__(self, raw_value):
    self.raw_value = raw_value

  def Matches(self, operand):
    """Matches the value of operand.

    Args:
      operand: The operand to match with.

    Returns:
      True if self matches operand, False otherwise.
    """
    raise NotImplementedError()

  def __repr__(self):
    return '%s(%r)' % (self.__class__.__name__, self.raw_value)

  def __eq__(self, rhs):
    return (isinstance(rhs, Value) and
            self.raw_value == rhs.raw_value and
            self.__class__ == rhs.__class__)

  def __ne__(self, rhs):
    return not self == rhs


class PlainTextMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """Metaclass for dumping plain text Value object.

  This metaclass registers YAML representer to encode a PlainTextValue object
  to its corrosponding YAML representation, i.e. like a normal python string.
  """
  # TODO(yhong): Finds a way to remove this dummy tag.
  #   Currently the hwid database loading flow in database.py is:
  #     1. Call yaml.load() to load the yaml file.  Fields starts with special
  #         tag will be loaded as corrosponding type.
  #     2. For those value without special tag, database.py wraps those value
  #         into PlainTextValue manually.
  #   As the result, PlainTextValue will never be created by yaml loader, but
  #       an instance of PlainTextValue should be able to dump to yaml object
  #       like a normal python string.  The above flow is derived from the work
  #       flow before refactor, but it still not a good way.
  YAML_TAG = '!just_a_fake_tag'

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_data(data.raw_value)


class PlainTextValue(Value, str):
  """The calss to hold a plain text value for expression evaluation."""
  __metaclass__ = PlainTextMetaclass

  def Matches(self, operand):
    """Matches the value of operand with raw_value.

    The value to be matched depends on the type of operand. If it is Value,
    it use operand.Matches to match instead; otherwise it just compare the
    raw_value with the operand.
    """
    if isinstance(operand, Value):
      return operand.Matches(self.raw_value)
    return self.raw_value == operand


class RegExpMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """Metaclass for creating regular expression-enabled Value object.

  This metaclass registers YAML constructor and representer to decode from YAML
  tag '!re' and data to a Value object, and to encode a Value object to its
  corresponding YAML representation.
  """
  YAML_TAG = '!re'

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    value = loader.construct_scalar(node)
    return RegExpValue(value)

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_scalar(mcs.YAML_TAG, data.raw_value)


class RegExpValue(Value):
  """A class to hold a regular expression value for expression evaluation."""
  __metaclass__ = RegExpMetaclass

  def Matches(self, operand):
    """Matches the value of operand by the regular expression.

    The match rules are listed as following:
      - If the operand is an instance of PlainTextValue, the function matchs
          with operand.raw_value.
      - If the operand is also an instance of RegExpValue, compare the raw
          regular expression directly.
      - If the operand is an instance of Value but not fits above rules,
          always trick this case as unmatched.
      - Otherwise, use the ragular expression to match the operand.
    """
    if isinstance(operand, RegExpValue):
      return self.raw_value == operand.raw_value

    if isinstance(operand, PlainTextValue):
      return self.Matches(operand.raw_value)

    if isinstance(operand, Value):
      return False

    return re.match(self.raw_value, operand) is not None


class RangeNumMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """Metaclass for creating a Value object responsed for number within a range.

  This metaclass registers YAML constructor and representer to decode from YAML
  tag '!num' and data to a Value object, and to encode a Value object to its
  corresponding YAML representation.
  """
  YAML_TAG = '!num'

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    value = loader.construct_scalar(node)
    return RangeNumValue(value)

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_scalar(mcs.YAML_TAG, data.raw_value)


class RangeNumValue(Value):
  """A class to hold a regular expression value for expression evaluation."""
  __metaclass__ = RangeNumMetaclass

  _MATCH_FUNCTIONS = {
    '>=': lambda my_value, operand: operand >= my_value,
    '==': lambda my_value, operand: operand == my_value,
    '<=': lambda my_value, operand: operand <= my_value,
    '>': lambda my_value, operand: operand > my_value,
    '<': lambda my_value, operand: operand < my_value,
    '[]': lambda my_value1, my_value2, operand: \
        my_value1 <= operand <= my_value2,
  }

  def __init__(self, raw_value):
    super(RangeNumValue, self).__init__(raw_value)

    words = [word for word in raw_value.split(' ') if word]

    if len(words) < 1:
      raise ValueError('No operator found')
    operator, words = words[0], words[1:]

    self._match_func = self._MATCH_FUNCTIONS.get(operator, None)
    if not self._match_func:
      raise ValueError('Invalid operator: %s' % operator)

    num_args = len(inspect.getargspec(self._match_func).args) - 1
    if len(words) != num_args:
      raise ValueError('Number of arguments of operator %r should be %d, got %d'
                       % (operator, num_args, len(words)))

    self._match_func_args = [float(word) for word in words]

  def Matches(self, operand):
    """Checks if the given value is in the specific value.

    The match rules are listed as following:
      - If the operand is an instance of PlainTextValue, the function matchs
          with operand.raw_value.
      - If the operand is also an instance of RangeNumValue, compare the
          raw_value directly.
      - If the operand is an instance of Value but not fits above rules,
          always trick this case as unmatched.
      - Otherwise, use the number comparasion.
    """
    if isinstance(operand, PlainTextValue):
      return self.Matches(operand.raw_value)

    if isinstance(operand, RangeNumValue):
      return self.raw_value == operand.raw_value

    if isinstance(operand, Value):
      return False

    return self._match_func(*(self._match_func_args + [float(operand)]))
