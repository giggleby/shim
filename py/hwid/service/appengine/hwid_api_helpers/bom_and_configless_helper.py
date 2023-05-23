# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import logging
import operator
from typing import Collection, Dict, NamedTuple, Optional, Sequence

from cros.factory.hwid.service.appengine.data import config_data
from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.hwid.v3 import rule as v3_rule


_CONFIG_DATA = config_data.CONFIG
# Set TTL to 30 days.
_DEFAULT_BOMCACHER_TTL = datetime.timedelta(days=30).total_seconds()


def _ExtractProjectName(hwid: str) -> str:
  project_and_brand, unused_sep, unused_part = hwid.partition(' ')
  project, unused_sep, unused_part = project_and_brand.partition('-')
  return project


def _GenerateCacheKey(hwid: str, verbose: bool, no_avl_name: bool) -> str:
  return f'{hwid},verbose={verbose},no_avl_name={no_avl_name}'


class BOMAndConfigless(NamedTuple):
  """A class to collect bom and configless obtained from decoded HWID string."""

  bom: Optional[hwid_action.BOM]
  configless: Optional[Dict]
  error: Optional[Exception]


class BOMEntry(NamedTuple):
  """A class containing fields of BomResponse."""
  components: Optional[Sequence['hwid_api_messages_pb2.Component']]
  phase: str
  error: str
  status: 'hwid_api_messages_pb2.Status'


def _GenerateCacheKeyWithProj(proj: str, cache_key: str) -> str:
  return f'{proj}:{cache_key}'


class BOMDataCacher(hwid_action_manager.IHWIDDataCacher):
  """A class to cache bom data by HWID string and invalidate them if needed."""

  def __init__(self, mem_adapter: memcache_adapter.MemcacheAdapter):
    self._mem_adapter = mem_adapter

  def GetBOMEntryFromCache(self, proj: str,
                           cache_key: str) -> Optional[BOMEntry]:
    return self._mem_adapter.Get(_GenerateCacheKeyWithProj(proj, cache_key))

  def SetBOMEntryCache(self, proj: str, cache_key: str, bom: BOMEntry):
    self._mem_adapter.Put(
        _GenerateCacheKeyWithProj(proj, cache_key), bom,
        expiry=_DEFAULT_BOMCACHER_TTL)

  def ClearCache(self, proj: Optional[str] = None):
    """See base class."""
    self._mem_adapter.DelByPattern(
        _GenerateCacheKeyWithProj(proj, '*') if proj else '*')


def GetBOMAndConfiglessStatusAndError(bom_configless):
  if bom_configless.error is not None:
    return (common_helper.ConvertExceptionToStatus(
        bom_configless.error), str(bom_configless.error))
  if bom_configless.bom is None:
    return (hwid_api_messages_pb2.Status.NOT_FOUND, 'HWID not found.')
  return (hwid_api_messages_pb2.Status.SUCCESS, None)


class BOMAndConfiglessHelper:

  def __init__(
      self,
      decoder_data_manager: decoder_data.DecoderDataManager,
      bom_data_cacher: BOMDataCacher,
  ):
    self._vpg_targets = _CONFIG_DATA.vpg_targets
    self._decoder_data_manager = decoder_data_manager
    self._bom_data_cacher = bom_data_cacher

  def BatchGetBOMAndConfigless(
      self,
      hwid_action_getter: hwid_action_manager.IHWIDActionGetter,
      hwid_strings: Sequence[str],
      verbose: bool = False,
      require_vp_info: bool = False,
  ) -> Dict[str, BOMAndConfigless]:
    """Get the BOM and configless for a given HWIDs.

    Args:
      hwid_action_getter: The HWID action getter.
      hwid_strings: List of HWID strings.
      verbose: Requires all fields of components in bom if set to True.
      require_vp_info: A bool to indicate if the is_vp_related field of
          each component is required.

    Returns:
      A dict of {hwid: BOMAndConfigless instance} where the BOMAndConfigless
      instance stores an optional bom dict and an optional configless field
      dict.  If an exception occurs while decoding the HWID string, the
      exception will also be provided in the instance.
    """

    result = {}
    for hwid_string in hwid_strings:
      logging.debug('Getting BOM for %r.', hwid_string)
      project = _ExtractProjectName(hwid_string)

      vpg_config = self._vpg_targets.get(project)

      bom = configless = error = None
      try:
        action = hwid_action_getter.GetHWIDAction(project)
        bom, configless = action.GetBOMAndConfigless(
            hwid_string, verbose, vpg_config, require_vp_info)
      except (ValueError, KeyError, RuntimeError) as ex:
        error = ex
      result[hwid_string] = BOMAndConfigless(bom, configless, error)
    return result

  def BatchGetBOMEntry(
      self,
      hwid_action_getter: hwid_action_manager.IHWIDActionGetter,
      hwids: Collection[str],
      verbose: bool = False,
      no_avl_name: bool = False,
  ) -> Dict[str, BOMEntry]:
    result = {}
    batch_request = []
    proj_mapping = {}
    for hwid in hwids:
      status, error = common_helper.FastFailKnownBadHWID(hwid)
      if status != hwid_api_messages_pb2.Status.SUCCESS:
        # Filter out bad HWIDs.
        result[hwid] = BOMEntry(None, '', error, status)
        continue
      project = _ExtractProjectName(hwid)
      proj_mapping[hwid] = project
      cache_key = _GenerateCacheKey(hwid, verbose, no_avl_name)
      bom_from_cache = self._bom_data_cacher.GetBOMEntryFromCache(
          project, cache_key)
      if bom_from_cache:
        # Use cached data.
        result[hwid] = bom_from_cache
        continue
      batch_request.append(hwid)

    np_adapter = name_pattern_adapter.NamePatternAdapter()
    for hwid, bom_configless in self.BatchGetBOMAndConfigless(
        hwid_action_getter, batch_request, verbose).items():
      cache_key = _GenerateCacheKey(hwid, verbose, no_avl_name)
      project = proj_mapping[hwid]
      status, error = GetBOMAndConfiglessStatusAndError(bom_configless)

      if status != hwid_api_messages_pb2.Status.SUCCESS:
        result[hwid] = BOMEntry(None, '', error, status)
        self._bom_data_cacher.SetBOMEntryCache(project, cache_key, result[hwid])
        continue
      bom = bom_configless.bom
      components = []

      for component in bom.GetComponents():
        if no_avl_name:
          avl_name = ''
        else:
          avl_name = self._decoder_data_manager.GetAVLName(
              component.cls, component.name, fallback=False)
        fields = []
        if verbose:
          for fname, fvalue in component.fields.items():
            field = hwid_api_messages_pb2.Field()
            field.name = fname
            if isinstance(fvalue, v3_rule.Value):
              field.value = ('!re ' + fvalue.raw_value
                             if fvalue.is_re else fvalue.raw_value)
            else:
              field.value = str(fvalue)
            fields.append(field)

        fields.sort(key=lambda field: field.name)

        name_pattern = np_adapter.GetNamePattern(component.cls)
        name_info = name_pattern.Matches(component.name)
        if name_info:
          qid = 0 if name_info.is_subcomp else name_info.qid
          avl_info = hwid_api_messages_pb2.AvlInfo(
              cid=name_info.cid, qid=qid, avl_name=avl_name,
              is_subcomp=name_info.is_subcomp)
        else:
          avl_info = None

        components.append(
            hwid_api_messages_pb2.Component(
                component_class=component.cls, name=component.name,
                fields=fields, avl_info=avl_info, has_avl=bool(avl_info)))

      components.sort(key=operator.attrgetter('component_class', 'name'))

      result[hwid] = BOMEntry(components, bom.phase, '',
                              status=hwid_api_messages_pb2.Status.SUCCESS)
      self._bom_data_cacher.SetBOMEntryCache(project, cache_key, result[hwid])
    return result
