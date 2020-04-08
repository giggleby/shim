# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe_info_service.app_engine import probe_metainfo_connector
from cros.factory.probe_info_service.app_engine import probe_tool_manager
from cros.factory.probe_info_service.app_engine import protorpc_utils
# pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import stubby_pb2
# pylint: enable=no-name-in-module


class ProbeInfoService(protorpc_utils.ProtoRPCServiceBase):
  SERVICE_DESCRIPTOR = stubby_pb2.DESCRIPTOR.services_by_name[
      'ProbeInfoService']

  def __init__(self):
    self._probe_tool_manager = probe_tool_manager.ProbeToolManager()
    self._probe_metainfo_connector = (
        probe_metainfo_connector.GetProbeMetaInfoConnectorInstance())

  @protorpc_utils.ProtoRPCServiceMethod
  def GetProbeSchema(self, request):
    del request  # unused
    response = stubby_pb2.GetProbeSchemaResponse()
    response.probe_schema.CopyFrom(self._probe_tool_manager.GetProbeSchema())
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def ValidateProbeInfo(self, request):
    response = stubby_pb2.ValidateProbeInfoResponse()
    response.probe_info_parsed_result.CopyFrom(
        self._probe_tool_manager.ValidateProbeInfo(request.probe_info,
                                                   not request.is_qual))
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetQualProbeTestBundle(self, request):
    response = stubby_pb2.GetQualProbeTestBundleResponse()

    probe_meta_info = self._probe_metainfo_connector.GetQualProbeMetaInfo(
        request.qual_probe_info.component_identity.qual_id)
    if probe_meta_info.is_overridden:
      response.result_type = response.UNKNOWN_ERROR
      response.error_msg = 'The feature is not implemented yet.'
      return response

    data_source = self._probe_tool_manager.CreateProbeDataSourceFromProbeInfo(
        self._GetComponentName(request.qual_probe_info.component_identity),
        request.qual_probe_info.probe_info)
    gen_result = self._probe_tool_manager.GenerateQualProbeTestBundlePayload(
        data_source)

    response.probe_info_parsed_result.CopyFrom(
        gen_result.probe_info_parsed_result)
    if gen_result.payload is None:
      response.result_type = response.INVALID_PROBE_INFO
    else:
      response.result_type = response.SUCCEED
      response.test_bundle_payload = gen_result.payload

    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def UploadQualProbeTestResult(self, request):
    response = stubby_pb2.UploadQualProbeTestResultResponse()

    probe_meta_info = self._probe_metainfo_connector.GetQualProbeMetaInfo(
        request.qual_probe_info.component_identity.qual_id)
    assert not probe_meta_info.is_overridden

    data_source = self._probe_tool_manager.CreateProbeDataSourceFromProbeInfo(
        self._GetComponentName(request.qual_probe_info.component_identity),
        request.qual_probe_info.probe_info)
    try:
      result = self._probe_tool_manager.AnalyzeQualProbeTestResultPayload(
          data_source, request.test_result_payload)
    except probe_tool_manager.PayloadInvalidError as e:
      response.is_uploaded_payload_valid = False
      response.uploaded_payload_error_msg = str(e)
      return response
    if result.result_type == result.PASSED:
      probe_meta_info.last_tested_probe_info_fp = data_source.probe_info_fp
      self._probe_metainfo_connector.UpdateQualProbeMetaInfo(
          request.qual_probe_info.component_identity.qual_id, probe_meta_info)

    response.is_uploaded_payload_valid = True
    response.probe_info_test_result.CopyFrom(result)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def GetProbeMetadata(self, request):
    response = stubby_pb2.GetProbeMetadataResponse()

    for comp_probe_info in request.component_probe_infos:
      if comp_probe_info.component_identity.device_id:
        raise NotImplementedError
      data_source = self._probe_tool_manager.CreateProbeDataSourceFromProbeInfo(
          self._GetComponentName(comp_probe_info.component_identity),
          comp_probe_info.probe_info)
      metainfo = self._probe_metainfo_connector.GetQualProbeMetaInfo(
          comp_probe_info.component_identity.qual_id)
      if metainfo.is_overridden:
        raise NotImplementedError
      response.probe_metadatas.add(
          is_tested=(
              metainfo.last_tested_probe_info_fp == data_source.probe_info_fp))

    return response

  def _GetComponentName(self, component_identity):
    return 'AVL_%d-%s-%s' % (component_identity.qual_id,
                             component_identity.device_id,
                             component_identity.readable_label)
