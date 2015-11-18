# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for data types."""

import collections
import Queue


class Error(Exception):
  """Generic fatal error."""
  pass


class TimeoutError(Error):
  """Timeout error."""
  def __init__(self, message, output=None):
    Error.__init__(self)
    self.message = message
    self.output = output

  def __str__(self):
    return repr(self.message)


class Obj(object):
  """Generic wrapper allowing dot-notation dict access."""

  def __init__(self, **field_dict):
    self.__dict__.update(field_dict)

  def __repr__(self):
    return repr(self.__dict__)


class Enum(frozenset):
  """An enumeration type.

  Usage:
    To create a enum object:
      dummy_enum = type_utils.Enum(['A', 'B', 'C'])

    To access a enum object, use:
      dummy_enum.A
      dummy_enum.B
  """

  def __getattr__(self, name):
    if name in self:
      return name
    raise AttributeError


def DrainQueue(queue):
  """Returns as many elements as can be obtained from a queue without blocking.

  (This may be no elements at all.)
  """
  ret = []
  while True:
    try:
      ret.append(queue.get_nowait())
    except Queue.Empty:
      break
  return ret


def FlattenList(lst):
  """Flattens a list, recursively including all items in contained arrays.

  For example:

    FlattenList([1,2,[3,4,[]],5,6]) == [1,2,3,4,5,6]
  """
  return sum((FlattenList(x) if isinstance(x, list) else [x] for x in lst),
             [])


def MakeList(value):
  """Converts the given value to a list.

  Returns:
    A list of elements from "value" if it is iterable (except string);
    otherwise, a list contains only one element.
  """
  if (isinstance(value, collections.Iterable) and
      not isinstance(value, basestring)):
    return list(value)
  return [value]


def MakeSet(value):
  """Converts the given value to a set.

  Returns:
    A set of elements from "value" if it is iterable (except string);
    otherwise, a set contains only one element.
  """
  if (isinstance(value, collections.Iterable) and
      not isinstance(value, basestring)):
    return set(value)
  return set([value])


def CheckDictKeys(dict_to_check, allowed_keys):
  """Makes sure that a dictionary's keys are valid.

  Args:
    dict_to_check: A dictionary.
    allowed_keys: The set of allowed keys in the dictionary.
  """
  if not isinstance(dict_to_check, dict):
    raise TypeError('Expected dict but found %s' % type(dict_to_check))

  extra_keys = set(dict_to_check) - set(allowed_keys)
  if extra_keys:
    raise ValueError('Found extra keys: %s' % list(extra_keys))


class AttrDict(dict):
  """Attribute dictionary.

  Use subclassed dict to store attributes. On __init__, the values inside
  initial iterable will be converted to AttrDict if its type is a builtin
  dict or builtin list.

  Example:
    foo = AttrDict()
    foo['xyz'] = 'abc'
    assertEqual(foo.xyz, 'abc')

    bar = AttrDict({'x': {'y': 'value_x_y'},
                    'z': [{'m': 'value_z_0_m'}]})
    assertEqual(bar.x.y, 'value_x_y')
    assertEqual(bar.z[0].m, 'value_z_0_m')
  """

  def _IsBuiltinDict(self, item):
    return (isinstance(item, dict) and
            item.__class__.__module__ == '__builtin__' and
            item.__class__.__name__ == 'dict')

  def _IsBuiltinList(self, item):
    return (isinstance(item, list) and
            item.__class__.__module__ == '__builtin__' and
            item.__class__.__name__ == 'list')

  def _ConvertList(self, itemlist):
    converted = []
    for item in itemlist:
      if self._IsBuiltinDict(item):
        converted.append(AttrDict(item))
      elif self._IsBuiltinList(item):
        converted.append(self._ConvertList(item))
      else:
        converted.append(item)
    return converted

  def __init__(self, *args, **kwargs):
    super(AttrDict, self).__init__(*args, **kwargs)
    for key, value in self.iteritems():
      if self._IsBuiltinDict(value):
        self[key] = AttrDict(value)
      elif self._IsBuiltinList(value):
        self[key] = self._ConvertList(value)
    self.__dict__ = self


class Singleton(type):
  """Singleton metaclass.

  Set __metaclass__ to Singleton to make it a singleton class. The instances
  are stored in:
    Singleton._instances[CLASSNAME]

  Example:
    class C(object):
      __metaclass__ = Singleton

    foo = C()
    bar = C()  # foo == bar
  """
  _instances = {}

  def __call__(cls, *args, **kwargs):
    if cls not in cls._instances:
      cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
    return cls._instances[cls]
