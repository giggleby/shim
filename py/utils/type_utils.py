# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for data types."""

import collections.abc
import functools
import inspect
import queue
import re
from typing import Any, Callable, Dict, Generic, Iterable, List, Set, Tuple, TypeVar, Union, overload


# The regular expression used by Overrides.
_OVERRIDES_CLASS_RE = re.compile(r'\s*class([^#]+)\(\s*([^\s#]+)\s*\)\s*\:')
T = TypeVar('T')


class Error(Exception):
  """Generic fatal error."""


class TestFailure(Exception):
  """Failure of a test."""


class TestListError(Exception):
  """TestList exception."""


class MaxRetryError(Exception):
  """Retry times exceeds threshold error."""

  def __init__(self, message="") -> None:
    self.message = message
    if not message:
      self.message = "Retry times exceeds threshold"
    super().__init__(message)


# pylint: disable=redefined-builtin
class TimeoutError(Error):
  """Timeout error."""
  def __init__(self, message='Timed out', output=None):
    Error.__init__(self)
    self.message = message
    self.output = output

  def __str__(self):
    return repr(self.message)


class Obj:
  """Generic wrapper allowing dot-notation dict access."""

  def __init__(self, **field_dict):
    self.__dict__.update(field_dict)

  def __repr__(self):
    return repr(self.__dict__)

  def __eq__(self, rhs):
    return isinstance(rhs, Obj) and self.__dict__ == rhs.__dict__

  def __ne__(self, rhs):
    return not self.__eq__(rhs)


def DrainQueue(q: 'queue.Queue[T]') -> List[T]:
  """Returns as many elements as can be obtained from a queue without blocking.

  (This may be no elements at all.)
  """
  ret = []
  while True:
    try:
      ret.append(q.get_nowait())
    except queue.Empty:
      break
  return ret


T_ElementOrList = Union[T, List[T]]


def FlattenList(lst: List[T_ElementOrList]) -> List[T]:
  """Flattens a list, recursively including all items in contained arrays.

  For example:

    FlattenList([1,2,[3,4,[]],5,6]) == [1,2,3,4,5,6]
  """
  return sum((FlattenList(x) if isinstance(x, list) else [x] for x in lst), [])


T_ElementOrTuple = Union[T, Tuple[T]]


def FlattenTuple(tupl: Tuple[T_ElementOrTuple]) -> Tuple[T, ...]:
  """Flattens a tuple, recursively including all items in contained tuples.

  For example:

    FlattenList((1,2,(3,4,()),5,6)) == (1,2,3,4,5,6)
  """
  return sum((FlattenTuple(x) if isinstance(x, tuple) else (x, ) for x in tupl),
             ())


@overload
def MakeList(value: str) -> List[str]:
  ...


@overload
def MakeList(value: Iterable[T]) -> List[T]:
  ...


@overload
def MakeList(value: T) -> List[T]:
  ...


def MakeList(value):
  """Converts the given value to a list.

  Returns:
    A list of elements from "value" if it is iterable (except string);
    otherwise, a list contains only one element.
  """
  if (isinstance(value, collections.abc.Iterable) and
      not isinstance(value, str)):
    return list(value)
  return [value]


@overload
def MakeTuple(value: str) -> Tuple[str]:
  ...


@overload
def MakeTuple(value: Iterable[T]) -> Tuple[T]:
  ...


@overload
def MakeTuple(value: T) -> Tuple[T]:
  ...


def MakeTuple(value):
  """Converts the given value to a tuple recursively.

  This is helpful for using an iterable argument as dict keys especially
  that arguments from JSON will always be list instead of tuple.

  Returns:
    A tuple of elements from "value" if it is iterable (except string)
    recursively; otherwise, a tuple with only one element.
  """

  def ShouldExpand(v):
    return (isinstance(v, collections.abc.Iterable) and not isinstance(v, str))

  def Expand(v):
    return tuple(Expand(e) if ShouldExpand(e) else e for e in v)

  if ShouldExpand(value):
    return Expand(value)
  return (value, )


@overload
def MakeSet(value: str) -> Set[str]:
  ...


@overload
def MakeSet(value: Iterable[T]) -> Set[T]:
  ...


@overload
def MakeSet(value: T) -> Set[T]:
  ...


def MakeSet(value):
  """Converts the given value to a set.

  Returns:
    A set of elements from "value" if it is iterable (except string);
    otherwise, a set contains only one element.
  """
  if (isinstance(value, collections.abc.Iterable) and
      not isinstance(value, str)):
    return set(value)
  return set([value])


def CheckDictKeys(dict_to_check: Dict[T, Any], allowed_keys: List[T]):
  """Makes sure that a dictionary's keys are valid.

  Args:
    dict_to_check: A dictionary.
    allowed_keys: The set of allowed keys in the dictionary.
  """
  if not isinstance(dict_to_check, dict):
    raise TypeError(f'Expected dict but found {type(dict_to_check)}')

  extra_keys = set(dict_to_check) - set(allowed_keys)
  if extra_keys:
    raise ValueError(f'Found extra keys: {list(extra_keys)}')


def GetDict(data: Dict[Any, Any], key_path: Union[str, List[Any]],
            default_value: Any = None) -> Any:
  """A simplified getter function to retrieve values inside dictionary.

  This function is very similar to `dict.get`, except it accepts a key path
  (can be a list or string delimited by dot, for example ['a', 'b'] or 'a.b')

  Args:
    data: A dictionary that may contain sub-dictionaries.
    key_path: A list of keys, or one simple string delimited by dot.
    default_value: The value to return if key_path does not exist.
  """
  if isinstance(key_path, str):
    key_path = key_path.split('.')
  for key in key_path:
    if key not in data:
      return default_value
    data = data[key]
  return data


class AttrDict(dict):
  """Attribute dictionary.

  Use subclassed dict to store attributes. On __init__, the values inside
  initial iterable will be converted to AttrDict if its type is a builtin
  dict or builtin list.

  Examples:
    foo = AttrDict()
    foo['xyz'] = 'abc'
    assertEqual(foo.xyz, 'abc')

    bar = AttrDict({'x': {'y': 'value_x_y'},
                    'z': [{'m': 'value_z_0_m'}]})
    assertEqual(bar.x.y, 'value_x_y')
    assertEqual(bar.z[0].m, 'value_z_0_m')
  """

  @classmethod
  def _Convert(cls, obj):
    if isinstance(obj, list):
      return [cls._Convert(val) for val in obj]
    if isinstance(obj, dict):
      return cls(obj)
    return obj

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for key, val in self.items():
      self[key] = self._Convert(val)
    self.__dict__ = self


class Singleton(type):
  """Singleton metaclass.

  Set __metaclass__ to Singleton to make it a singleton class. The instances
  are stored in:
    Singleton._instances[CLASSNAME]

  Examples:
    class C:
      __metaclass__ = Singleton

    foo = C()
    bar = C()  # foo == bar
  """
  _instances = {}

  def __call__(cls, *args, **kwargs):
    if cls not in cls._instances:
      cls._instances[cls] = super().__call__(*args, **kwargs)
    return cls._instances[cls]


def Overrides(method):
  """A decorator for checking if the parent has implementation for the method.

  Inspired from http://stackoverflow.com/questions/1167617.
  Current implementation does not support multiple inheritance.

  Examples:
    class A:
      def m(self):
        return 1

    class B(A):
      @Overrides
      def m(self):
        return 2

    class C(A):
      @Overrides  # This will raise exception because A does not have k method.
      def k(self):
        return 3
        print('child')

  When being used with other decorators, Overrides should be put at last:

  class B(A):
   @property
   @Overrides
   def m(self):
     return 2
  """
  frame = inspect.currentframe()
  while frame:
    info = inspect.getframeinfo(frame)
    source = info[3] or ['']
    matched = _OVERRIDES_CLASS_RE.match(source[0])
    if matched:
      current_class = matched.group(1)
      base_class = matched.group(2)
      break
    frame = frame.f_back
  else:
    raise ValueError('@Overrides failed to find base class')

  # Resolve base_class in context (look up both locals and globals)
  context = frame.f_globals.copy()
  context.update(frame.f_locals)
  for name in base_class.split('.'):
    if isinstance(context, dict):
      context = context[name]
    else:
      context = getattr(context, name)

  assert hasattr(context, method.__name__), (
      f'Method <{method.__name__}> in class <{current_class}> is not defined in'
      f' base class <{base_class}>.')
  return method


class CachedGetter:
  """A decorator for a cacheable getter function.

  This is helpful for caching results for getter functions. For example::

  @CacheGetter
  def ReadDeviceID():
    with open('/var/device_id') as f:
      return f.read()

  The real file I/O will occur only on first invocation of ``ReadDeviceID()``,
  until ``ReadDeviceID.InvalidateCache()`` is called.

  In current implementation, the getter may accept arguments, but the arguments
  are ignored if there is already cache available. In other words::

  @CacheGetter
  def m(v):
    return v + 1

  m(0)  # First call: returns 1
  m(1)  # Second call: return previous cached answer, 1.
  """

  def __init__(self, getter):
    functools.update_wrapper(self, getter)
    self._getter = getter
    self._has_cached = False
    self._cached_value = None

  def InvalidateCache(self):
    self._has_cached = False
    self._cached_value = None

  def Override(self, value):
    self._has_cached = True
    self._cached_value = value

  def HasCached(self):
    return self._has_cached

  def __call__(self, *args, **kargs):
    # TODO(hungte) Cache args/kargs as well, to return different values when the
    # arguments are different.
    if not self.HasCached():
      self.Override(self._getter(*args, **kargs))
    return self._cached_value


def OverrideCacheableGetter(getter, value):
  """Overrides a function decorated by CacheableGetter with some value."""
  assert hasattr(getter, 'has_cached'), 'Need a CacheableGetter target.'
  assert hasattr(getter, 'cached_value'), 'Need a CacheableGetter target.'
  getter.has_cached = True
  getter.cached_value = value


class LazyProperty(Generic[T]):
  """A decorator for lazy loading properties.

  Examples:

    class C:
      @LazyProperty
      def m(self):
        print 'init!'
        return 3

    c = C()
    print c.m  # see 'init!' then 3
    print c.m  # only see 3
  """
  PROP_NAME_PREFIX = '_lazyprop_'

  def __init__(self, prop: Callable[..., T]):
    self._init_func = prop
    self._prop_name = self.PROP_NAME_PREFIX + prop.__name__
    functools.update_wrapper(self, prop)

  def __get__(self, obj, ignored_obj_type) -> Union['LazyProperty[T]', T]:
    if obj is None:
      return self
    if not hasattr(obj, self._prop_name):
      prop_value = self._init_func(obj)
      setattr(obj, self._prop_name, prop_value)
      return prop_value
    return getattr(obj, self._prop_name)

  def __set__(self, obj, value):
    raise AttributeError(
        f'cannot set attribute, use {type(self).__name__}.Override instead')

  @classmethod
  def Override(cls, obj, prop_name, value):
    obj_class = type(obj)
    if not hasattr(obj_class, prop_name):
      raise AttributeError(f'{obj} has no attribute named {prop_name}')
    if not isinstance(getattr(obj_class, prop_name), cls):
      raise AttributeError(f'{prop_name} is not a {cls.__name__}')
    setattr(obj, cls.PROP_NAME_PREFIX + prop_name, value)


class ClassProperty:
  """A decorator for setting class property."""

  def __init__(self, fget=None):
    self.fget = fget

  def __get__(self, unused_obj, obj_type=None):
    return self.fget(obj_type)


class LazyObject:
  """A proxy object for creating an object on demand.."""

  def __init__(self, constructor, *args, **kargs):
    self._proxy_constructor = lambda: constructor(*args, **kargs)
    self._proxy_object = None

  def __getattr__(self, name):
    if self._proxy_constructor is not None:
      self._proxy_object = self._proxy_constructor()
      self._proxy_constructor = None
    attr = getattr(self._proxy_object, name)
    # We can't do 'setattr' here to speed up processing because the members in
    # the proxy object may be volatile.
    return attr


def StdRepr(obj, extra=None, excluded_keys=None, true_only=False):
  """Returns the representation of an object including its properties.

  Args:
    obj: The object to get properties from.
    extra: Extra items to include in the representation.
    excluded_keys: Keys not to include in the representation.
    true_only: Whether to include only values that evaluate to
      true.
  """
  extra = extra or []
  excluded_keys = excluded_keys or []
  return (obj.__class__.__name__ + '(' + ', '.join(extra + [
      f'{k}={getattr(obj, k)!r}' for k in sorted(obj.__dict__.keys())
      if k[0] != '_' and k not in excluded_keys and
      (not true_only or getattr(obj, k))
  ]) + ')')


def BindFunction(func, *args, **kwargs):
  """Bind arguments to a function.

  The returned function have same __name__ and __doc__ with func.
  """
  @functools.wraps(func)
  def _Wrapper():
    return func(*args, **kwargs)
  return _Wrapper
