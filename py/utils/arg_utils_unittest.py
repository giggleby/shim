#!/usr/bin/env python3
#
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import re
import unittest
from unittest import mock

from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.arg_utils import Args
from cros.factory.utils.arg_utils import _DEFAULT_NOT_SET


class EnumTyped_1(str, enum.Enum):
  a = 'a'
  b = 'b'

  def __str__(self) -> str:
    return self.name


class IntEnumTyped(enum.IntEnum):
  num_1 = 1
  num_2 = 2


class ArgTest(unittest.TestCase):

  def setUp(self):
    patcher = mock.patch('argparse.ArgumentParser')
    self.parser = patcher.start()
    self.addCleanup(patcher.stop)

  def testIsOptional(self):
    int_arg_1 = Arg('int_arg_1', int, 'X')
    self.assertFalse(int_arg_1.IsOptional())
    int_arg_2 = Arg('int_arg_2', int, 'X', default=0)
    self.assertTrue(int_arg_2.IsOptional())

  def testValueMatchesType_int(self):
    int_arg = Arg('int_arg', int, 'X')
    self.assertTrue(int_arg.ValueMatchesType(0))
    self.assertFalse(int_arg.ValueMatchesType('0'))

  def testValueMatchesType_Enum(self):
    enum_arg_1 = Arg('enum_arg_1', EnumTyped_1, 'X')
    self.assertTrue(enum_arg_1.ValueMatchesType(EnumTyped_1.a))
    self.assertTrue(enum_arg_1.ValueMatchesType('a'))
    self.assertFalse(enum_arg_1.ValueMatchesType('c'))
    enum_arg_2 = Arg('enum_arg_2', enum.Enum('EnumTyped_2', ['a', 'b']), 'X')
    self.assertTrue(enum_arg_2.ValueMatchesType('a'))
    self.assertFalse(enum_arg_2.ValueMatchesType('c'))

  def testValueMatchesType_IntEnum(self):
    int_enum_arg = Arg('int_enum_arg', IntEnumTyped, 'X')
    self.assertTrue(int_enum_arg.ValueMatchesType(IntEnumTyped.num_1))
    self.assertTrue(int_enum_arg.ValueMatchesType(2))
    self.assertFalse(int_enum_arg.ValueMatchesType(3))

  def testValueMatchesType_DefaultNone(self):
    int_arg_1 = Arg('int_arg_1', int, 'X')
    self.assertFalse(int_arg_1.ValueMatchesType(None))
    int_arg_2 = Arg('int_arg_2', int, 'X', default=None)
    self.assertTrue(int_arg_2.ValueMatchesType(None))

  def testAddToParser_InvalidType(self):
    self.assertRaisesRegex(
        ValueError,
        r'Arg float_arg cannot be transfered. \(\<class \'float\'\>,\)',
        lambda: Arg('float_arg', float, 'X').AddToParser(self.parser))

  def testAddToParser_Optional(self):
    Arg('int_arg', int, 'X').AddToParser(self.parser)
    self.parser.add_argument.assert_called_with('int_arg', type=int, help='X',
                                                default=_DEFAULT_NOT_SET)
    Arg('int_arg', int, 'X', default=0).AddToParser(self.parser)
    self.parser.add_argument.assert_called_with('--int-arg', type=int, help='X',
                                                default=0)

  def testAddToParser_AddBool(self):
    Arg('bool_arg', bool, 'X').AddToParser(self.parser)
    self.parser.add_argument.assert_called_with(
        'bool_arg', help='X', default=False, action='store_true')
    Arg('bool_arg', bool, 'X', default=True).AddToParser(self.parser)
    self.parser.add_argument.assert_called_with(
        '--no-bool-arg', help='X', default=True, action='store_false')

  def testAddToParser_AddInt(self):
    Arg('int_arg', int, 'X', default=0).AddToParser(self.parser)
    self.parser.add_argument.assert_called_once_with('--int-arg', type=int,
                                                     help='X', default=0)

  def testAddToParser_AddList(self):
    Arg('list_arg', list, 'X').AddToParser(self.parser)
    self.parser.add_argument.assert_called_once_with(
        'list_arg', help='X', default=_DEFAULT_NOT_SET, nargs='*')

  def testAddToParser_AddEnum(self):
    Arg('enum_arg', EnumTyped_1, 'X').AddToParser(self.parser)
    self.parser.add_argument.assert_called_once_with(
        'enum_arg', type=str, help='X', choices={'a',
                                                 'b'}, default=_DEFAULT_NOT_SET)

  def testAddToParser_AddIntEnum(self):
    Arg('int_enum_arg', IntEnumTyped, 'X').AddToParser(self.parser)
    self.parser.add_argument.assert_called_once_with('int_enum_arg', type=int,
                                                     help='X', choices={1, 2},
                                                     default=_DEFAULT_NOT_SET)


class ArgsTest(unittest.TestCase):

  def setUp(self):
    self.parser = None

  def Parse(self, dargs):
    """Parses dargs.

    Returns:
      A dictionary of attributes from the resultant object.
    """
    values = self.parser.Parse(dargs)
    return {k: v for k, v in values.__dict__.items() if not k.startswith('_')}

  def testNone(self):
    self.parser = Args(Arg('int_or_none', int, 'X', default=None))
    self.assertEqual(dict(int_or_none=None), self.Parse({}))
    self.assertEqual(dict(int_or_none=10), self.Parse(dict(int_or_none=10)))

  def testRequired(self):
    self.parser = Args(Arg('required', str, 'X'))
    self.assertEqual(dict(required='x'), self.Parse(dict(required='x')))
    self.assertRaises(ValueError, lambda: self.Parse({}))
    self.assertRaises(ValueError, lambda: self.Parse(dict(required=None)))
    self.assertRaises(ValueError, lambda: self.Parse(dict(required=3)))

  def testOptional(self):
    self.parser = Args(Arg('optional', str, 'X', default=None))
    self.assertEqual(dict(optional=None), self.Parse({}))
    self.assertEqual(dict(optional='y'), self.Parse(dict(optional='y')))

  def testInt(self):
    self.parser = Args(Arg('int_typed', int, 'X', default=0))
    self.assertEqual(dict(int_typed=0), self.Parse({}))
    self.assertEqual(dict(int_typed=3), self.Parse(dict(int_typed=3)))
    self.assertRaises(ValueError, lambda: self.Parse(dict(int_typed='3')))

  def testIntOrString(self):
    self.parser = Args(
        Arg('int_or_string_typed', (int, str), 'X', default=None))
    for value in (3, 'x'):
      self.assertEqual(
          dict(int_or_string_typed=value),
          self.Parse(dict(int_or_string_typed=value)))
    # Wrong type
    self.assertRaises(
        ValueError,
        lambda: self.Parse(dict(required='x', int_or_string_typed=1.0)))

  def testEnum(self):
    self.parser = Args(
        Arg('enum_typed_1', EnumTyped_1, 'X', default=None),
        Arg('enum_typed_2', enum.Enum('EnumTyped_2', 'a b'), 'X', default=None))
    self.assertEqual(
        dict(enum_typed_1=EnumTyped_1.a, enum_typed_2=None),
        self.Parse(dict(enum_typed_1=EnumTyped_1.a)))
    self.assertEqual(
        dict(enum_typed_1='a', enum_typed_2=None),
        self.Parse(dict(enum_typed_1=EnumTyped_1.a)))
    self.assertEqual(
        dict(enum_typed_1='a', enum_typed_2=None),
        self.Parse(dict(enum_typed_1='a')))
    self.assertEqual(
        dict(enum_typed_1=None, enum_typed_2='b'),
        self.Parse(dict(enum_typed_2='b')))

    error_pattern = re.compile(
        r'.*enum_typed_[12].*The argument should have type '
        r'\(\<enum \'EnumTyped_[12]\'\>', re.DOTALL)
    self.assertRaisesRegex(ValueError, error_pattern, self.Parse,
                           dict(enum_typed_1='c'))
    self.assertRaisesRegex(ValueError, error_pattern, self.Parse,
                           dict(enum_typed_2='c'))

  def testIntEnum(self):
    self.parser = Args(Arg('int_enum_typed', IntEnumTyped, 'X', default=None))
    self.assertEqual(
        dict(int_enum_typed=IntEnumTyped.num_1),
        self.Parse(dict(int_enum_typed=IntEnumTyped.num_1)))
    self.assertEqual(
        dict(int_enum_typed=2),
        self.Parse(dict(int_enum_typed=IntEnumTyped.num_2)))

    error_pattern = re.compile(
        r'.*int_enum_typed.*The argument should have type '
        r'\(\<enum \'IntEnumTyped\'\>', re.DOTALL)
    self.assertRaisesRegex(ValueError, error_pattern, self.Parse,
                           dict(int_enum_typed=3))


if __name__ == '__main__':
  unittest.main()
