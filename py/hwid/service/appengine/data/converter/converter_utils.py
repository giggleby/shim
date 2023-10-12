# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Mapping, NamedTuple, Optional

from cros.factory.hwid.service.appengine.data.converter import audio_codec_converter
from cros.factory.hwid.service.appengine.data.converter import battery_converter
from cros.factory.hwid.service.appengine.data.converter import camera_converter
from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import cpu_converter
from cros.factory.hwid.service.appengine.data.converter import display_panel_converter
from cros.factory.hwid.service.appengine.data.converter import dram_converter
from cros.factory.hwid.service.appengine.data.converter import pcie_emmc_storage_assembly_converter
from cros.factory.hwid.service.appengine.data.converter import pcie_emmc_storage_bridge_converter
from cros.factory.hwid.service.appengine.data.converter import storage_bridge_converter
from cros.factory.hwid.service.appengine.data.converter import storage_converter
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import name_pattern_adapter


# A map to collect converter collections.
_DEFAULT_CONVERTER_COLLECTION_MAP = {
    'audio_codec':
        audio_codec_converter.GetConverterCollection(),
    'battery':
        battery_converter.GetConverterCollection(),
    'camera':
        camera_converter.GetConverterCollection(category='camera'),
    'cpu':
        cpu_converter.GetConverterCollection(),
    'display_panel':
        display_panel_converter.GetConverterCollection(),
    'dram':
        dram_converter.GetConverterCollection(),
    'storage':
        storage_converter.GetConverterCollection(),
    'storage_bridge':
        storage_bridge_converter.GetConverterCollection(),
    'video':
        camera_converter.GetConverterCollection(category='video'),
    'pcie_emmc_storage_assembly':
        pcie_emmc_storage_assembly_converter.GetConverterCollection(),
    'pcie_emmc_storage_bridge':
        pcie_emmc_storage_bridge_converter.GetConverterCollection(),
}
_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class _AVLKey(NamedTuple):
  cid: int
  qid: int


class _GetAVLKeyAcceptor(
    name_pattern_adapter.NameInfoAcceptor[Optional[_AVLKey]]):
  """An acceptor to provide CID info."""

  def AcceptRegularComp(self, cid: int,
                        qid: Optional[int]) -> Optional[_AVLKey]:
    """See base class."""
    return _AVLKey(cid, 0 if qid is None else qid)

  def AcceptSubcomp(self, cid: int) -> Optional[_AVLKey]:
    """See base class."""
    return _AVLKey(cid, 0)

  def AcceptUntracked(self) -> Optional[_AVLKey]:
    """See base class."""
    return None

  def AcceptLegacy(self, raw_comp_name: str) -> Optional[_AVLKey]:  # pylint: disable=useless-return
    """See base class."""
    del raw_comp_name
    return None


class ConverterManager:

  def __init__(self, collection_map: Mapping[str,
                                             converter.ConverterCollection]):
    self._collection_map = collection_map
    self._get_avl_key_acceptor = _GetAVLKeyAcceptor()

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
      comp_identity = comp_probe_info.component_identity
      avl_key = _AVLKey(comp_identity.component_id, comp_identity.qual_id)
      probe_info_map[avl_key] = comp_probe_info.probe_info

    with builder.DatabaseBuilder.FromDBData(hwid_db_content) as db_builder:
      for comp_cls in db_builder.GetComponentClasses():
        converter_collection = self.GetConverterCollection(comp_cls)
        if not converter_collection:
          continue
        name_pattern = adapter.GetNamePattern(comp_cls)
        for comp_name, comp_info in db_builder.GetComponents(comp_cls).items():
          name_info = name_pattern.Matches(comp_name)
          avl_key = name_info.Provide(self._get_avl_key_acceptor)
          if avl_key is None:
            continue
          probe_info = probe_info_map.get(avl_key)
          if probe_info is None:
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
