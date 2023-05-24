# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import operator
import re

from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine import hwid_action_manager as hwid_action_mngr_module
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper_module
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper as sku_helper_module
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils


def _GetFeatureEnablementStatusOrDefaultFromBOMEntry(
    hwid: str, bom_entry: bc_helper_module.BOMEntry,
    hwid_action_getter: hwid_action_mngr_module.IHWIDActionGetter) -> str:
  if bom_entry.status != hwid_api_messages_pb2.Status.SUCCESS:
    return ''
  action = hwid_action_getter.GetHWIDAction(bom_entry.project)
  return action.GetFeatureEnablementLabel(hwid)


class GetBOMShard(common_helper.HWIDServiceShardBase):

  def __init__(
      self,
      hwid_action_manager: hwid_action_mngr_module.HWIDActionManager,
      bc_helper: bc_helper_module.BOMAndConfiglessHelper,
  ):
    self._hwid_action_manager = hwid_action_manager
    self._bc_helper = bc_helper

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetBom(self, request):
    """Return the components of the BOM identified by the HWID."""
    hwid_action_getter = hwid_action_mngr_module.InMemoryCachedHWIDActionGetter(
        self._hwid_action_manager)
    bom_entry_dict = self._bc_helper.BatchGetBOMEntry(
        hwid_action_getter, [request.hwid], request.verbose,
        request.no_avl_name)
    bom_entry = bom_entry_dict.get(request.hwid)
    if bom_entry is None:
      return hwid_api_messages_pb2.BomResponse(
          error='Internal error',
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)
    return hwid_api_messages_pb2.BomResponse(
        components=bom_entry.components, phase=bom_entry.phase,
        feature_enablement_status=(
            _GetFeatureEnablementStatusOrDefaultFromBOMEntry(
                request.hwid, bom_entry, hwid_action_getter)),
        error=bom_entry.error, status=bom_entry.status)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def BatchGetBom(self, request):
    """Return the components of the BOM identified by the batch HWIDs."""
    response = hwid_api_messages_pb2.BatchGetBomResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS)
    hwid_action_getter = hwid_action_mngr_module.InMemoryCachedHWIDActionGetter(
        self._hwid_action_manager)
    bom_entry_dict = self._bc_helper.BatchGetBOMEntry(
        hwid_action_getter, request.hwid, request.verbose, request.no_avl_name)
    for hwid, bom_entry in bom_entry_dict.items():
      response.boms.get_or_create(hwid).CopyFrom(
          hwid_api_messages_pb2.BatchGetBomResponse.Bom(
              components=bom_entry.components, phase=bom_entry.phase,
              feature_enablement_status=(
                  _GetFeatureEnablementStatusOrDefaultFromBOMEntry(
                      hwid, bom_entry, hwid_action_getter)),
              error=bom_entry.error, status=bom_entry.status))
      if bom_entry.status != hwid_api_messages_pb2.Status.SUCCESS:
        if response.status == hwid_api_messages_pb2.Status.SUCCESS:
          # Set the status and error of the response to the first unsuccessful
          # one.
          response.status = bom_entry.status
          response.error = bom_entry.error
    return response


class GetSKUShard(common_helper.HWIDServiceShardBase):

  def __init__(
      self,
      hwid_action_manager: hwid_action_mngr_module.HWIDActionManager,
      bc_helper: bc_helper_module.BOMAndConfiglessHelper,
      sku_helper: sku_helper_module.SKUHelper,
  ):
    self._hwid_action_manager = hwid_action_manager
    self._bc_helper = bc_helper
    self._sku_helper = sku_helper

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetSku(self, request):
    """Return the components of the SKU identified by the HWID."""
    status, error = common_helper.FastFailKnownBadHWID(request.hwid)
    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.SkuResponse(error=error, status=status)

    hwid_action_getter = hwid_action_mngr_module.InMemoryCachedHWIDActionGetter(
        self._hwid_action_manager)
    bc_dict = self._bc_helper.BatchGetBOMAndConfigless(
        hwid_action_getter, [request.hwid], verbose=True)
    bom_configless = bc_dict.get(request.hwid)
    if bom_configless is None:
      return hwid_api_messages_pb2.SkuResponse(
          error='Internal error',
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)
    status, error = bc_helper_module.GetBOMAndConfiglessStatusAndError(
        bom_configless)
    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.SkuResponse(error=error, status=status)
    bom = bom_configless.bom
    configless = bom_configless.configless

    sku = self._sku_helper.GetSKUFromBOM(bom, configless)
    action = hwid_action_getter.GetHWIDAction(bom.project)
    return hwid_api_messages_pb2.SkuResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, project=sku.project,
        cpu=sku.cpu, memory_in_bytes=sku.total_bytes, memory=sku.memory_str,
        sku=sku.sku_str, warnings=sku.warnings,
        feature_enablement_status=(action.GetFeatureEnablementLabel(
            request.hwid)))


class GetDUTLabelShard(common_helper.HWIDServiceShardBase):

  def __init__(self, decoder_data_manager: decoder_data.DecoderDataManager,
               goldeneye_memcache_adapter: memcache_adapter.MemcacheAdapter,
               bc_helper: bc_helper_module.BOMAndConfiglessHelper,
               sku_hepler: sku_helper_module.SKUHelper,
               hwid_action_manager: hwid_action_mngr_module.HWIDActionManager):
    self._decoder_data_manager = decoder_data_manager
    self._goldeneye_memcache_adapter = goldeneye_memcache_adapter
    self._bc_helper = bc_helper
    self._sku_helper = sku_hepler
    self._hwid_action_manager_inst = hwid_action_manager

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetDutLabels(self, request):
    """Return the components of the SKU identified by the HWID."""
    hwid = request.hwid

    # If you add any labels to the list of returned labels, also add to
    # the list of possible labels.
    possible_labels = [
        'hwid_component',
        'phase',
        'sku',
        'stylus',
        'touchpad',
        'touchscreen',
        'variant',
        'wireless',
        'cellular',
        'feature_enablement_status',
    ]

    if not hwid:  # Return possible labels.
      return hwid_api_messages_pb2.DutLabelsResponse(
          possible_labels=possible_labels,
          status=hwid_api_messages_pb2.Status.SUCCESS)

    status, error = common_helper.FastFailKnownBadHWID(hwid)
    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.DutLabelsResponse(
          error=error, possible_labels=possible_labels, status=status)

    hwid_action_getter = hwid_action_mngr_module.InMemoryCachedHWIDActionGetter(
        self._hwid_action_manager_inst)
    bc_dict = self._bc_helper.BatchGetBOMAndConfigless(
        hwid_action_getter, [hwid], verbose=True, require_vp_info=True)
    bom_configless = bc_dict.get(hwid)
    if bom_configless is None:
      return hwid_api_messages_pb2.DutLabelResponse(
          error='Internal error',
          status=hwid_api_messages_pb2.Status.SERVER_ERROR,
          possible_labels=possible_labels)
    bom = bom_configless.bom
    configless = bom_configless.configless
    status, error = bc_helper_module.GetBOMAndConfiglessStatusAndError(
        bom_configless)

    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.DutLabelsResponse(
          status=status, error=error, possible_labels=possible_labels)

    sku = self._sku_helper.GetSKUFromBOM(bom, configless)
    response = hwid_api_messages_pb2.DutLabelsResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS)
    response.labels.add(name='sku', value=sku.sku_str)
    response.warnings.extend(sku.warnings)

    regexp_to_device = self._goldeneye_memcache_adapter.Get('regexp_to_device')

    if not regexp_to_device:
      # TODO(haddowk) Kick off the ingestion to ensure that the memcache is
      # up to date.
      return hwid_api_messages_pb2.DutLabelsResponse(
          error='Missing Regexp List', possible_labels=possible_labels,
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)
    variant_set = set()
    for (regexp, device, unused_regexp_to_project) in regexp_to_device:
      del unused_regexp_to_project  # unused
      try:
        if re.match(regexp, hwid):
          variant_set.add(device)
      except re.error:
        logging.exception('invalid regex pattern: %r', regexp)
    for device in variant_set:
      response.labels.add(name='variant', value=device)
    if bom.phase:
      response.labels.add(name='phase', value=bom.phase)

    comp_classes = ['touchscreen', 'touchpad', 'stylus']
    for comp_cls in comp_classes:
      # The lab just want the existence of a component they do not care
      # what type it is.
      if configless and 'has_' + comp_cls in configless['feature_list']:
        if configless['feature_list']['has_' + comp_cls]:
          response.labels.add(name=comp_cls, value=None)
      else:
        components = self._sku_helper.GetComponentValueFromBOM(bom, comp_cls)
        if components and components[0]:
          response.labels.add(name=comp_cls, value=None)

    # cros labels in host_info store, which will be used in tast tests of
    # runtime probe
    for component in bom.GetComponents():
      if component.name and component.is_vp_related:
        name = self._decoder_data_manager.GetPrimaryIdentifier(
            bom.project, component.cls, component.name)
        if component.information is not None:
          name = component.information.get('comp_group', name)
        response.labels.add(name="hwid_component",
                            value=component.cls + '/' + name)

    # Labels to provide the identifier used in AVL.
    avl_comp_classes = ['wireless', 'cellular']
    for comp_cls in avl_comp_classes:
      components = self._sku_helper.GetComponentValueFromBOM(bom, comp_cls)
      if components and components[0]:
        comp_name = components[0]
        avl_name = self._decoder_data_manager.GetAVLName(comp_cls, comp_name)
        response.labels.add(name=comp_cls, value=avl_name)

    action = hwid_action_getter.GetHWIDAction(bom.project)
    response.labels.add(name='feature_enablement_status',
                        value=action.GetFeatureEnablementLabel(hwid))

    unexpected_labels = set(
        label.name for label in response.labels) - set(possible_labels)

    if unexpected_labels:
      logging.error('unexpected labels: %r', unexpected_labels)
      return hwid_api_messages_pb2.DutLabelsResponse(
          error='Possible labels are out of date',
          possible_labels=possible_labels,
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)

    response.labels.sort(key=operator.attrgetter('name', 'value'))
    response.possible_labels[:] = possible_labels
    return response
