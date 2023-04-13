# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


_ConvertedValueSpec = converter.ConvertedValueSpec


class _AudioCodecAVLAttrs(converter.AVLAttrs):
  KERNEL_NAME = 'name'


_AUDIO_CODEC_CONVERTERS: Sequence[converter.FieldNameConverter] = [
    converter.FieldNameConverter.FromFieldMap('full_length_match', {
        _AudioCodecAVLAttrs.KERNEL_NAME: _ConvertedValueSpec('name'),
    }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('audio_codec')
  for conv in _AUDIO_CODEC_CONVERTERS:
    collection.AddConverter(conv)
  return collection
