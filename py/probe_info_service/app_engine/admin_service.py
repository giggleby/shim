# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe_info_service.app_engine import admin_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import migration_utils
from cros.factory.probe_info_service.app_engine import protorpc_utils


def _ConvertMigrationResultCase(case: migration_utils.MigrationResultCase):
  return admin_pb2.MigrationScriptResult.ResultCase.Value(case.name)


class AdminServiceServerStub(protorpc_utils.ProtoRPCServiceBase):
  SERVICE_DESCRIPTOR = admin_pb2.DESCRIPTOR.services_by_name['AdminService']

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._migration_manager = migration_utils.MigrationManager()

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
