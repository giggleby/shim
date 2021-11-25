# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""HWID Api definition.  Defines all the exposed API methods.

This file is also the place that all the binding is done for various components.
"""

import hashlib
import logging
import textwrap
import time
from typing import List, NamedTuple, Tuple

from cros.chromeoshwid import update_checksum
from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.config import CONFIG
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import dut_label_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.service.appengine import ingestion
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.v3 import common as v3_common
from cros.factory.hwid.v3 import contents_analyzer
# pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2
# pylint: enable=import-error, no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils


KNOWN_BAD_HWIDS = ['DUMMY_HWID', 'dummy_hwid']
KNOWN_BAD_SUBSTR = [
    '.*TEST.*', '.*CHEETS.*', '^SAMS .*', '.* DEV$', '.*DOGFOOD.*'
]

_HWID_DB_COMMIT_STATUS_TO_PROTOBUF_HWID_CL_STATUS = {
    hwid_repo.HWIDDBCLStatus.NEW:
        hwid_api_messages_pb2.HwidDbEditableSectionChangeClInfo.PENDING,
    hwid_repo.HWIDDBCLStatus.MERGED:
        hwid_api_messages_pb2.HwidDbEditableSectionChangeClInfo.MERGED,
    hwid_repo.HWIDDBCLStatus.ABANDONED:
        hwid_api_messages_pb2.HwidDbEditableSectionChangeClInfo.ABANDONED,
}

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


class _HWIDStatusConversionError(Exception):
  """Indicate a failure to convert HWID component status to
  `hwid_api_messages_pb2.SupportStatus`."""


def _ConvertToNameChangedComponent(name_changed_comp_info):
  """Converts an instance of `NameChangedComponentInfo` to
  hwid_api_messages_pb2.NameChangedComponent message."""
  support_status_descriptor = (
      hwid_api_messages_pb2.NameChangedComponent.SupportStatus.DESCRIPTOR)
  status_val = support_status_descriptor.values_by_name.get(
      name_changed_comp_info.status.upper())
  if status_val is None:
    raise _HWIDStatusConversionError(
        "Unknown status: '%s'" % name_changed_comp_info.status)
  return hwid_api_messages_pb2.NameChangedComponent(
      cid=name_changed_comp_info.cid, qid=name_changed_comp_info.qid,
      support_status=status_val.number,
      component_name=name_changed_comp_info.comp_name,
      has_cid_qid=name_changed_comp_info.has_cid_qid)


class _HWIDDBChangeInfo(NamedTuple):
  """A record class to hold a single change of HWID DB."""
  fingerprint: str
  curr_hwid_db_contents: str
  new_hwid_db_contents: str


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
        entries.extend(_ConvertToNameChangedComponent(c) for c in comps)
      except _HWIDStatusConversionError as ex:
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
    live_hwid_repo = _hwid_repo_manager.GetLiveHWIDRepo()
    hwid_db_contents = _LoadHWIDDBV3Contents(live_hwid_repo, request.project)
    unused_header, hwid_db_editable_section_lines = _SplitHWIDDBV3Sections(
        hwid_db_contents)
    response = hwid_api_messages_pb2.GetHwidDbEditableSectionResponse(
        hwid_db_editable_section=_NormalizeAndJoinHWIDDBEditableSectionLines(
            hwid_db_editable_section_lines))
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def ValidateHwidDbEditableSectionChange(self, request):
    live_hwid_repo = _hwid_repo_manager.GetLiveHWIDRepo()
    change_info = _GetHWIDDBChangeInfo(live_hwid_repo, request.project,
                                       request.new_hwid_db_editable_section)
    response = (
        hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeResponse(
            validation_token=change_info.fingerprint))
    try:
      unused_model, new_hwid_comps = _hwid_validator.ValidateChange(
          change_info.new_hwid_db_contents, change_info.curr_hwid_db_contents)
    except hwid_validator.ValidationError as ex:
      logging.exception('Validation failed')
      for error in ex.errors:
        response.validation_result.errors.add(
            code=(response.validation_result.SCHEMA_ERROR
                  if error.code == hwid_validator.ErrorCode.SCHEMA_ERROR else
                  response.validation_result.CONTENTS_ERROR),
            message=error.message)
      return response
    try:
      name_changed_comps = {
          comp_cls: [_ConvertToNameChangedComponent(c) for c in comps]
          for comp_cls, comps in new_hwid_comps.items()
      }
    except _HWIDStatusConversionError as ex:
      response.validation_result.errors.add(
          code=response.validation_result.CONTENTS_ERROR, message=str(ex))
      return response
    field = response.validation_result.name_changed_components_per_category
    for comp_cls, name_changed_comps in name_changed_comps.items():
      field.get_or_create(comp_cls).entries.extend(name_changed_comps)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def CreateHwidDbEditableSectionChangeCl(self, request):
    live_hwid_repo = _hwid_repo_manager.GetLiveHWIDRepo()
    change_info = _GetHWIDDBChangeInfo(live_hwid_repo, request.project,
                                       request.new_hwid_db_editable_section)
    if change_info.fingerprint != request.validation_token:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.ABORTED,
          detail='The validation token is expired.')

    commit_msg = textwrap.dedent(f"""\
        ({int(time.time())}) {request.project}: HWID Config Update

        Requested by: {request.original_requester}
        Warning: all posted comments will be sent back to the requester.

        {request.description}

        BUG=b:{request.bug_number}
        """)
    try:
      cl_number = live_hwid_repo.CommitHWIDDB(
          request.project, change_info.new_hwid_db_contents, commit_msg,
          request.reviewer_emails, request.cc_emails, request.auto_approved)
    except hwid_repo.HWIDRepoError:
      logging.exception(
          'Caught unexpected exception while uploading a HWID CL.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
    resp = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClResponse(
        cl_number=cl_number)
    return resp

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def BatchGetHwidDbEditableSectionChangeClInfo(self, request):
    response = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))
    for cl_number in request.cl_numbers:
      try:
        commit_info = _hwid_repo_manager.GetHWIDDBCLInfo(cl_number)
      except hwid_repo.HWIDRepoError as ex:
        logging.error('Failed to load the HWID DB CL info: %r.', ex)
        continue
      cl_status = response.cl_status.get_or_create(cl_number)
      cl_status.status = _HWID_DB_COMMIT_STATUS_TO_PROTOBUF_HWID_CL_STATUS.get(
          commit_info.status, cl_status.STATUS_UNSPECIFIC)
      for comment in commit_info.comments:
        cl_status.comments.add(email=comment.author_email,
                               message=comment.message)
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def BatchGenerateAvlComponentName(self, request):
    response = hwid_api_messages_pb2.BatchGenerateAvlComponentNameResponse()
    for mat in request.component_name_materials:
      if mat.avl_qid == 0:
        response.component_names.append(
            f'{mat.component_class}_{mat.avl_cid}#{mat.seq_no}')
      else:
        response.component_names.append(
            f'{mat.component_class}_{mat.avl_cid}_{mat.avl_qid}#{mat.seq_no}')
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def AnalyzeHwidDbEditableSection(self, request):
    response = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse()

    live_hwid_repo = _hwid_repo_manager.GetLiveHWIDRepo()
    change_info = _GetHWIDDBChangeInfo(live_hwid_repo, request.project,
                                       request.hwid_db_editable_section)

    analyzer = contents_analyzer.ContentsAnalyzer(
        change_info.new_hwid_db_contents, None,
        change_info.curr_hwid_db_contents)

    def _RemoveHeader(hwid_db_contents):
      unused_header, lines = _SplitHWIDDBV3Sections(hwid_db_contents)
      return _NormalizeAndJoinHWIDDBEditableSectionLines(lines)

    report = analyzer.AnalyzeChange(_RemoveHeader)

    if report.precondition_errors:
      for error in report.precondition_errors:
        response.validation_result.errors.add(
            code=(response.validation_result.SCHEMA_ERROR
                  if error.code == hwid_validator.ErrorCode.SCHEMA_ERROR else
                  response.validation_result.CONTENTS_ERROR),
            message=error.message)
      return response

    # TODO(yhong): Don't add the status `duplicate` if the project is too old.
    response.analysis_report.unqualified_support_status.extend([
        v3_common.COMPONENT_STATUS.deprecated,
        v3_common.COMPONENT_STATUS.unsupported,
        v3_common.COMPONENT_STATUS.unqualified,
        v3_common.COMPONENT_STATUS.duplicate
    ])
    response.analysis_report.qualified_support_status.append(
        v3_common.COMPONENT_STATUS.supported)

    for line in report.lines:
      response_line = response.analysis_report.hwid_config_lines.add()
      if line.modification_status == line.ModificationStatus.MODIFIED:
        response_line.modification_status = response_line.MODIFIED
      elif line.modification_status == line.ModificationStatus.NEWLY_ADDED:
        response_line.modification_status = response_line.NEWLY_ADDED
      else:
        response_line.modification_status = response_line.NOT_MODIFIED
      for part in line.parts:
        if part.type == part.Type.COMPONENT_NAME:
          response_line.parts.add(component_name_field_id=part.reference_id)
        elif part.type == part.Type.COMPONENT_STATUS:
          response_line.parts.add(support_status_field_id=part.reference_id)
        else:
          response_line.parts.add(fixed_text=part.text)
    for reference_id, comp_info in report.hwid_components.items():
      response_comp_info = (
          response.analysis_report.component_infos.get_or_create(reference_id))
      response_comp_info.component_class = comp_info.comp_cls
      response_comp_info.original_name = comp_info.comp_name
      response_comp_info.original_status = comp_info.support_status
      response_comp_info.is_newly_added = comp_info.is_newly_added
      if comp_info.avl_id is not None:
        response_comp_info.avl_info.cid, response_comp_info.avl_info.qid = (
            comp_info.avl_id)
        response_comp_info.has_avl = True
      else:
        response_comp_info.has_avl = False
      response_comp_info.seq_no = comp_info.seq_no
      if comp_info.comp_name_with_correct_seq_no is not None:
        response_comp_info.component_name_with_correct_seq_no = (
            comp_info.comp_name_with_correct_seq_no)
    return response


def _GetHWIDDBChangeInfo(live_hwid_repo, project, new_hwid_db_editable_section):
  new_hwid_db_editable_section = _NormalizeAndJoinHWIDDBEditableSectionLines(
      new_hwid_db_editable_section.splitlines())
  curr_hwid_db_contents = _LoadHWIDDBV3Contents(live_hwid_repo, project)
  curr_header, unused_curr_editable_section_lines = _SplitHWIDDBV3Sections(
      curr_hwid_db_contents)
  new_hwid_config_contents = update_checksum.ReplaceChecksum(
      f'{curr_header}\n{new_hwid_db_editable_section}')
  checksum = ''
  for contents in (curr_hwid_db_contents, new_hwid_config_contents):
    checksum = hashlib.sha1((checksum + contents).encode('utf-8')).hexdigest()
  return _HWIDDBChangeInfo(checksum, curr_hwid_db_contents,
                           new_hwid_config_contents)


def _LoadHWIDDBV3Contents(live_hwid_repo, project):
  try:
    hwid_db_metadata = live_hwid_repo.GetHWIDDBMetadataByName(project)
  except ValueError:
    raise protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND,
        detail='Project is not available.') from None
  if hwid_db_metadata.version != 3:
    raise protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.FAILED_PRECONDITION,
        detail='Project must be HWID version 3.')
  try:
    return live_hwid_repo.LoadHWIDDBByName(project)
  except hwid_repo.HWIDRepoError:
    raise protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.INTERNAL,
        detail='Project is not available.') from None


def _SplitHWIDDBV3Sections(hwid_db_contents) -> Tuple[str, List[str]]:
  """Split the given HWID DB contents into the header and lines of DB body."""
  lines = hwid_db_contents.splitlines()
  split_idx_list = [i for i, l in enumerate(lines) if l.rstrip() == 'image_id:']
  if len(split_idx_list) != 1:
    raise protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.INTERNAL,
        detail='The project has an invalid HWID DB.')
  return '\n'.join(lines[:split_idx_list[0]]), lines[split_idx_list[0]:]


def _NormalizeAndJoinHWIDDBEditableSectionLines(lines):
  return '\n'.join(l.rstrip() for l in lines).rstrip()
