# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter

# Shorter identifiers.
_ConvertedValueSpec = converter.ConvertedValueSpec


class _BatteryAVLAttrs(converter.AVLAttrs):
  MANUFACTURER = 'manufacturer'
  MODEL_NAME = 'model_name'


_BATTERY_CONVERTERS: Sequence[converter.FieldNameConverter] = (
    converter.FieldNameConverter.FromFieldMap(
        'full_length_match', {
            _BatteryAVLAttrs.MANUFACTURER: _ConvertedValueSpec('manufacturer'),
            _BatteryAVLAttrs.MODEL_NAME: _ConvertedValueSpec('model_name'),
        }), )


def GetConverterCollection():
  collection = converter.ConverterCollection('battery')
  for conv in _BATTERY_CONVERTERS:
    collection.AddConverter(conv)
  return collection
