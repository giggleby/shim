# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import json
from typing import Dict

from cros.factory.utils.schema import FixedDict
from cros.factory.utils.schema import Scalar


class IRecord(abc.ABC):
  """A base class for holding dictionary-like data."""

  def __init__(self, data: Dict):
    self._data = data

  def __getitem__(self, key):
    return self._data[key]

  def __setitem__(self, key, val):
    self._data[key] = val

  def __contains__(self, item):
    return item in self._data

  def __eq__(self, other):
    if isinstance(other, self.__class__):
      return self._data == other._data
    return False

  def ToDict(self):
    return self._data

  @abc.abstractmethod
  def GetTime(self) -> float:
    """Returns the number of seconds passed since 1970/01/01 00:00:00."""
    raise NotImplementedError

  def __lt__(self, other):
    return self.GetTime() < other.GetTime()


class FactoryRecord(IRecord):
  _SCHEMA = FixedDict(
      'Factory record schema', items={
          'time':
              Scalar('Time in seconds since the epoch of the record.', float),
      }, allow_undefined_keys=True)

  @classmethod
  def FromJSON(cls, json_str: str, check_valid: bool = True):
    """Loads and validates the field of a JSON string to a dict-like object."""
    data = json.loads(json_str)
    if check_valid:
      cls._SCHEMA.Validate(data)

    return cls(data)

  def GetTime(self) -> float:
    return self['time']
