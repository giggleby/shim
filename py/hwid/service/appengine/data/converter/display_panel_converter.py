# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


_ConvertedValueSpec = converter.ConvertedValueSpec


class DisplayPanelAVLAttrs(converter.AVLAttrs):
  PRODUCT_ID = 'product_id'
  VENDOR = 'vendor'
  HEIGHT = 'height'
  WIDTH = 'width'


_DISPLAY_PANEL_CONVERTERS: Sequence[converter.FieldNameConverter] = [
    converter.FieldNameConverter.FromFieldMap(
        'product_and_vendor', {
            DisplayPanelAVLAttrs.PRODUCT_ID:
                _ConvertedValueSpec(
                    'product_id',
                    converter.MakeBothNormalizedFillWidthHexValueFactory(
                        fill_width=4, source_has_prefix=False)),
            DisplayPanelAVLAttrs.VENDOR:
                _ConvertedValueSpec('vendor'),
            DisplayPanelAVLAttrs.HEIGHT:
                _ConvertedValueSpec('height'),
            DisplayPanelAVLAttrs.WIDTH:
                _ConvertedValueSpec('width'),
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('display_panel')
  for conv in _DISPLAY_PANEL_CONVERTERS:
    collection.AddConverter(conv)
  return collection
