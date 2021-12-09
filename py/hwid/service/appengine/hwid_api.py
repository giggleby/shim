# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""HWID Api definition.  Defines all the exposed API methods.

This file is also the place that all the binding is done for various components.
"""

import logging

from cros.chromeoshwid import update_checksum
from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.config import CONFIG
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import dut_label_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import self_service_helper as ss_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.service.appengine import ingestion
from cros.factory.hwid.service.appengine import memcache_adapter
# pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2
# pylint: enable=import-error, no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils


KNOWN_BAD_HWIDS = ['DUMMY_HWID', 'dummy_hwid']
KNOWN_BAD_SUBSTR = [
    '.*TEST.*', '.*CHEETS.*', '^SAMS .*', '.* DEV$', '.*DOGFOOD.*'
]

_hwid_action_manager = CONFIG.hwid_action_manager
_hwid_db_data_manager = CONFIG.hwid_db_data_manager
_decoder_data_manager = CONFIG.decoder_data_manager
_hwid_validator = hwid_validator.HwidValidator()
_goldeneye_memcache_adapter = memcache_adapter.MemcacheAdapter(
    namespace=ingestion.GOLDENEYE_MEMCACHE_NAMESPACE)
_hwid_repo_manager = CONFIG.hwid_repo_manager


def _MapValidationException(ex, cls):
  msgs = [er.message for er in ex.errors]
  if any(er.code == hwid_validator.ErrorCode.SCHEMA_ERROR for er in ex.errors):
    return cls(
        error_message=str(msgs) if len(msgs) > 1 else msgs[0],
        status=hwid_api_messages_pb2.Status.SCHEMA_ERROR)
  return cls(
      error_message=str(msgs) if len(msgs) > 1 else msgs[0],
      status=hwid_api_messages_pb2.Status.BAD_REQUEST)


class ProtoRPCService(protorpc_utils.ProtoRPCServiceBase):
  SERVICE_DESCRIPTOR = hwid_api_messages_pb2.DESCRIPTOR.services_by_name[
      'HwidService']

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._sku_helper = sku_helper.SKUHelper(_decoder_data_manager)
    self._bc_helper = (
        bc_helper.BOMAndConfiglessHelper(
            _hwid_action_manager, CONFIG.vpg_targets, _decoder_data_manager))
    self._dut_label_helper = dut_label_helper.DUTLabelHelper(
        _decoder_data_manager, _goldeneye_memcache_adapter, self._bc_helper,
        self._sku_helper)
    self._ss_helper = ss_helper.SelfServiceHelper(
        _hwid_action_manager, _hwid_repo_manager, _hwid_db_data_manager)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetProjects(self, request):
    """Return all of the supported projects in sorted order."""
    versions = list(request.versions) if request.versions else None
    metadata_list = _hwid_db_data_manager.ListHWIDDBMetadata(versions=versions)
    projects = [m.project for m in metadata_list]

    response = hwid_api_messages_pb2.ProjectsResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, projects=sorted(projects))
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetBom(self, request):
    """Return the components of the BOM identified by the HWID."""
    bom_entry_dict = self._bc_helper.BatchGetBOMEntry([request.hwid],
                                                      request.verbose)
    bom_entry = bom_entry_dict.get(request.hwid)
    if bom_entry is None:
      return hwid_api_messages_pb2.BomResponse(
          error='Internal error',
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)
    return hwid_api_messages_pb2.BomResponse(
        components=bom_entry.components, labels=bom_entry.labels,
        phase=bom_entry.phase, error=bom_entry.error, status=bom_entry.status)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def BatchGetBom(self, request):
    """Return the components of the BOM identified by the batch HWIDs."""
    response = hwid_api_messages_pb2.BatchGetBomResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS)
    bom_entry_dict = self._bc_helper.BatchGetBOMEntry(request.hwid,
                                                      request.verbose)
    for hwid, bom_entry in bom_entry_dict.items():
      response.boms.get_or_create(hwid).CopyFrom(
          hwid_api_messages_pb2.BatchGetBomResponse.Bom(
              components=bom_entry.components, labels=bom_entry.labels,
              phase=bom_entry.phase, error=bom_entry.error,
              status=bom_entry.status))
      if bom_entry.status != hwid_api_messages_pb2.Status.SUCCESS:
        if response.status == hwid_api_messages_pb2.Status.SUCCESS:
          # Set the status and error of the response to the first unsuccessful
          # one.
          response.status = bom_entry.status
          response.error = bom_entry.error
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetSku(self, request):
    """Return the components of the SKU identified by the HWID."""
    status, error = common_helper.FastFailKnownBadHWID(request.hwid)
    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.SkuResponse(error=error, status=status)

    bc_dict = self._bc_helper.BatchGetBOMAndConfigless([request.hwid],
                                                       verbose=True)
    bom_configless = bc_dict.get(request.hwid)
    if bom_configless is None:
      return hwid_api_messages_pb2.SkuResponse(
          error='Internal error',
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)
    status, error = bc_helper.GetBOMAndConfiglessStatusAndError(bom_configless)
    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.SkuResponse(error=error, status=status)
    bom = bom_configless.bom
    configless = bom_configless.configless

    try:
      sku = self._sku_helper.GetSKUFromBOM(bom, configless)
    except sku_helper.SKUDeductionError as e:
      return hwid_api_messages_pb2.SkuResponse(
          error=str(e), status=hwid_api_messages_pb2.Status.BAD_REQUEST)

    return hwid_api_messages_pb2.SkuResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, project=sku['project'],
        cpu=sku['cpu'], memory_in_bytes=sku['total_bytes'],
        memory=sku['memory_str'], sku=sku['sku'])

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetHwids(self, request):
    """Return a filtered list of HWIDs for the given project."""
    parse_filter_field = lambda value: set(filter(None, value)) or None
    try:
      hwid_action = _hwid_action_manager.GetHWIDAction(request.project)
      hwids = hwid_action.EnumerateHWIDs(
          with_classes=parse_filter_field(request.with_classes),
          without_classes=parse_filter_field(request.without_classes),
          with_components=parse_filter_field(request.with_components),
          without_components=parse_filter_field(request.without_components))
    except (KeyError, ValueError, RuntimeError) as ex:
      return hwid_api_messages_pb2.HwidsResponse(
          status=common_helper.ConvertExceptionToStatus(ex), error=str(ex))

    return hwid_api_messages_pb2.HwidsResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, hwids=hwids)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetComponentClasses(self, request):
    """Return a list of all component classes for the given project."""
    try:
      hwid_action = _hwid_action_manager.GetHWIDAction(request.project)
      classes = hwid_action.GetComponentClasses()
    except (KeyError, ValueError, RuntimeError) as ex:
      return hwid_api_messages_pb2.ComponentClassesResponse(
          status=common_helper.ConvertExceptionToStatus(ex), error=str(ex))

    return hwid_api_messages_pb2.ComponentClassesResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, component_classes=classes)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetComponents(self, request):
    """Return a filtered list of components for the given project."""
    try:
      hwid_action = _hwid_action_manager.GetHWIDAction(request.project)
      components = hwid_action.GetComponents(
          with_classes=set(filter(None, request.with_classes)) or None)
    except (KeyError, ValueError, RuntimeError) as ex:
      return hwid_api_messages_pb2.ComponentsResponse(
          status=common_helper.ConvertExceptionToStatus(ex), error=str(ex))

    components_list = []
    for cls, comps in components.items():
      for comp in comps:
        components_list.append(
            hwid_api_messages_pb2.Component(component_class=cls, name=comp))

    return hwid_api_messages_pb2.ComponentsResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, components=components_list)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateConfig(self, request):
    """Validate the config.

    Args:
      request: a ValidateConfigRequest.

    Returns:
      A ValidateConfigAndUpdateResponse containing an error message if an error
      occurred.
    """
    hwid_config_contents = request.hwid_config_contents

    try:
      _hwid_validator.Validate(hwid_config_contents)
    except hwid_validator.ValidationError as e:
      logging.exception('Validation failed')
      return _MapValidationException(
          e, hwid_api_messages_pb2.ValidateConfigResponse)

    return hwid_api_messages_pb2.ValidateConfigResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateConfigAndUpdateChecksum(self, request):
    """Validate the config and update its checksum.

    Args:
      request: a ValidateConfigAndUpdateChecksumRequest.

    Returns:
      A ValidateConfigAndUpdateChecksumResponse containing either the updated
      config or an error message.  Also the cid, qid, status will also be
      responded if the component name follows the naming rule.
    """

    hwid_config_contents = request.hwid_config_contents
    prev_hwid_config_contents = request.prev_hwid_config_contents

    updated_contents = update_checksum.ReplaceChecksum(hwid_config_contents)

    try:
      model, new_hwid_comps = _hwid_validator.ValidateChange(
          updated_contents, prev_hwid_config_contents)

    except hwid_validator.ValidationError as e:
      logging.exception('Validation failed')
      return _MapValidationException(
          e, hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse)

    resp = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS,
        new_hwid_config_contents=updated_contents, model=model)

    for comp_cls, comps in new_hwid_comps.items():
      entries = resp.name_changed_components_per_category.get_or_create(
          comp_cls).entries
      try:
        entries.extend(
            ss_helper.ConvertToNameChangedComponent(c) for c in comps)
      except ss_helper.HWIDStatusConversionError as ex:
        return hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=hwid_api_messages_pb2.Status.BAD_REQUEST,
            error_message=str(ex))
    return resp

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetDutLabels(self, request):
    return self._dut_label_helper.GetDUTLabels(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetHwidDbEditableSection(self, request):
    return self._ss_helper.GetHWIDDBEditableSection(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateHwidDbEditableSectionChange(self, request):
    return self._ss_helper.ValidateHWIDDBEditableSectionChange(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def CreateHwidDbEditableSectionChangeCl(self, request):
    return self._ss_helper.CreateHWIDDBEditableSectionChangeCL(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def BatchGetHwidDbEditableSectionChangeClInfo(self, request):
    return self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def BatchGenerateAvlComponentName(self, request):
    return self._ss_helper.BatchGenerateAVLComponentName(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def AnalyzeHwidDbEditableSection(self, request):
    return self._ss_helper.AnalyzeHWIDDBEditableSection(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetHwidBundleResourceInfo(self, request):
    return self._ss_helper.GetHWIDBundleResourceInfo(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def CreateHwidBundle(self, request):
    return self._ss_helper.CreateHWIDBundle(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def CreateHwidDbFirmwareInfoUpdateCl(self, request):
    return self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(request)
