# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines the flexible field value types.

This module consists of converter types which could be used to compare with
different value representations.
"""

from typing import Any


class IntValueType(int):
  """Flexible int value type to match integers repsented in str."""

  def __eq__(self, other: Any):

    if isinstance(other, str):
      # hexadecimal
      other = other.lower().strip()
      if other.startswith('0x'):
        try:
          v = int(other, 16)
        except ValueError:
          return False
        return super().__eq__(v)

      # decimal
      try:
        v = int(other)
      except ValueError:
        return False
      return super().__eq__(v)
    return super().__eq__(other)
