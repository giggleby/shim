# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Callable, Sequence

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import converter_types


# Shorter identifiers.
_ConvertedValueSpec = converter.ConvertedValueSpec


class _BatteryAVLAttrs(converter.AVLAttrs):
  MANUFACTURER = 'manufacturer'
  MODEL_NAME = 'model_name'


class _PrefixAndTrimStrFormatter(converter_types.StrFormatter):

  def __init__(self, length: int):
    self._length = length

  def __call__(self, value: str, *unused_args, **unused_kwargs):
    return value[:self._length].strip()


def MakeStrPrefixMatchFactory(
    length: int) -> Callable[..., converter_types.FormattedStrType]:
  return converter_types.FormattedStrType.CreateInstanceFactory(
      formatter_self=_PrefixAndTrimStrFormatter(length),
      formatter_other=lambda x: x.rstrip())


_BATTERY_CONVERTERS: Sequence[converter.FieldNameConverter] = (
    converter.FieldNameConverter.FromFieldMap(
        'full_length_match', {
            _BatteryAVLAttrs.MANUFACTURER: _ConvertedValueSpec('manufacturer'),
            _BatteryAVLAttrs.MODEL_NAME: _ConvertedValueSpec('model_name'),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'prefix_match_length_11', {
            _BatteryAVLAttrs.MANUFACTURER:
                _ConvertedValueSpec('manufacturer',
                                    MakeStrPrefixMatchFactory(11)),
            _BatteryAVLAttrs.MODEL_NAME:
                _ConvertedValueSpec('model_name',
                                    MakeStrPrefixMatchFactory(11)),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'prefix_match_length_7', {
            _BatteryAVLAttrs.MANUFACTURER:
                _ConvertedValueSpec('manufacturer',
                                    MakeStrPrefixMatchFactory(7)),
            _BatteryAVLAttrs.MODEL_NAME:
                _ConvertedValueSpec('model_name', MakeStrPrefixMatchFactory(7)),
        }),
)


def GetConverterCollection():
  collection = converter.ConverterCollection('battery')
  for conv in _BATTERY_CONVERTERS:
    collection.AddConverter(conv)
  return collection
