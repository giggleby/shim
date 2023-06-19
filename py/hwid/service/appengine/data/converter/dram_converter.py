# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


_ConvertedValueSpec = converter.ConvertedValueSpec


class DRAMAVLAttrs(converter.AVLAttrs):
  PART = 'part'


_DRAM_CONVERTERS: Sequence[converter.FieldNameConverter] = [
    converter.FieldNameConverter.FromFieldMap('full_length_match', {
        DRAMAVLAttrs.PART: _ConvertedValueSpec('part'),
    }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('dram')
  for conv in _DRAM_CONVERTERS:
    collection.AddConverter(conv)
  return collection
