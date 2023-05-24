# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""HWID Api definition.  Defines all the exposed API methods.

This file is also the place that all the binding is done for various components.
"""

from typing import Collection

from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper_module
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import decoding_apis
from cros.factory.hwid.service.appengine.hwid_api_helpers import project_info_apis
from cros.factory.hwid.service.appengine.hwid_api_helpers import self_service_helper as ss_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper as sku_helper_module
from cros.factory.hwid.service.appengine import ingestion
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils


KNOWN_BAD_HWIDS = ['DUMMY_HWID', 'dummy_hwid']
KNOWN_BAD_SUBSTR = [
    '.*TEST.*', '.*CHEETS.*', '^SAMS .*', '.* DEV$', '.*DOGFOOD.*'
]

_SESSION_CACHE_NAMESPACE = 'SessionCache'


class ProtoRPCService(common_helper.HWIDServiceShardBase):

  def __init__(self, config, *args, **kwargs):
    super().__init__(*args, **kwargs)
    hwid_repo_manager = config.hwid_repo_manager
    avl_converter_manager = config.avl_converter_manager
    session_cache_adapter = memcache_adapter.MemcacheAdapter(
        namespace=_SESSION_CACHE_NAMESPACE)
    avl_metadata_manager = config.avl_metadata_manager

    self._hwid_action_manager = config.hwid_action_manager
    self._hwid_db_data_manager = config.hwid_db_data_manager
    self._ss_helper = ss_helper.SelfServiceHelper(
        self._hwid_action_manager,
        hwid_repo_manager,
        self._hwid_db_data_manager,
        avl_converter_manager,
        session_cache_adapter,
        avl_metadata_manager,
        ss_helper.FeatureMatcherBuilderImpl,
    )

  @classmethod
  def CreateInstance(cls, config):
    """Creates RPC service instance."""
    return cls(config)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateConfig(self, request):  # pylint: disable=unused-argument
    """Validate the config.

    Args:
      request: a ValidateConfigRequest.

    Returns:
      A ValidateConfigAndUpdateResponse containing an error message if an error
      occurred.
    """
    return hwid_api_messages_pb2.ValidateConfigResponse(
        status=hwid_api_messages_pb2.Status.SERVER_ERROR,
        error_message='deprecated API')

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateConfigAndUpdateChecksum(self, request):  # pylint: disable=unused-argument
    """Validate the config and update its checksum.

    Args:
      request: a ValidateConfigAndUpdateChecksumRequest.

    Returns:
      A ValidateConfigAndUpdateChecksumResponse containing either the updated
      config or an error message.  Also the cid, qid, status will also be
      responded if the component name follows the naming rule.
    """
    return hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
        status=hwid_api_messages_pb2.Status.SERVER_ERROR,
        error_message='deprecated API')

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetHwidDbEditableSection(self, request):
    return self._ss_helper.GetHWIDDBEditableSection(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateHwidDbEditableSectionChange(self, request):
    raise protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.UNIMPLEMENTED,
        'Deprecated. Use AnalyzeHwidDbEditableSection instead.')

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

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def CreateHwidDbInitCl(self, request):
    return self._ss_helper.CreateHWIDDBInitCL(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def SetChangeClBotApprovalStatus(self, request):
    return self._ss_helper.SetChangeCLBotApprovalStatus(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def SetFirmwareInfoSupportStatus(self, request):
    return self._ss_helper.SetFirmwareInfoSupportStatus(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def SplitHwidDbChange(self, request):
    return self._ss_helper.SplitHWIDDBChange(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def CreateSplittedHwidDbCls(self, request):
    return self._ss_helper.CreateSplittedHWIDDBCLs(request)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def UpdateAudioCodecKernelNames(self, request):
    return self._ss_helper.UpdateAudioCodecKernelNames(request)


def GetAllHWIDServiceShards(
    config) -> Collection[common_helper.HWIDServiceShardBase]:
  project_info_shard = project_info_apis.ProjectInfoShard(
      config.hwid_action_manager, config.hwid_db_data_manager)

  goldeneye_memcache_adapter = memcache_adapter.MemcacheAdapter(
      namespace=ingestion.GOLDENEYE_MEMCACHE_NAMESPACE)
  bc_helper = bc_helper_module.BOMAndConfiglessHelper(
      config.decoder_data_manager, config.bom_data_cacher)
  sku_helper = sku_helper_module.SKUHelper(config.decoder_data_manager)
  get_bom_shard = decoding_apis.GetBOMShard(
      config.hwid_action_manager, bc_helper)
  get_sku_shard = decoding_apis.GetSKUShard(
      config.hwid_action_manager, bc_helper, sku_helper)
  get_dut_label_shard = decoding_apis.GetDUTLabelShard(
      config.decoder_data_manager, goldeneye_memcache_adapter,
      bc_helper, sku_helper, config.hwid_action_manager)

  return [
      project_info_shard,
      get_bom_shard,
      get_sku_shard,
      get_dut_label_shard,
      ProtoRPCService.CreateInstance(config),
  ]
