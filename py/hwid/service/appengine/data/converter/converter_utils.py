# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Mapping, Optional

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import storage_converter

# A map to collect converter collections.
_DEFAULT_CONVERTER_COLLECTION_MAP = {
    'storage': storage_converter.GetConverterCollection(),
}


class ConverterManager:

  def __init__(self, collection_map: Mapping[str,
                                             converter.ConverterCollection]):
    self._collection_map = collection_map

  @classmethod
  def FromDefault(cls):
    return cls(_DEFAULT_CONVERTER_COLLECTION_MAP)

  def GetConverterCollection(
      self, category: str) -> Optional[converter.ConverterCollection]:
    return self._collection_map.get(category)
