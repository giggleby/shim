# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Mapping, Optional

from cros.factory.hwid.service.appengine.data.converter import audio_codec_converter
from cros.factory.hwid.service.appengine.data.converter import battery_converter
from cros.factory.hwid.service.appengine.data.converter import camera_converter
from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import cpu_converter
from cros.factory.hwid.service.appengine.data.converter import display_panel_converter
from cros.factory.hwid.service.appengine.data.converter import dram_converter
from cros.factory.hwid.service.appengine.data.converter import storage_converter
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import name_pattern_adapter


# A map to collect converter collections.
_DEFAULT_CONVERTER_COLLECTION_MAP = {
    'audio_codec': audio_codec_converter.GetConverterCollection(),
    'battery': battery_converter.GetConverterCollection(),
    'camera': camera_converter.GetConverterCollection(category='camera'),
    'cpu': cpu_converter.GetConverterCollection(),
    'display_panel': display_panel_converter.GetConverterCollection(),
    'dram': dram_converter.GetConverterCollection(),
    'storage': storage_converter.GetConverterCollection(),
    'video': camera_converter.GetConverterCollection(category='video'),
}
_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class ConverterManager:

  def __init__(self, collection_map: Mapping[str,
                                             converter.ConverterCollection]):
    self._collection_map = collection_map
    self._get_cid_acceptor = name_pattern_adapter.GetCIDAcceptor()

  @classmethod
  def FromDefault(cls):
    return cls(_DEFAULT_CONVERTER_COLLECTION_MAP)

  def GetConverterCollection(
      self, category: str) -> Optional[converter.ConverterCollection]:
    return self._collection_map.get(category)

  def LinkAVL(
      self, hwid_db_content: hwid_db_data.HWIDDBData,
      avl_resource: hwid_api_messages_pb2.HwidDbExternalResource
  ) -> hwid_db_data.HWIDDBData:
    adapter = name_pattern_adapter.NamePatternAdapter()

    probe_info_map = {}
    for comp_probe_info in avl_resource.component_probe_infos:
      comp_id = comp_probe_info.component_identity.component_id
      probe_info_map[comp_id] = comp_probe_info.probe_info

    with builder.DatabaseBuilder.FromDBData(hwid_db_content) as db_builder:
      for comp_cls in db_builder.GetComponentClasses():
        converter_collection = self.GetConverterCollection(comp_cls)
        if not converter_collection:
          continue
        name_pattern = adapter.GetNamePattern(comp_cls)
        for comp_name, comp_info in db_builder.GetComponents(comp_cls).items():
          name_info = name_pattern.Matches(comp_name)
          cid = name_info.Provide(self._get_cid_acceptor)
          if cid is None:
            continue
          probe_info = probe_info_map.get(cid)
          if not probe_info:
            continue
          match_result = converter_collection.Match(comp_info.values,
                                                    probe_info)
          db_builder.SetLinkAVLProbeValue(
              comp_cls, comp_name, match_result.converter_identifier,
              match_result.alignment_status == _PVAlignmentStatus.ALIGNED)
    db = db_builder.Build()
    return db.DumpDataWithoutChecksum(suppress_support_status=False,
                                      magic_placeholder_options=None,
                                      internal=True)
