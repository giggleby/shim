#!/usr/bin/env python3.6
#
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import re
import unittest

from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.arg_utils import Args
from cros.factory.utils.type_utils import Enum


class enum_typed_1(str, enum.Enum):
  a = 'a'
  b = 'b'

  def __str__(self) -> str:
    return self.name


class ArgsTest(unittest.TestCase):

  def setUp(self):
    self.parser = Args(
        Arg('required', str, 'X'),
        Arg('has_default', str, 'X', default='DEFAULT_VALUE'),
        Arg('optional', str, 'X', default=None),
        Arg('int_typed', int, 'X', default=None),
        Arg('int_or_string_typed', (int, str), 'X', default=None),
        Arg('type_util_enum_typed', Enum(['a', 'b']), 'X', default=None),
        Arg('enum_typed_1', enum_typed_1, 'X', default=None),
        Arg('enum_typed_2', enum.Enum('enum_typed_2', 'a b'), 'X',
            default=None))

  def Parse(self, dargs):
    """Parses dargs.

    Returns:
      A dictionary of attributes from the resultant object.
    """
    values = self.parser.Parse(dargs)
    return {k: v for k, v in values.__dict__.items() if not k.startswith('_')}

  def testIntOrNone(self):
    self.parser = Args(
        Arg('int_or_none', (int, type(None)), 'X', default=5))
    self.assertEqual(dict(int_or_none=5), self.Parse({}))
    self.assertEqual(dict(int_or_none=10), self.Parse(dict(int_or_none=10)))
    self.assertEqual(dict(int_or_none=None),
                     self.Parse(dict(int_or_none=None)))

  def testRequired(self):
    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': None,
            'int_or_string_typed': None,
            'int_typed': None,
            'type_util_enum_typed': None,
            'enum_typed_1': None,
            'enum_typed_2': None
        }, self.Parse(dict(required='x')))
    self.assertRaises(ValueError, lambda: self.Parse({}))
    self.assertRaises(ValueError, lambda: self.Parse(dict(required=None)))
    self.assertRaises(ValueError, lambda: self.Parse(dict(required=3)))

  def testOptional(self):
    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': 'y',
            'int_or_string_typed': None,
            'int_typed': None,
            'type_util_enum_typed': None,
            'enum_typed_1': None,
            'enum_typed_2': None
        }, self.Parse(dict(required='x', optional='y')))
    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': None,
            'int_or_string_typed': None,
            'int_typed': None,
            'type_util_enum_typed': None,
            'enum_typed_1': None,
            'enum_typed_2': None
        }, self.Parse(dict(required='x', optional=None)))

  def testInt(self):
    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': None,
            'int_or_string_typed': None,
            'int_typed': 3,
            'type_util_enum_typed': None,
            'enum_typed_1': None,
            'enum_typed_2': None
        }, self.Parse(dict(required='x', int_typed=3)))
    self.assertRaises(ValueError, self.Parse, dict(required='x', int_typed='3'))

  def testEnum(self):
    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': None,
            'int_or_string_typed': None,
            'int_typed': None,
            'type_util_enum_typed': None,
            'enum_typed_1': 'a',
            'enum_typed_2': 'a'
        }, self.Parse(dict(required='x', enum_typed_1='a', enum_typed_2='a')))

    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': None,
            'int_or_string_typed': None,
            'int_typed': None,
            'type_util_enum_typed': None,
            'enum_typed_1': 'b',
            'enum_typed_2': None
        }, self.Parse(dict(required='x', enum_typed_1=enum_typed_1.b)))

    error_pattern = re.compile(
        r'.*enum_typed_[12].*The argument should have type '
        r'\(\<enum \'enum_typed_[12]\'\>', re.DOTALL)
    self.assertRaisesRegex(ValueError, error_pattern, self.Parse,
                           dict(required='x', enum_typed_1='c'))
    self.assertRaisesRegex(ValueError, error_pattern, self.Parse,
                           dict(required='x', enum_typed_2='c'))

  def testTypeUtilEnum(self):
    self.assertEqual(
        {
            'has_default': 'DEFAULT_VALUE',
            'required': 'x',
            'optional': None,
            'int_or_string_typed': None,
            'int_typed': 3,
            'type_util_enum_typed': 'a',
            'enum_typed_1': None,
            'enum_typed_2': None
        }, self.Parse(
            dict(required='x', int_typed=3, type_util_enum_typed='a')))

    error_pattern = re.compile(
        r'.*type_util_enum_typed.*The argument should have type \(Enum',
        re.DOTALL)
    self.assertRaisesRegex(ValueError, error_pattern, self.Parse,
                           dict(required='x', type_util_enum_typed='c'))

  def testIntOrString(self):
    for value in (3, 'x'):
      self.assertEqual(
          {
              'has_default': 'DEFAULT_VALUE',
              'required': 'x',
              'optional': None,
              'int_or_string_typed': value,
              'int_typed': None,
              'type_util_enum_typed': None,
              'enum_typed_1': None,
              'enum_typed_2': None
          }, self.Parse(dict(required='x', int_or_string_typed=value)))
    # Wrong type
    self.assertRaises(
        ValueError,
        self.Parse, dict(required='x', int_or_string_typed=1.0))


if __name__ == '__main__':
  unittest.main()
