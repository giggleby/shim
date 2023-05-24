# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Optional

from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action_manager as hwid_action_mngr_module
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils


def _NormalizeProjectString(string: str) -> Optional[str]:
  """Normalizes a string to account for things like case."""
  return string.strip().upper() if string else None


class ProjectInfoShard(common_helper.HWIDServiceShardBase):

  def __init__(self,
               hwid_action_manager: hwid_action_mngr_module.HWIDActionManager,
               hwid_db_data_manager: hwid_db_data.HWIDDBDataManager):
    self._hwid_action_manager = hwid_action_manager
    self._hwid_db_data_manager = hwid_db_data_manager

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetProjects(self, request):
    """Return all of the supported projects in sorted order."""
    versions = list(request.versions) if request.versions else None
    metadata_list = self._hwid_db_data_manager.ListHWIDDBMetadata(
        versions=versions)
    projects = [m.project for m in metadata_list]

    response = hwid_api_messages_pb2.ProjectsResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, projects=sorted(projects))
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetHwids(self, request):
    """Return a filtered list of HWIDs for the given project."""
    project = _NormalizeProjectString(request.project)
    parse_filter_field = lambda value: set(filter(None, value)) or None
    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
      hwids = action.EnumerateHWIDs(
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
    project = _NormalizeProjectString(request.project)
    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
      classes = action.GetComponentClasses()
    except (KeyError, ValueError, RuntimeError) as ex:
      return hwid_api_messages_pb2.ComponentClassesResponse(
          status=common_helper.ConvertExceptionToStatus(ex), error=str(ex))

    return hwid_api_messages_pb2.ComponentClassesResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS, component_classes=classes)

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def GetComponents(self, request):
    """Return a filtered list of components for the given project."""
    project = _NormalizeProjectString(request.project)
    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
      components = action.GetComponents(
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
