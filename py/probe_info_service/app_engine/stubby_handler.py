# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
from typing import Callable, NamedTuple, Optional, Tuple

from cros.factory.probe_info_service.app_engine import models
from cros.factory.probe_info_service.app_engine import probe_tool_manager
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.probe_info_service.app_engine import ps_storage_connector
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


_ProbeInfoParsedResult = stubby_pb2.ProbeInfoParsedResult


def GetProbeDataSourceComponentName(component_identity):
  return f'AVL_{component_identity.qual_id}'


def _DeriveSortableValueFromProbeParameter(probe_parameter):
  value_type = probe_parameter.WhichOneof('value')
  if value_type is None:
    return (probe_parameter.name,)
  probe_parameter_value = getattr(probe_parameter, value_type)
  # The value of `value_type` determines the type of `probe_parameter_value`.
  # And since the tuple comparison compares the elements from the begin,
  # placing `value_type` before `probe_parameter_value` prevents `TypeError`
  # from element comparisons.
  return (probe_parameter.name, value_type, probe_parameter_value)


def _InplaceNormalizeProbeInfo(probe_info):
  probe_info.probe_parameters.sort(key=_DeriveSortableValueFromProbeParameter)


class _ProbeDataSourceFactory(NamedTuple):
  probe_statement_type: int
  probe_data_source_generator: Callable[[], probe_tool_manager.ProbeDataSource]
  overridden_probe_data: Optional[ps_storage_connector.OverriddenProbeData]


class ProbeInfoService(protorpc_utils.ProtoRPCServiceBase):
  SERVICE_DESCRIPTOR = stubby_pb2.DESCRIPTOR.services_by_name[
      'ProbeInfoService']

  MSG_NO_PROBE_STATEMENT_PREVIEW_INVALID_AVL_DATA = (
      '(no preview available due to the invalid data from AVL)')

  def __init__(self):
    self._probe_tool_manager = probe_tool_manager.ProbeToolManager()
    self._ps_storage_connector = (
        ps_storage_connector.GetProbeStatementStorageConnector())
    self._avl_probe_entry_mngr = models.AVLProbeEntryManager()

  @protorpc_utils.ProtoRPCServiceMethod
  def GetProbeSchema(self, request):
    del request  # unused
    response = stubby_pb2.GetProbeSchemaResponse()
    response.probe_schema.CopyFrom(self._probe_tool_manager.GetProbeSchema())
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def ValidateProbeInfo(self, request: stubby_pb2.ValidateProbeInfoRequest):
    response = stubby_pb2.ValidateProbeInfoResponse()

    unused_converted_probe_info, parsed_result = (
        self._probe_tool_manager.ValidateProbeInfo(request.probe_info,
                                                   not request.is_qual))
    response.probe_info_parsed_result.CopyFrom(parsed_result)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetQualProbeTestBundle(self,
                             request: stubby_pb2.GetQualProbeTestBundleRequest):
    response = stubby_pb2.GetQualProbeTestBundleResponse()

    self._UpdateCompProbeInfo(request.qual_probe_info)
    probe_data_source_factory = self._GetProbeDataSourceFactory(
        request.qual_probe_info.component_identity)
    gen_result = self._probe_tool_manager.GenerateProbeBundlePayload(
        [probe_data_source_factory.probe_data_source_generator()])

    response.probe_info_parsed_result.CopyFrom(
        gen_result.probe_info_parsed_results[0])
    if gen_result.output is None:
      response.status = response.INVALID_PROBE_INFO
    else:
      response.status = response.SUCCEED
      response.test_bundle_payload = gen_result.output.content
      response.test_bundle_file_name = gen_result.output.name

    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def UploadQualProbeTestResult(
      self, request: stubby_pb2.UploadQualProbeTestResultRequest):
    response = stubby_pb2.UploadQualProbeTestResultResponse()

    self._UpdateCompProbeInfo(request.qual_probe_info)
    component_identity = request.qual_probe_info.component_identity
    probe_data_source_factory = self._GetProbeDataSourceFactory(
        component_identity)
    data_source = probe_data_source_factory.probe_data_source_generator()

    try:
      result = self._probe_tool_manager.AnalyzeQualProbeTestResultPayload(
          data_source, request.test_result_payload)
    except probe_tool_manager.PayloadInvalidError as e:
      response.is_uploaded_payload_valid = False
      response.uploaded_payload_error_msg = str(e)
      return response

    probe_statement_type = probe_data_source_factory.probe_statement_type
    if probe_statement_type != stubby_pb2.ProbeMetadata.AUTO_GENERATED:
      if result.result_type == result.PASSED:
        self._ps_storage_connector.MarkOverriddenProbeStatementTested(
            component_identity.qual_id, '')
    else:
      entry = self._avl_probe_entry_mngr.GetAVLProbeEntry(
          component_identity.component_id, component_identity.qual_id)
      if not entry:
        raise protorpc_utils.ProtoRPCException(
            protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT,
            'Got an unexpected AVL ID.')
      entry.is_tested = result.result_type == result.PASSED
      entry.is_justified_for_overridden = (
          result.result_type == result.INTRIVIAL_ERROR)
      self._avl_probe_entry_mngr.SaveAVLProbeEntry(entry)

    response.is_uploaded_payload_valid = True
    response.probe_info_test_result.CopyFrom(result)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetDeviceProbeConfig(self,
                           request: stubby_pb2.GetDeviceProbeConfigRequest):
    response = stubby_pb2.GetDeviceProbeConfigResponse()

    probe_data_sources = []
    for comp_probe_info in request.component_probe_infos:
      self._UpdateCompProbeInfo(comp_probe_info)
      probe_data_source_factory = self._GetDeviceProbeDataSourceFactory(
          comp_probe_info.component_identity)
      probe_data_sources.append(
          probe_data_source_factory.probe_data_source_generator())

    gen_result = self._probe_tool_manager.GenerateProbeBundlePayload(
        probe_data_sources)

    for pi_parsed_result in gen_result.probe_info_parsed_results:
      response.probe_info_parsed_results.append(pi_parsed_result)
    if gen_result.output is None:
      response.status = response.INVALID_PROBE_INFO
    else:
      response.status = response.SUCCEED
      response.generated_config_payload = gen_result.output.content
      response.generated_config_file_name = gen_result.output.name

    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def UploadDeviceProbeResult(
      self, request: stubby_pb2.UploadDeviceProbeResultRequest):
    response = stubby_pb2.UploadDeviceProbeResultResponse()

    probe_data_source_factories = []
    for comp_probe_info in request.component_probe_infos:
      self._UpdateCompProbeInfo(comp_probe_info)
      probe_data_source_factories.append(
          self._GetDeviceProbeDataSourceFactory(
              comp_probe_info.component_identity))
    probe_data_sources = [
        f.probe_data_source_generator() for f in probe_data_source_factories
    ]

    try:
      analyzed_result = (
          self._probe_tool_manager.AnalyzeDeviceProbeResultPayload(
              probe_data_sources, request.probe_result_payload))
    except probe_tool_manager.PayloadInvalidError as e:
      response.upload_status = response.PAYLOAD_INVALID_ERROR
      response.error_msg = str(e)
      return response

    if analyzed_result.intrivial_error_msg:
      response.upload_status = response.INTRIVIAL_ERROR
      response.error_msg = analyzed_result.intrivial_error_msg
      return response

    for i, probe_data_source_factory in enumerate(probe_data_source_factories):
      if (analyzed_result.probe_info_test_results[i].result_type ==
          stubby_pb2.ProbeInfoParsedResult.PASSED):
        ps_type = probe_data_source_factory.probe_statement_type
        component_identity = request.component_probe_infos[i].component_identity
        if ps_type == stubby_pb2.ProbeMetadata.AUTO_GENERATED:
          avl_entry = self._avl_probe_entry_mngr.GetAVLProbeEntry(
              component_identity.component_id, component_identity.qual_id)
          if not avl_entry:
            raise protorpc_utils.ProtoRPCException(
                protorpc_utils.RPCCANONICALErrorCode.INVALID_ARGUMENT,
                'Invalid AVL ID.')
          if not avl_entry.is_tested:
            avl_entry.is_tested = True
            self._avl_probe_entry_mngr.SaveAVLProbeEntry(avl_entry)
        else:
          device_id = ('' if ps_type == stubby_pb2.ProbeMetadata.QUAL_OVERRIDDEN
                       else component_identity.device_id)
          probe_data_source_factory.overridden_probe_data.is_tested = True
          self._ps_storage_connector.MarkOverriddenProbeStatementTested(
              component_identity.qual_id, device_id)

    response.upload_status = response.SUCCEED
    response.probe_info_test_results.extend(
        analyzed_result.probe_info_test_results)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def CreateOverriddenProbeStatement(
      self, request: stubby_pb2.CreateOverriddenProbeStatementRequest):
    response = stubby_pb2.CreateOverriddenProbeStatementResponse()

    comp_identity = request.component_probe_info.component_identity
    probe_info = request.component_probe_info.probe_info

    if self._ps_storage_connector.TryLoadOverriddenProbeData(
        comp_identity.qual_id, comp_identity.device_id):
      response.status = response.ALREADY_OVERRIDDEN_ERROR
      return response

    # Try to generate a default overridden probe statement from the given
    # probe info.
    data_source = self._probe_tool_manager.CreateProbeDataSource(
        GetProbeDataSourceComponentName(comp_identity), probe_info)
    unused_pi_parsed_result, ps = (
        self._probe_tool_manager.DumpProbeDataSource(data_source))
    if ps is None:
      ps = self._probe_tool_manager.GenerateDummyProbeStatement(data_source)

    result_msg = self._ps_storage_connector.SetProbeStatementOverridden(
        comp_identity.qual_id, comp_identity.device_id, ps)

    response.status = response.SUCCEED
    response.result_msg = result_msg
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetProbeMetadata(self, request: stubby_pb2.GetProbeMetadataRequest):
    response = stubby_pb2.GetProbeMetadataResponse()

    for comp_probe_info in request.component_probe_infos:
      entry, unused_parsed_result = self._UpdateCompProbeInfo(comp_probe_info)
      probe_data_source_factory = self._GetDeviceProbeDataSourceFactory(
          comp_probe_info.component_identity)
      probe_statement_type = probe_data_source_factory.probe_statement_type
      if probe_statement_type != stubby_pb2.ProbeMetadata.AUTO_GENERATED:
        probe_metadata = response.probe_metadatas.add(
            probe_statement_type=probe_data_source_factory.probe_statement_type,
            is_tested=probe_data_source_factory.overridden_probe_data.is_tested)
      else:
        probe_metadata = response.probe_metadatas.add(
            probe_statement_type=stubby_pb2.ProbeMetadata.AUTO_GENERATED,
            is_tested=entry.is_tested,
            is_proved_ready_for_overridden=entry.is_justified_for_overridden)

      if request.include_probe_statement_preview:
        gen_result = self._probe_tool_manager.GenerateRawProbeStatement(
            probe_data_source_factory.probe_data_source_generator())
        probe_metadata.probe_statement_preview = (
            gen_result.output if gen_result.output is not None else
            self.MSG_NO_PROBE_STATEMENT_PREVIEW_INVALID_AVL_DATA)

    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetDeviceComponentHwidInfo(
      self, request: stubby_pb2.GetDeviceComponentHwidInfoRequest):
    response = stubby_pb2.GetDeviceComponentHwidInfoResponse()
    for comp_identity in request.component_identities:
      entry = self._avl_probe_entry_mngr.GetAVLProbeEntry(
          comp_identity.component_id, comp_identity.qual_id)
      if not entry or not entry.is_valid:
        continue
      comp_probe_info = stubby_pb2.ComponentProbeInfo(
          component_identity=comp_identity, probe_info=entry.probe_info)
      metadata = stubby_pb2.ProbeMetadata(
          probe_statement_type=stubby_pb2.ProbeMetadata.AUTO_GENERATED,
          is_tested=entry.is_tested,
          is_proved_ready_for_overridden=entry.is_justified_for_overridden)
      response.component_hwid_infos.add(component_probe_info=comp_probe_info,
                                        metadata=metadata)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def UploadDeviceComponentHwidResult(
      self, request: stubby_pb2.UploadDeviceComponentHwidResultRequest):
    del request
    return stubby_pb2.UploadDeviceComponentHwidResultResponse()

  def _UpdateCompProbeInfo(
      self, comp_probe_info: stubby_pb2.ComponentProbeInfo
  ) -> Tuple[models.AVLProbeEntry, stubby_pb2.ProbeInfoParsedResult]:
    converted_probe_info, parsed_result = (
        self._probe_tool_manager.ValidateProbeInfo(
            comp_probe_info.probe_info,
            not comp_probe_info.component_identity.qual_id))
    _InplaceNormalizeProbeInfo(converted_probe_info)
    need_save, entry = self._avl_probe_entry_mngr.GetOrCreateAVLProbeEntry(
        comp_probe_info.component_identity.component_id,
        comp_probe_info.component_identity.qual_id)
    if entry.probe_info != converted_probe_info:
      entry.probe_info = converted_probe_info
      entry.is_valid = (
          parsed_result.result_type == _ProbeInfoParsedResult.ResultType.PASSED)
      entry.is_tested = False
      entry.is_justified_for_overridden = False
      need_save = True
    if need_save:
      self._avl_probe_entry_mngr.SaveAVLProbeEntry(entry)
    return entry, parsed_result

  @protorpc_utils.ProtoRPCServiceMethod
  def UpdateComponentProbeInfo(
      self, request: stubby_pb2.UpdateComponentProbeInfoRequest):
    response = stubby_pb2.UpdateComponentProbeInfoResponse()

    for comp_probe_info in request.component_probe_infos:
      unused_entry, probe_info_parsed_result = self._UpdateCompProbeInfo(
          comp_probe_info)
      response.probe_info_parsed_results.append(probe_info_parsed_result)

    return response

  def _GetProbeDataSourceFactory(self, component_identity):
    """Gets the probe data source for the component.

    It loads and returns the correct probe data source factory with the
    following orders:
      1.  If there's a device agnostic overridden, uses it as the data source.
      2.  If there's AVL-generated probe info, uses it as the data source.
      3.  Otherwise, raises `protorpc_utils.ProtoRPCException` to indicate an
          invalid argument error.

    Args:
      component_identity: AVL IDs of the target.

    Returns:
      The factory instance for the loaded probe data source.

    Raises:
      `protorpc_utils.ProtoRPCException`: If no probe info for the given AVL ID.
    """
    component_name = GetProbeDataSourceComponentName(component_identity)
    ret = self._TryGetProbeDataSourceFactoryForOverridden(
        component_identity.qual_id, '',
        stubby_pb2.ProbeMetadata.QUAL_OVERRIDDEN, component_name)
    if ret:
      return ret

    entry = self._avl_probe_entry_mngr.GetAVLProbeEntry(
        component_identity.component_id, component_identity.qual_id)
    if not entry:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT,
          'Invalid AVL ID.')
    return _ProbeDataSourceFactory(
        stubby_pb2.ProbeMetadata.AUTO_GENERATED,
        functools.partial(self._probe_tool_manager.CreateProbeDataSource,
                          component_name, entry.probe_info), None)

  def _GetDeviceProbeDataSourceFactory(self, component_identity):
    """Gets the probe data source for the component on the specific device.

    It loads and returns the correct probe data source factory with the
    following orders:
      1.  If there's a device specific overridden, uses it as the data source.
      2.  If there's a device agnostic overridden, uses it as the data source.
      3.  If there's AVL-generated probe info, uses it as the data source.
      4.  Otherwise, raises `protorpc_utils.ProtoRPCException` to indicate an
          invalid argument error.

    Args:
      component_identity: AVL IDs and the device ID of the target.

    Returns:
      The factory instance for the loaded probe data source.

    Raises:
      `protorpc_utils.ProtoRPCException`: If no probe info for the given AVL ID.
    """
    component_name = GetProbeDataSourceComponentName(component_identity)
    if component_identity.device_id:
      ret = self._TryGetProbeDataSourceFactoryForOverridden(
          component_identity.qual_id, component_identity.device_id,
          stubby_pb2.ProbeMetadata.DEVICE_OVERRIDDEN, component_name)
      if ret:
        return ret
    return self._GetProbeDataSourceFactory(component_identity)

  def _TryGetProbeDataSourceFactoryForOverridden(
      self, qual_id, device_id, probe_statement_type, component_name):
    probe_data = self._ps_storage_connector.TryLoadOverriddenProbeData(
        qual_id, device_id)
    if not probe_data:
      return None
    return _ProbeDataSourceFactory(
        probe_statement_type,
        functools.partial(self._probe_tool_manager.LoadProbeDataSource,
                          component_name, probe_data.probe_statement),
        probe_data)
