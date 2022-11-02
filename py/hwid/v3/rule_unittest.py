#!/usr/bin/env python3
# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.v3 import rule as v3_rule


@v3_rule.RuleFunction(['string'])
def StrLen():
  return len(v3_rule.GetContext().string)


@v3_rule.RuleFunction(['string'])
def AssertStrLen(length):
  logger = v3_rule.GetLogger()
  if len(v3_rule.GetContext().string) <= length:
    logger.Error('Assertion error')


class HWIDRuleTest(unittest.TestCase):

  def setUp(self):
    self.context = v3_rule.Context(string='12345')

  def testRule(self):
    rule = v3_rule.Rule(name='foobar1', when='StrLen() > 3',
                        evaluate='AssertStrLen(3)', otherwise=None)
    self.assertEqual(None, rule.Evaluate(self.context))
    rule = v3_rule.Rule(name='foobar2', when='StrLen() > 3',
                        evaluate='AssertStrLen(6)', otherwise='AssertStrLen(8)')
    self.assertRaisesRegex(v3_rule.RuleException, r'ERROR: Assertion error',
                           rule.Evaluate, self.context)
    rule = v3_rule.Rule(name='foobar2', when='StrLen() > 6',
                        evaluate='AssertStrLen(6)', otherwise='AssertStrLen(8)')
    self.assertRaisesRegex(v3_rule.RuleException, r'ERROR: Assertion error',
                           rule.Evaluate, self.context)

  def testValue(self):
    self.assertTrue(v3_rule.Value('foo').Matches('foo'))
    self.assertFalse(v3_rule.Value('foo').Matches('bar'))
    self.assertTrue(
        v3_rule.Value('^foo.*bar$', is_re=True).Matches('fooxyzbar'))
    self.assertFalse(
        v3_rule.Value('^foo.*bar$', is_re=True).Matches('barxyzfoo'))

  def testEvaluateOnce(self):
    self.assertEqual(5, v3_rule.Rule.EvaluateOnce('StrLen()', self.context))
    self.assertRaisesRegex(v3_rule.RuleException, r'ERROR: Assertion error',
                           v3_rule.Rule.EvaluateOnce, 'AssertStrLen(6)',
                           self.context)


class AVLProbeValueTest(unittest.TestCase):

  def testNoneValues(self):
    apv = v3_rule.AVLProbeValue('identifier', False, None)

    self.assertTrue(apv.value_is_none)
    self.assertRaisesRegex(
        ValueError, "None check fails at method 'items'.  Use "
        '`ComponentInfo.value_is_none` instead of '
        '`ComponentInfo.value is None` to check if this value is None.',
        apv.items)


if __name__ == '__main__':
  unittest.main()
