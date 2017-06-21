# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

import factory_common  # pylint: disable=unused-import
from cros.factory.probe import function
from cros.factory.utils.arg_utils import Arg


class MatchFunction(function.Function):
  """Filter the results which does not match the rule.

  The rule might be a dict or a string. A result is matched if every value of
  the rule is matched. If the rule is a string, then the matched result should
  only contain one item and the value is matched to the string.

  If the string starts with "!re ", then the remaining string is treated as a
  regular expression.

  If the string starts with "!num ", the probed value will be treated as
  floating point number, and the remaining of rule string should be
  "< '==' | '>' | '<' | '>=' | '<=' | '!=' > ' ' NUMBER", e.g. "!num >= 10".

  Otherwise, the value of the result should be the same.
  """

  REGEX_PREFIX = '!re '
  NUM_CMP_PREFIX = '!num '
  NUM_CMP_OPERATOR = set(['==', '>', '<', '>=', '<=', '!='])

  ARGS = [
      Arg('rule', (str, dict), 'The matched rule.')]

  def __init__(self, **kwargs):
    super(MatchFunction, self).__init__(**kwargs)

    self.is_dict = isinstance(self.args.rule, dict)
    if self.is_dict:
      self.args.rule = {key: self.ConstructRule(value)
                        for key, value in self.args.rule.iteritems()}
    else:
      self.args.rule = self.ConstructRule(self.args.rule)

  def Apply(self, data):
    return filter(self.Match, data)

  def Match(self, item):
    def _Match(matcher, value):
      return matcher(value)

    if not self.is_dict:
      return len(item) == 1 and _Match(self.args.rule, item.values()[0])
    else:
      return all([key in item and _Match(rule, item[key])
                  for key, rule in self.args.rule.iteritems()])

  @classmethod
  def ConstructRule(cls, rule):
    transformers = [cls.TryTransferRegex, cls.TryTransferNumberCompare]

    for transformer in transformers:
      matcher = transformer(rule)
      if matcher:
        return matcher
    return lambda v: v == rule

  @classmethod
  def TryTransferRegex(cls, value):
    assert isinstance(value, str)
    if value.startswith(cls.REGEX_PREFIX):
      regexp = re.compile(value[len(cls.REGEX_PREFIX):])
      def matcher(v):
        try:
          return regexp.match(v) is not None
        except TypeError:
          return False
      return matcher
    return None

  @classmethod
  def TryTransferNumberCompare(cls, value):
    assert isinstance(value, str)
    if value.startswith(cls.NUM_CMP_PREFIX):
      op, unused_sep, num = value[len(cls.NUM_CMP_PREFIX):].partition(' ')
      num = float(num)
      if op not in cls.NUM_CMP_OPERATOR:
        raise ValueError('invalid operator %s' % op)
      def matcher(v):
        v = float(v)
        if op == '==':
          return v == num
        if op == '!=':
          return v != num
        if op == '<':
          return v < num
        if op == '>':
          return v > num
        if op == '<=':
          return v <= num
        if op == '>=':
          return v >= num
      return matcher
    return None
