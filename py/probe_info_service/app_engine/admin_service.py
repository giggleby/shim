# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe_info_service.app_engine import admin_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import migration_utils
from cros.factory.probe_info_service.app_engine import models
from cros.factory.probe_info_service.app_engine import probe_tool_utils
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.probe_info_service.app_engine import stubby_handler
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


def _ConvertMigrationResultCase(case: migration_utils.MigrationResultCase):
  return admin_pb2.MigrationScriptResult.ResultCase.Value(case.name)


AdminServiceProtoRPCBase = protorpc_utils.CreateProtoRPCServiceClass(
    'AdminServiceProtoRPCBase',
    admin_pb2.DESCRIPTOR.services_by_name['AdminService'])


class AdminServiceServerStub(AdminServiceProtoRPCBase):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._migration_manager = migration_utils.MigrationManager()

    self._pi_analyzer = probe_tool_utils.CreateProbeInfoAnalyzer()
    self._avl_probe_entry_mngr = models.AVLProbeEntryManager()

  @protorpc_utils.ProtoRPCServiceMethod
  def RunMigrationScripts(self, request):
    del request  # unused
    response = admin_pb2.RunMigrationScriptsResponse()

    while True:
      report = self._migration_manager.RunNextPendingMigrationScript()
      if not report:
        break
      response.reports.add(
          script_index=report.script_order,
          result_case=_ConvertMigrationResultCase(report.result_case))
      if report.result_case != migration_utils.MigrationResultCase.SUCCESS:
        break

    return response

  @protorpc_utils.ProtoRPCServiceMethod
  def ForceForwardMigrationProgress(self, request):
    response = admin_pb2.ForceForwardMigrationProgressResponse()

    self._migration_manager.ForwardProgress(request.script_index)

    return response

  def _UpdateCompProbeInfo(
      self,
      comp_probe_info: stubby_pb2.ComponentProbeInfo,
  ) -> stubby_pb2.ProbeInfoParsedResult:
    parsed_result = self._pi_analyzer.ValidateProbeInfo(
        comp_probe_info.probe_info,
        not comp_probe_info.component_identity.qual_id)
    normalized_probe_info = stubby_handler.GetNormalizedProbeInfo(
        comp_probe_info.probe_info)
    need_save, entry = self._avl_probe_entry_mngr.GetOrCreateAVLProbeEntry(
        comp_probe_info.component_identity.component_id,
        comp_probe_info.component_identity.qual_id)
    if entry.probe_info != normalized_probe_info.probe_info:
      entry.probe_info = normalized_probe_info.probe_info
      need_save = True
    if need_save:
      self._avl_probe_entry_mngr.SaveAVLProbeEntry(entry)
    return parsed_result

  @protorpc_utils.ProtoRPCServiceMethod
  def ModifyComponentProbeInfo(self, request):
    return admin_pb2.ModifyComponentProbeInfoResponse(
        probe_info_parsed_results=[
            self._UpdateCompProbeInfo(comp_probe_info)
            for comp_probe_info in request.component_probe_infos
        ])
