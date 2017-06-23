#!/usr/bin/python -u
# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
import yaml
import factory_common  # pylint: disable=unused-import

from cros.factory.hwid.v3.rule import Context
from cros.factory.hwid.v3.rule import GetContext
from cros.factory.hwid.v3.rule import GetLogger
from cros.factory.hwid.v3.rule import PlainTextValue
from cros.factory.hwid.v3.rule import RangeNumValue
from cros.factory.hwid.v3.rule import RegExpValue
from cros.factory.hwid.v3.rule import Rule
from cros.factory.hwid.v3.rule import RuleException
from cros.factory.hwid.v3.rule import RuleFunction
from cros.factory.hwid.v3.rule import SetContext


@RuleFunction(['string'])
def StrLen():
  return len(GetContext().string)


@RuleFunction(['string'])
def AssertStrLen(length):
  logger = GetLogger()
  if len(GetContext().string) <= length:
    logger.Error('Assertion error')


class HWIDRuleTest(unittest.TestCase):

  def setUp(self):
    self.context = Context(string='12345')

  def testRule(self):
    rule = Rule(name='foobar1',
                when='StrLen() > 3',
                evaluate='AssertStrLen(3)',
                otherwise=None)
    self.assertEquals(None, rule.Evaluate(self.context))
    rule = Rule(name='foobar2',
                when='StrLen() > 3',
                evaluate='AssertStrLen(6)',
                otherwise='AssertStrLen(8)')
    self.assertRaisesRegexp(
        RuleException, r'ERROR: Assertion error', rule.Evaluate, self.context)
    rule = Rule(name='foobar2',
                when='StrLen() > 6',
                evaluate='AssertStrLen(6)',
                otherwise='AssertStrLen(8)')
    self.assertRaisesRegexp(
        RuleException, r'ERROR: Assertion error', rule.Evaluate, self.context)

  def testPlainTextValue(self):
    self.assertTrue(PlainTextValue('foo').Matches('foo'))
    self.assertFalse(PlainTextValue('foo').Matches('bar'))
    self.assertTrue(PlainTextValue('foo').Matches(RegExpValue('^fo*$')))

  def testRegExpValue(self):
    self.assertTrue(RegExpValue('^foo.*bar$').Matches('fooxyzbar'))
    self.assertFalse(RegExpValue('^foo.*bar$').Matches('barxyzfoo'))
    self.assertTrue(
        RegExpValue('^foo.*bar$').Matches(PlainTextValue('fooxyzbar')))
    self.assertFalse(
        RegExpValue('^foo.*bar$').Matches(RegExpValue('fooxyzbar')))
    self.assertTrue(
        RegExpValue('^foo.*bar$').Matches(RegExpValue('^foo.*bar$')))

  def testRangeNumValue(self):
    for cls in [str, PlainTextValue]:
      self.assertFalse(RangeNumValue('== 5').Matches(cls('4')))
      self.assertTrue(RangeNumValue('== 5').Matches(cls('5')))
      self.assertFalse(RangeNumValue('== 5').Matches(cls('6')))

      self.assertFalse(RangeNumValue('>= 5').Matches(cls('4')))
      self.assertTrue(RangeNumValue('>= 5').Matches(cls('5')))
      self.assertTrue(RangeNumValue('>= 5').Matches(cls('6')))

      self.assertFalse(RangeNumValue('> 5').Matches(cls('4')))
      self.assertFalse(RangeNumValue('> 5').Matches(cls('5')))
      self.assertTrue(RangeNumValue('> 5').Matches(cls('6')))

      self.assertTrue(RangeNumValue('<= 5').Matches(cls('4')))
      self.assertTrue(RangeNumValue('<= 5').Matches(cls('5')))
      self.assertFalse(RangeNumValue('<= 5').Matches(cls('6')))

      self.assertTrue(RangeNumValue('< 5').Matches(cls('4')))
      self.assertFalse(RangeNumValue('< 5').Matches(cls('5')))
      self.assertFalse(RangeNumValue('< 5').Matches(cls('6')))

      self.assertFalse(RangeNumValue('[] 5 10').Matches(cls('3')))
      self.assertTrue(RangeNumValue('[] 5 10').Matches(cls('5')))
      self.assertTrue(RangeNumValue('[] 5 10').Matches(cls('7')))
      self.assertTrue(RangeNumValue('[] 5 10').Matches(cls('10')))
      self.assertFalse(RangeNumValue('[] 5 10').Matches(cls('11')))

    self.assertTrue(RangeNumValue('[] 5 10').Matches(RangeNumValue('[] 5 10')))
    self.assertFalse(RangeNumValue('[] 5 10').Matches(RangeNumValue('[] 5 1')))
    self.assertFalse(RangeNumValue('[] 5 10').Matches(RegExpValue('^[] 5 10$')))

  def testYAMLParsing(self):
    SetContext(self.context)
    self.assertRaisesRegexp(
        SyntaxError, r'unexpected EOF while parsing', yaml.load("""
            !rule
            name: foobar1
            when: StrLen() > 3
            evaluate: AssertStrLen(5
        """).Validate)
    self.assertRaisesRegexp(
        SyntaxError, r'invalid syntax \(<string>, line 1\)', yaml.load("""
            !rule
            name: foobar1
            when: StrLen( > 3
            evaluate: AssertStrLen(5)
        """).Validate)

    rule = yaml.load("""
        !rule
        name: foobar2
        when: StrLen() > 3
        evaluate: AssertStrLen(3)
    """)
    self.assertEquals(None, rule.Evaluate(self.context))

    rule = yaml.load("""
        !rule
        name: foobar2
        when: StrLen() > 3
        evaluate: AssertStrLen(6)
    """)
    self.assertRaisesRegexp(
        RuleException, r'ERROR: Assertion error', rule.Evaluate, self.context)

  def testEvaluateOnce(self):
    self.assertEquals(5, Rule.EvaluateOnce('StrLen()', self.context))
    self.assertRaisesRegexp(
        RuleException, r'ERROR: Assertion error',
        Rule.EvaluateOnce, 'AssertStrLen(6)', self.context)

if __name__ == '__main__':
  unittest.main()
