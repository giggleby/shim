# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
from typing import Optional

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import storage_converter

# A map to collect converter collections.
_CONVERTER_COLLECTION_MAP = {
    'storage': storage_converter.GetConverterCollection(),
}


class ConverterManager:

  @functools.lru_cache(maxsize=None)
  def GetConverterCollection(
      self, category: str) -> Optional[converter.ConverterCollection]:
    return _CONVERTER_COLLECTION_MAP.get(category)
