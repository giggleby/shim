# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import numbers

from cros.factory.utils import type_utils


class InvalidRecord(type_utils.Error):
  pass


class LogExtractorRecord(dict):
  """A JSON loader which checks the validity of field `time` when parsing.

  Note that the range and precision of JSON number depends on the
  implementation of deserializer, and thus field `time` might lose some
  precision after loading.
  """

  @classmethod
  def Load(cls, line):
    """Each JSON record should contain at least a field called `time`."""
    record = json.loads(line)
    time = record.get('time')
    if not time:
      raise InvalidRecord(
          f'JSON record {record!r} does not contain field `time`.')
    if not isinstance(time, numbers.Number):
      raise InvalidRecord('The value of field `time` should be numeric type.')

    return cls(record)

  def GetTime(self):
    return self['time']

  def __lt__(self, other):
    return self.GetTime() < other.GetTime()
