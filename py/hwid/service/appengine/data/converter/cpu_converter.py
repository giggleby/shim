# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds CPU field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


_ConvertedValueSpec = converter.ConvertedValueSpec


class CPUAVLAttrs(converter.AVLAttrs):
  IDENTIFIER = 'identifier'


_CPU_CONVERTERS: Sequence[converter.FieldNameConverter] = [
    converter.FieldNameConverter.FromFieldMap('model_as_identifier', {
        CPUAVLAttrs.IDENTIFIER: _ConvertedValueSpec('model'),
    }),
    converter.FieldNameConverter.FromFieldMap('chip_id_as_identifier', {
        CPUAVLAttrs.IDENTIFIER: _ConvertedValueSpec('chip_id'),
    }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('cpu')
  for conv in _CPU_CONVERTERS:
    collection.AddConverter(conv)
  return collection
