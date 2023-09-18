# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import functools
from typing import Callable, NamedTuple, Optional, Tuple

from cros.factory.probe_info_service.app_engine import models
from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine import probe_tool_utils
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.probe_info_service.app_engine import ps_storages
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


_ProbeInfoParsedResult = stubby_pb2.ProbeInfoParsedResult


def GetProbeDataSourceComponentName(component_identity):
  if component_identity.qual_id:
    return f'AVL_QUAL_{component_identity.qual_id}'
  return f'AVL_COMP_{component_identity.component_id}'


def _DeriveSortableValueFromProbeParameter(probe_parameter):
  value_type = probe_parameter.WhichOneof('value')
  if value_type is None:
    return (probe_parameter.name, )
  probe_parameter_value = getattr(probe_parameter, value_type)
  # The value of `value_type` determines the type of `probe_parameter_value`.
  # And since the tuple comparison compares the elements from the begin,
  # placing `value_type` before `probe_parameter_value` prevents `TypeError`
  # from element comparisons.
  return (probe_parameter.name, value_type, probe_parameter_value)


def GetNormalizedProbeInfo(probe_info):
  normalized_probe_info = copy.deepcopy(probe_info)
  normalized_probe_info.probe_parameters.sort(
      key=_DeriveSortableValueFromProbeParameter)
  return normalized_probe_info


class _ProbeDataSourceLookupResult(NamedTuple):
  # `source_type` captures the enum item of
  # `stubby_pb2.ProbeMetadata.ProbeStatementType`.  However that type is not
  # a valid annotation, so here it uses `int` instead.
  source_type: int
  probe_data_source: probe_info_analytics.IProbeDataSource
  is_tested: bool
  preview_generator: Callable[[], str]


ProbeInfoServiceProtoRPCBase = protorpc_utils.CreateProtoRPCServiceClass(
    'ProbeInfoServiceProtoRPCBase',
    stubby_pb2.DESCRIPTOR.services_by_name['ProbeInfoService'])


class ProbeInfoService(ProbeInfoServiceProtoRPCBase):

  MSG_NO_PROBE_STATEMENT_PREVIEW_INVALID_AVL_DATA = (
      '(no preview available due to the invalid data from AVL)')

  def __init__(self):
    self._pi_analyzer = probe_tool_utils.CreateProbeInfoAnalyzer()
    self._ps_storage_connector = ps_storages.GetProbeStatementStorageConnector()
    self._avl_probe_entry_mngr = models.AVLProbeEntryManager()

  @protorpc_utils.ProtoRPCServiceMethod
  def GetProbeSchema(self, request):
    del request  # unused
    response = stubby_pb2.GetProbeSchemaResponse()
    response.probe_schema.CopyFrom(self._pi_analyzer.GetProbeSchema())
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def ValidateProbeInfo(self, request: stubby_pb2.ValidateProbeInfoRequest):
    response = stubby_pb2.ValidateProbeInfoResponse()

    parsed_result = self._pi_analyzer.ValidateProbeInfo(request.probe_info,
                                                        not request.is_qual)
    response.probe_info_parsed_result.CopyFrom(parsed_result)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetQualProbeTestBundle(self,
                             request: stubby_pb2.GetQualProbeTestBundleRequest):
    response = stubby_pb2.GetQualProbeTestBundleResponse()

    self._UpdateCompProbeInfo(request.qual_probe_info)
    lookup_result = self._LookupProbeDataSource(
        request.qual_probe_info.component_identity,
        request.qual_probe_info.probe_info)
    gen_result = self._pi_analyzer.GenerateProbeBundlePayload(
        [lookup_result.probe_data_source])

    response.probe_info_parsed_result.CopyFrom(
        self._ConvertProbeInfoParsedResult(
            lookup_result, gen_result.probe_info_parsed_results[0]))
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
    probe_info = request.qual_probe_info.probe_info
    component_identity = request.qual_probe_info.component_identity
    lookup_result = self._LookupProbeDataSource(component_identity, probe_info)

    try:
      result = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
          lookup_result.probe_data_source, request.test_result_payload)
    except probe_info_analytics.PayloadInvalidError as e:
      response.is_uploaded_payload_valid = False
      response.uploaded_payload_error_msg = str(e)
      return response

    if lookup_result.source_type != stubby_pb2.ProbeMetadata.AUTO_GENERATED:
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

  def _ConvertProbeInfoParsedResult(
      self, lookup_result: _ProbeDataSourceLookupResult,
      parsed_result: stubby_pb2.ProbeInfoParsedResult
  ) -> stubby_pb2.ProbeInfoParsedResult:
    if (lookup_result.source_type == stubby_pb2.ProbeMetadata.AUTO_GENERATED or
        parsed_result.result_type != parsed_result.PROBE_PARAMETER_ERROR):
      return parsed_result
    converted_msg = stubby_pb2.ProbeInfoParsedResult()
    converted_msg.CopyFrom(parsed_result)
    converted_msg.result_type = converted_msg.OVERRIDDEN_PROBE_STATEMENT_ERROR
    return converted_msg

  @protorpc_utils.ProtoRPCServiceMethod
  def GetDeviceProbeConfig(self,
                           request: stubby_pb2.GetDeviceProbeConfigRequest):
    response = stubby_pb2.GetDeviceProbeConfigResponse()

    lookup_results = []
    for comp_probe_info in request.component_probe_infos:
      self._UpdateCompProbeInfo(comp_probe_info)
      lookup_results.append(
          self._LookupProbeDataSource(comp_probe_info.component_identity,
                                      comp_probe_info.probe_info))

    gen_result = self._pi_analyzer.GenerateProbeBundlePayload(
        [r.probe_data_source for r in lookup_results])

    for lookup_result, pi_parsed_result in zip(
        lookup_results, gen_result.probe_info_parsed_results):
      response.probe_info_parsed_results.append(
          self._ConvertProbeInfoParsedResult(lookup_result, pi_parsed_result))
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

    lookup_results = []
    for comp_probe_info in request.component_probe_infos:
      self._UpdateCompProbeInfo(comp_probe_info)
      lookup_results.append(
          self._LookupProbeDataSource(comp_probe_info.component_identity,
                                      comp_probe_info.probe_info))
    probe_data_sources = [r.probe_data_source for r in lookup_results]

    try:
      analyzed_result = (
          self._pi_analyzer.AnalyzeDeviceProbeResultPayload(
              probe_data_sources, request.probe_result_payload))
    except probe_info_analytics.PayloadInvalidError as e:
      response.upload_status = response.PAYLOAD_INVALID_ERROR
      response.error_msg = str(e)
      return response

    if analyzed_result.intrivial_error_msg:
      response.upload_status = response.INTRIVIAL_ERROR
      response.error_msg = analyzed_result.intrivial_error_msg
      return response

    for i, lookup_result in enumerate(lookup_results):
      if (analyzed_result.probe_info_test_results[i].result_type ==
          stubby_pb2.ProbeInfoParsedResult.PASSED):
        component_identity = request.component_probe_infos[i].component_identity
        if lookup_result.source_type == stubby_pb2.ProbeMetadata.AUTO_GENERATED:
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
          device_id = ('' if (lookup_result.source_type
                              == stubby_pb2.ProbeMetadata.QUAL_OVERRIDDEN) else
                       component_identity.device_id)
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
    data_source = self._pi_analyzer.CreateProbeDataSource(
        GetProbeDataSourceComponentName(comp_identity), probe_info)
    unused_pi_parsed_result, ps = (
        self._pi_analyzer.DumpProbeDataSource(data_source))
    if ps is None:
      ps = self._pi_analyzer.GenerateDummyProbeStatement(data_source)

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
      lookup_result = self._LookupProbeDataSource(
          comp_probe_info.component_identity, comp_probe_info.probe_info)
      if lookup_result.source_type != stubby_pb2.ProbeMetadata.AUTO_GENERATED:
        probe_metadata = response.probe_metadatas.add(
            probe_statement_type=lookup_result.source_type,
            is_tested=lookup_result.is_tested)
      else:
        probe_metadata = response.probe_metadatas.add(
            probe_statement_type=stubby_pb2.ProbeMetadata.AUTO_GENERATED,
            is_tested=entry.is_tested,
            is_proved_ready_for_overridden=entry.is_justified_for_overridden)

      if request.include_probe_statement_preview:
        probe_metadata.probe_statement_preview = (
            lookup_result.preview_generator())

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
    parsed_result = self._pi_analyzer.ValidateProbeInfo(
        comp_probe_info.probe_info,
        not comp_probe_info.component_identity.qual_id)
    normalized_probe_info = GetNormalizedProbeInfo(comp_probe_info.probe_info)
    need_save, entry = self._avl_probe_entry_mngr.GetOrCreateAVLProbeEntry(
        comp_probe_info.component_identity.component_id,
        comp_probe_info.component_identity.qual_id)
    if entry.probe_info != normalized_probe_info:
      entry.probe_info = normalized_probe_info
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

  def _GeneratePreviewForProbeDataSourceFromAVL(
      self, probe_data_source: probe_info_analytics.IProbeDataSource) -> str:
    gen_result = self._pi_analyzer.GenerateRawProbeStatement(probe_data_source)
    return (gen_result.output or
            self.MSG_NO_PROBE_STATEMENT_PREVIEW_INVALID_AVL_DATA)

  def _LookupProbeDataSource(self, component_identity,
                             probe_info=None) -> _ProbeDataSourceLookupResult:
    """Gets the probe data source for the component.

    It loads and returns the correct probe data source with the
    following orders:
      1.  If the device ID is specified and there's device specific overridden,
          uses it as the data source.
      2.  If there's a device agnostic overridden, uses it as the data source.
      3.  If there's AVL-generated probe info, uses it as the data source.
      4.  Otherwise, raises `protorpc_utils.ProtoRPCException` to indicate an
          invalid argument error.

    Args:
      component_identity: AVL IDs of the target.
      probe_info: If passed, use it as the probe info of the returned
          probe_data_source. Otherwise, use the probe info of the queried
          entry.

    Returns:
      The factory instance for the loaded probe data source.

    Raises:
      `protorpc_utils.ProtoRPCException`: If no probe info for the given AVL ID.
    """
    component_name = GetProbeDataSourceComponentName(component_identity)

    overridden_lookup_result = self._LookupOverriddenProbeDataSource(
        component_identity.qual_id, component_identity.device_id,
        component_name)
    if overridden_lookup_result:
      return overridden_lookup_result

    if component_identity.device_id:
      overridden_lookup_result = self._LookupOverriddenProbeDataSource(
          component_identity.qual_id, '', component_name)
      if overridden_lookup_result:
        return overridden_lookup_result

    entry = self._avl_probe_entry_mngr.GetAVLProbeEntry(
        component_identity.component_id, component_identity.qual_id)
    if entry:
      probe_data_source = self._pi_analyzer.CreateProbeDataSource(
          component_name,
          probe_info if probe_info is not None else entry.probe_info)
      preview_generator = functools.partial(
          self._GeneratePreviewForProbeDataSourceFromAVL, probe_data_source)
      return _ProbeDataSourceLookupResult(
          stubby_pb2.ProbeMetadata.AUTO_GENERATED, probe_data_source,
          entry.is_tested, preview_generator)

    raise protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT,
        'Invalid AVL ID.')

  def _LookupOverriddenProbeDataSource(
      self, qual_id: int, device_id: str,
      component_name: str) -> Optional[_ProbeDataSourceLookupResult]:
    overridden_data = self._ps_storage_connector.TryLoadOverriddenProbeData(
        qual_id, device_id)
    if not overridden_data:
      return None
    source_type = (
        stubby_pb2.ProbeMetadata.DEVICE_OVERRIDDEN
        if device_id else stubby_pb2.ProbeMetadata.QUAL_OVERRIDDEN)
    probe_info = self._pi_analyzer.LoadProbeInfo(
        overridden_data.probe_statement)
    probe_data_source = self._pi_analyzer.CreateProbeDataSource(
        component_name, probe_info)
    return _ProbeDataSourceLookupResult(source_type, probe_data_source,
                                        overridden_data.is_tested,
                                        lambda: overridden_data.probe_statement)
