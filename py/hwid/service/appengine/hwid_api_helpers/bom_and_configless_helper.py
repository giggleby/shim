# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import operator
from typing import Dict, List, NamedTuple, Optional

from cros.factory.hwid.service.appengine.data import config_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.hwid.v3 import rule as v3_rule


_CONFIG_DATA = config_data.CONFIG


class BOMAndConfigless(NamedTuple):
  """A class to collect bom and configless obtained from decoded HWID string."""

  bom: Optional[hwid_action.BOM]
  configless: Optional[Dict]
  error: Optional[Exception]


class BOMEntry(NamedTuple):
  """A class containing fields of BomResponse."""
  components: Optional[List['hwid_api_messages_pb2.Component']]
  phase: str
  error: str
  status: 'hwid_api_messages_pb2.Status'


def GetBOMAndConfiglessStatusAndError(bom_configless):
  if bom_configless.error is not None:
    return (common_helper.ConvertExceptionToStatus(
        bom_configless.error), str(bom_configless.error))
  if bom_configless.bom is None:
    return (hwid_api_messages_pb2.Status.NOT_FOUND, 'HWID not found.')
  return (hwid_api_messages_pb2.Status.SUCCESS, None)


class BOMAndConfiglessHelper:

  def __init__(self, decoder_data_manager):
    self._vpg_targets = _CONFIG_DATA.vpg_targets
    self._decoder_data_manager = decoder_data_manager

  def BatchGetBOMAndConfigless(
      self, hwid_action_getter: hwid_action_manager.IHWIDActionGetter,
      hwid_strings: List[str], verbose: bool = False,
      require_vp_info: bool = False) -> Dict[str, BOMAndConfigless]:
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
      project_and_brand, unused_sep, unused_part = hwid_string.partition(' ')
      project, unused_sep, unused_part = project_and_brand.partition('-')

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
      self, hwid_action_getter: hwid_action_manager.IHWIDActionGetter, hwids,
      verbose=False) -> Dict[str, BOMEntry]:
    result = {}
    batch_request = []
    # filter out bad HWIDs
    for hwid in hwids:
      status, error = common_helper.FastFailKnownBadHWID(hwid)
      if status != hwid_api_messages_pb2.Status.SUCCESS:
        result[hwid] = BOMEntry(None, '', error, status)
      else:
        batch_request.append(hwid)

    np_adapter = name_pattern_adapter.NamePatternAdapter()
    for hwid, bom_configless in self.BatchGetBOMAndConfigless(
        hwid_action_getter, batch_request, verbose).items():
      status, error = GetBOMAndConfiglessStatusAndError(bom_configless)

      if status != hwid_api_messages_pb2.Status.SUCCESS:
        result[hwid] = BOMEntry(None, '', error, status)
        continue
      bom = bom_configless.bom

      bom_entry = BOMEntry([], bom.phase, '',
                           status=hwid_api_messages_pb2.Status.SUCCESS)

      for component in bom.GetComponents():
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

        bom_entry.components.append(
            hwid_api_messages_pb2.Component(
                component_class=component.cls, name=component.name,
                fields=fields, avl_info=avl_info, has_avl=bool(avl_info)))

      bom_entry.components.sort(
          key=operator.attrgetter('component_class', 'name'))

      result[hwid] = bom_entry
    return result
