# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import logging
import re
import textwrap
import time
from typing import Optional, Tuple

from google.protobuf import json_format

from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.v3 import builder as v3_builder
from cros.factory.hwid.v3 import common as v3_common
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.probe_info_service.app_engine import protorpc_utils


_HWID_DB_COMMIT_STATUS_TO_PROTOBUF_HWID_CL_STATUS = {
    hwid_repo.HWIDDBCLStatus.NEW:
        hwid_api_messages_pb2.HwidDbEditableSectionChangeClInfo.PENDING,
    hwid_repo.HWIDDBCLStatus.MERGED:
        hwid_api_messages_pb2.HwidDbEditableSectionChangeClInfo.MERGED,
    hwid_repo.HWIDDBCLStatus.ABANDONED:
        hwid_api_messages_pb2.HwidDbEditableSectionChangeClInfo.ABANDONED,
}

_MAX_OPENED_HWID_DB_CL_AGE = datetime.timedelta(
    days=365 * 3)  # A rough estimation of 3 years.
_MAX_MERGE_CONFLICT_HWID_DB_CL_AGE = datetime.timedelta(
    days=365 * 3 // 4)  # A rough estimation of 3 quarters.

_AnalysisReportMsg = hwid_api_messages_pb2.HwidDbEditableSectionAnalysisReport


class HWIDStatusConversionError(Exception):
  """Indicate a failure to convert HWID component status to
  `hwid_api_messages_pb2.SupportStatus`."""


def ConvertToNameChangedComponent(name_changed_comp_info):
  """Converts an instance of `NameChangedComponentInfo` to
  hwid_api_messages_pb2.NameChangedComponent message."""
  support_status_descriptor = (
      hwid_api_messages_pb2.NameChangedComponent.SupportStatus.DESCRIPTOR)
  status_val = support_status_descriptor.values_by_name.get(
      name_changed_comp_info.status.upper())
  if status_val is None:
    raise HWIDStatusConversionError(
        f'Unknown status: {name_changed_comp_info.status!r}.')
  return hwid_api_messages_pb2.NameChangedComponent(
      cid=name_changed_comp_info.cid, qid=name_changed_comp_info.qid,
      support_status=status_val.number,
      component_name=name_changed_comp_info.comp_name,
      has_cid_qid=name_changed_comp_info.has_cid_qid,
      diff_prev=name_changed_comp_info.diff_prev and
      hwid_api_messages_pb2.DiffStatus(
          unchanged=name_changed_comp_info.diff_prev.unchanged,
          name_changed=name_changed_comp_info.diff_prev.name_changed,
          support_status_changed=name_changed_comp_info.diff_prev
          .support_status_changed,
          values_changed=name_changed_comp_info.diff_prev.values_changed,
          prev_comp_name=name_changed_comp_info.diff_prev.prev_comp_name,
          prev_support_status=name_changed_comp_info.diff_prev
          .prev_support_status))


def _ConvertValidationErrorCode(code):
  ValidationResultMessage = (
      hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult)
  if code == hwid_action.DBValidationErrorCode.SCHEMA_ERROR:
    return ValidationResultMessage.ErrorCode.SCHEMA_ERROR
  return ValidationResultMessage.ErrorCode.CONTENTS_ERROR


def _ConvertCompInfoToMsg(
    comp_info: hwid_action.DBHWIDComponentAnalysisResult
) -> _AnalysisReportMsg.ComponentInfo:
  comp_info_msg = _AnalysisReportMsg.ComponentInfo()
  comp_info_msg.component_class = comp_info.comp_cls
  comp_info_msg.original_name = comp_info.comp_name
  comp_info_msg.original_status = comp_info.support_status
  comp_info_msg.is_newly_added = comp_info.is_newly_added
  if comp_info.avl_id is not None:
    comp_info_msg.avl_info.cid, comp_info_msg.avl_info.qid = comp_info.avl_id
    comp_info_msg.has_avl = True
  else:
    comp_info_msg.has_avl = False
  comp_info_msg.seq_no = comp_info.seq_no
  if comp_info.comp_name_with_correct_seq_no is not None:
    comp_info_msg.component_name_with_correct_seq_no = (
        comp_info.comp_name_with_correct_seq_no)
  comp_info_msg.null_values = comp_info.null_values
  if comp_info.diff_prev is not None:
    diff = comp_info.diff_prev
    comp_info_msg.diff_prev.CopyFrom(
        hwid_api_messages_pb2.DiffStatus(
            unchanged=diff.unchanged,
            name_changed=diff.name_changed,
            support_status_changed=diff.support_status_changed,
            values_changed=diff.values_changed,
            prev_comp_name=diff.prev_comp_name,
            prev_support_status=diff.prev_support_status,
        ))
  return comp_info_msg


def _IsCLExpired(cl_info: hwid_repo.HWIDDBCLInfo) -> Tuple[bool, Optional[str]]:
  """Determines whether a CL is considered expired.

  Args:
    cl_info: The information of the CL to check.

  Returns:
    The expiration check result in a 2-value tuple.  The first value is
    `True` iff the CL is expired.  If the CL is considered expired,
    the second tuple value is a string message of the reason.
    If the CL is not expired, the second tuple value is `None`.
  """
  if cl_info.status == hwid_repo.HWIDDBCLStatus.NEW:
    cl_age = datetime.datetime.utcnow() - cl_info.created_time
    if cl_info.mergeable:
      if cl_age > _MAX_OPENED_HWID_DB_CL_AGE:
        return True, ('The CL is expired for not getting merged in time '
                      f'({_MAX_OPENED_HWID_DB_CL_AGE.days} days).')
    elif cl_age > _MAX_MERGE_CONFLICT_HWID_DB_CL_AGE:
      return True, 'The CL is expired because the contents are out-of-date.'
  return False, None


class SelfServiceHelper:

  def __init__(self,
               hwid_action_manager_inst: hwid_action_manager.HWIDActionManager,
               hwid_repo_manager: hwid_repo.HWIDRepoManager,
               hwid_db_data_manager: hwid_db_data.HWIDDBDataManager):
    self._hwid_action_manager = hwid_action_manager_inst
    self._hwid_repo_manager = hwid_repo_manager
    self._hwid_db_data_manager = hwid_db_data_manager

  def GetHWIDDBEditableSection(self, request):
    try:
      action = self._hwid_action_manager.GetHWIDAction(request.project)
      editable_section = action.GetDBEditableSection()
    except (KeyError, ValueError, RuntimeError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

    response = hwid_api_messages_pb2.GetHwidDbEditableSectionResponse(
        hwid_db_editable_section=editable_section)
    return response

  def ValidateHWIDDBEditableSectionChange(self, request):
    raise common_helper.ConvertExceptionToProtoRPCException(
        NotImplementedError(('Deprecated. Use AnalyzeHwidDbEditableSection '
                             'instead')))

  def CreateHWIDDBEditableSectionChangeCL(self, request):
    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    try:
      metadata = live_hwid_repo.GetHWIDDBMetadataByName(request.project)
      self._hwid_db_data_manager.UpdateProjectsByRepo(
          live_hwid_repo, [metadata], delete_missing=False)
      self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
          limit_models=[request.project])

      action = self._hwid_action_manager.GetHWIDAction(request.project)
      analysis = action.AnalyzeDraftDBEditableSection(
          request.new_hwid_db_editable_section, derive_fingerprint_only=True,
          require_hwid_db_lines=False)
    except (KeyError, ValueError, RuntimeError, hwid_repo.HWIDRepoError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

    if analysis.fingerprint != request.validation_token:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.ABORTED,
          detail='The validation token is expired.')

    commit_msg = textwrap.dedent(f"""\
        ({int(time.time())}) {request.project}: HWID Config Update

        Requested by: {request.original_requester}
        Warning: all posted comments will be sent back to the requester.

        %s

        BUG=b:{request.bug_number}
        """) % request.description

    try:
      cl_number = live_hwid_repo.CommitHWIDDB(
          request.project, analysis.new_hwid_db_contents, commit_msg,
          request.reviewer_emails, request.cc_emails, request.auto_approved)
    except hwid_repo.HWIDRepoError:
      logging.exception(
          'Caught unexpected exception while uploading a HWID CL.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
    resp = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClResponse(
        cl_number=cl_number)
    return resp

  def CreateHWIDDBFirmwareInfoUpdateCL(self, request):
    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    bundle_record = request.bundle_record
    all_commits = []
    for firmware_record in bundle_record.firmware_records:
      # Load HWID DB
      try:
        metadata = live_hwid_repo.GetHWIDDBMetadataByName(firmware_record.model)
        self._hwid_db_data_manager.UpdateProjectsByRepo(
            live_hwid_repo, [metadata], delete_missing=False)
        self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
            limit_models=[firmware_record.model])
        action = self._hwid_action_manager.GetHWIDAction(firmware_record.model)
      except (KeyError, ValueError, RuntimeError,
              hwid_repo.HWIDRepoError) as ex:
        raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

      # Derive firmware key component name
      keys_comp_name = None
      if bundle_record.firmware_signer:
        match = re.match(
            f'^{bundle_record.board}(mp|premp)keys(?:-(v[0-9]+))?$',
            bundle_record.firmware_signer.lower())
        if match is None:
          raise ValueError('Cannot derive firmware key name from signer: '
                           f'{bundle_record.firmware_signer}.')
        keys_comp_name = f'firmware_keys_{match.group(1)}'
        if match.group(2):
          keys_comp_name += f'_{match.group(2)}'

      # Add component to DB
      db_builder = v3_builder.DatabaseBuilder(database=action.GetDBV3())
      changed = False
      for field, value in firmware_record.ListFields():
        if field.message_type is None:
          continue
        value = json_format.MessageToDict(value,
                                          preserving_proto_field_name=True)

        if field.message_type.name == 'FirmwareInfo':
          comp_name = v3_builder.DetermineComponentName(field.name, value)
        elif field.message_type.name == 'FirmwareKeys':
          comp_name = keys_comp_name
        else:
          continue

        if comp_name in db_builder.database.GetComponents(field.name):
          logging.info('Skip existed component: %s', comp_name)
        else:
          db_builder.AddComponent(field.name, value, comp_name)
          changed = True

      if not changed:
        logging.info('No component is added to DB: %s', firmware_record.model)
        continue

      # Create commit
      editable_section = action.RemoveHeader(
          db_builder.database.DumpDataWithoutChecksum(internal=True))
      analysis = action.AnalyzeDraftDBEditableSection(
          editable_section, derive_fingerprint_only=True,
          require_hwid_db_lines=False)
      commit_msg = textwrap.dedent(f"""\
          ({int(time.time())}) {db_builder.database.project}: HWID Firmware \
Info Update

          Requested by: {request.original_requester}
          Warning: all posted comments will be sent back to the requester.

          %s
          """) % request.description
      all_commits.append((firmware_record.model, analysis, commit_msg))

    # Create CLs and rollback on exception
    resp = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClResponse()
    try:
      for model_name, analysis, commit_msg in all_commits:
        try:
          cl_number = live_hwid_repo.CommitHWIDDB(
              name=model_name, hwid_db_contents=analysis.new_hwid_db_contents,
              commit_msg=commit_msg, reviewers=[],
              cc_list=[request.original_requester], auto_approved=True)
        except hwid_repo.HWIDRepoError:
          logging.exception(
              'Caught unexpected exception while uploading a HWID CL.')
          raise protorpc_utils.ProtoRPCException(
              protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
        resp.commits[model_name].cl_number = cl_number
        resp.commits[model_name].new_hwid_db_contents = (
            analysis.new_hwid_db_contents)
    except Exception as ex:
      # Abandon all committed CLs on exception
      logging.exception('Rollback to abandon commited CLs.')
      for model_name, commit in resp.commits.items():
        try:
          logging.info('Abdandon CL: %d', commit.cl_number)
          self._hwid_repo_manager.AbandonCL(commit.cl_number)
        except git_util.GitUtilException as git_ex:
          logging.error('Failed to abandon CL: %d, error: %r.',
                        commit.cl_number, git_ex)
      raise ex

    return resp

  def _GetActiveHWIDDBEditableSectionChangeCLInfo(self, cl_number):
    try:
      cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(cl_number)
    except hwid_repo.HWIDRepoError as ex:
      logging.error('Failed to load the HWID DB CL info: %r.', ex)
      return None

    # TODO(yhong): Consider triggering legacy CL deprecation routine by
    # cronjobs instead.
    is_cl_expired, cl_expiration_reason = _IsCLExpired(cl_info)
    if not is_cl_expired:
      return cl_info

    try:
      self._hwid_repo_manager.AbandonCL(cl_number, reason=cl_expiration_reason)
    except git_util.GitUtilException as ex:
      logging.warning(
          'Caught exception while abandoning the expired HWID DB CL: %r.', ex)
      return cl_info

    try:
      cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(cl_number)
    except hwid_repo.HWIDRepoError as ex:
      logging.error(
          'Failed to refetch CL info after the abandon operation, '
          'caught exception: %r.', ex)
      return None
    if cl_info.status != hwid_repo.HWIDDBCLStatus.ABANDONED:
      logging.error('CL abandon seems failed.  The status flag in the '
                    'refetched CL info are not changed.')
      return None
    return cl_info

  def BatchGetHWIDDBEditableSectionChangeCLInfo(self, request):
    response = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))
    for cl_number in request.cl_numbers:
      cl_info = self._GetActiveHWIDDBEditableSectionChangeCLInfo(cl_number)
      if cl_info is None:
        continue

      cl_status = response.cl_status.get_or_create(cl_number)
      cl_status.status = _HWID_DB_COMMIT_STATUS_TO_PROTOBUF_HWID_CL_STATUS.get(
          cl_info.status, cl_status.STATUS_UNSPECIFIC)
      for comment in cl_info.messages:
        cl_status.comments.add(email=comment.author_email,
                               message=comment.message)
    return response

  def AnalyzeHWIDDBEditableSection(self, request):
    response = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse()
    require_hwid_db_lines = request.require_hwid_db_lines

    try:
      action = self._hwid_action_manager.GetHWIDAction(request.project)
      report = action.AnalyzeDraftDBEditableSection(
          request.hwid_db_editable_section, False, require_hwid_db_lines)
    except (KeyError, ValueError, RuntimeError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None
    response.validation_token = report.fingerprint

    if report.precondition_errors:
      for error in report.precondition_errors:
        response.validation_result.errors.add(
            code=_ConvertValidationErrorCode(error.code), message=error.message)

    if report.validation_errors:
      for error in report.validation_errors:
        response.validation_result.errors.add(
            code=_ConvertValidationErrorCode(error.code), message=error.message)

    if response.validation_result.errors:
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

    if require_hwid_db_lines:
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
      response.analysis_report.component_infos[reference_id].CopyFrom(
          _ConvertCompInfoToMsg(comp_info))
    return response

  def BatchGenerateAVLComponentName(self, request):
    response = hwid_api_messages_pb2.BatchGenerateAvlComponentNameResponse()
    np_adapter = name_pattern_adapter.NamePatternAdapter()
    nps = {}
    for mat in request.component_name_materials:
      try:
        np = nps[mat.component_class]
      except KeyError:
        np = nps[mat.component_class] = np_adapter.GetNamePattern(
            mat.component_class)

      response.component_names.append(
          np.GenerateAVLName(mat.avl_cid,
                             qid=mat.avl_qid if mat.avl_qid else None,
                             seq_no=mat.seq_no))
    return response

  def GetHWIDBundleResourceInfo(self, request):
    try:
      metadata = self._hwid_repo_manager.GetHWIDDBMetadata(request.project)
      content = self._hwid_repo_manager.GetFileContent(metadata.path)
      self._hwid_db_data_manager.UpdateProjectContent(request.project, content)
      self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
          limit_models=[request.project])

      action = self._hwid_action_manager.GetHWIDAction(request.project)
      resource_info = action.GetHWIDBundleResourceInfo()
    except (KeyError, ValueError, RuntimeError, hwid_repo.HWIDRepoError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

    response = hwid_api_messages_pb2.GetHwidBundleResourceInfoResponse(
        bundle_creation_token=resource_info.fingerprint)

    for reference_id, comp_info in resource_info.hwid_components.items():
      response.resource_info.db_info.component_infos[reference_id].CopyFrom(
          _ConvertCompInfoToMsg(comp_info))
    return response

  def CreateHWIDBundle(self, request):
    try:
      action = self._hwid_action_manager.GetHWIDAction(request.project)
      resource_info = action.GetHWIDBundleResourceInfo(fingerprint_only=True)
    except (KeyError, ValueError, RuntimeError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None
    if resource_info.fingerprint != request.bundle_creation_token:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.ABORTED,
          'Invalid resource info token.')

    try:
      # TODO(b/209362238): pass request.bundle_resource into BundleHWIDDB to
      # validate if the AVL link still holds.
      bundle_info = action.BundleHWIDDB()
    except (KeyError, ValueError, RuntimeError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

    response = hwid_api_messages_pb2.CreateHwidBundleResponse(
        hwid_bundle=hwid_api_messages_pb2.HwidBundle(
            contents=bundle_info.bundle_contents,
            name_ext=bundle_info.bundle_file_ext))
    return response
