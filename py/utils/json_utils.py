# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""JSON utilities.

This module provides utilities to serialize or deserialize Python objects
to/from JSON strings or JSON files.
"""

import collections
import enum
import json
import os
from typing import Any, Callable, NamedTuple, Sequence

from cros.factory.utils import file_utils

LoadStr = json.loads


def LoadFile(file_path):
  """Deserialize a file consists of a JSON string to a Python object.

  Args:
    file_path: The path of the file to be deserialize.

  Returns:
    The deserialized Python object.
  """
  return LoadStr(file_utils.ReadFile(file_path))


def DumpStr(obj, pretty=False, newline=None, **json_dumps_kwargs):
  """Serialize a Python object to a JSON string.

  Args:
    obj: a Python object to be serialized.
    pretty: True to output in human-friendly pretty format.
    newline: True to append a newline in the end of result, default to the
      previous argument ``pretty``.
    json_dumps_kwargs: Any allowable arguments to json.dumps.

  Returns:
    The serialized JSON string.
  """
  if newline is None:
    newline = pretty

  if pretty:
    kwargs = dict(indent=2, separators=(',', ': '), sort_keys=True)
  else:
    kwargs = {}
  kwargs.update(json_dumps_kwargs)
  result = json.dumps(obj, **kwargs)

  if newline:
    result += '\n'

  return result


def DumpFile(file_path, obj, pretty=True, newline=None, **json_dumps_kwargs):
  """Write serialized JSON string of a Python object to a given file.

  Args:
    file_path: The path of the file.
    obj: a Python object to be serialized.
    pretty: True to output in human-friendly pretty format.
    newline: True to append a newline in the end of output, default to the
      previous argument ``pretty``.
    json_dumps_kwargs: Any allowable arguments to json.dumps.
  """
  file_utils.WriteFile(
      file_path,
      DumpStr(obj, pretty=pretty, newline=newline, **json_dumps_kwargs))


class JSONDatabase(dict):
  """A dict bound to a JSON file."""

  def __init__(self, file_path, allow_create=False):
    """Initialize and read the JSON file.

    Args:
      file_path: The path of the JSON file.
      allow_create: If True, the file will be automatically created if not
        exists.
    """
    super(JSONDatabase, self).__init__()
    self._file_path = file_path
    if not allow_create or os.path.exists(file_path):
      self.Load()
    else:
      self.Save()

  def Load(self, file_path=None):
    """Read a JSON file and replace the content of this object.

    Args:
      file_path: The path of the JSON file, defaults to argument ``file_path``
        of initialization.
    """
    self.clear()
    self.update(LoadFile(file_path or self._file_path))

  def Save(self, file_path=None):
    """Write the content to a JSON file.

    Args:
      file_path: The path of the JSON file, defaults to argument ``file_path``
        of initialization.
    """
    DumpFile(file_path or self._file_path, self)


class TypeConversionResult(NamedTuple):
  """Holds the result of converting one value to a JSON-supported type of value.

  If the result value is a dictionary or a list, the items might not be in type
  of a JSON-supported one.

  Attributes:
    is_converted: Whether the conversion succeed or not.
    converted_value: The result value that is in type of a JSON-supported one.
  """
  is_converted: bool
  converted_value: Any

  @classmethod
  def from_type_not_convered(cls) -> 'TypeConversionResult':
    return cls(False, None)

  @classmethod
  def from_converted_value(cls, converted_value) -> 'TypeConversionResult':
    return cls(True, converted_value)


class Serializer:
  """Serializes an instance to JSON-serializable object.

  This class takes a list of type-converter functions as a config.  Then, while
  serializing the given object, the class method first tries to convert the
  value type into a JSON-supported one (i.e. none type, bool, int, str, dict,
  list) by invoking each converter function in order and adapting the result
  from the first success one.  Then, if the value is either a list or a
  dictionary, the method recursively serializes the contents.
  """

  def __init__(self, type_converters: Sequence[Callable[[Any],
                                                        TypeConversionResult]]):
    """Initializer.

    Args:
      type_converters: A list of converters, each covers certain types of
        values and convert them to a value in type of a JSON-supported one.
    """
    self._type_converters = type_converters

  def Serialize(self, inst):
    """Serializes the given `instance` to a JSON-serializable object."""
    for type_converter in self._type_converters:
      result = type_converter(inst)
      if result.is_converted:
        inst = result.converted_value
        break
    if isinstance(inst, (type(None), int, float, bool, str)):
      return inst
    if isinstance(inst, (list, tuple)):
      return [self.Serialize(item) for item in inst]
    if isinstance(inst, dict):
      return collections.OrderedDict(
          [(k, self.Serialize(v)) for k, v in inst.items()])
    raise TypeError(f'Unable to serialize the type {type(inst)}.')


def ConvertNamedTupleToDict(input_value) -> TypeConversionResult:
  """Try to convert the nametuple value to a dictionary."""
  if isinstance(input_value, tuple) and hasattr(input_value, '_asdict'):
    return TypeConversionResult.from_converted_value(input_value._asdict())
  return TypeConversionResult.from_type_not_convered()


def ConvertEnumToStr(input_value) -> TypeConversionResult:
  """Try to convert the enum value to string of the enum name."""
  if isinstance(input_value, enum.Enum):
    return TypeConversionResult.from_converted_value(input_value.name)
  return TypeConversionResult.from_type_not_convered()
