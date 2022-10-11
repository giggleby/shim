# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import io
import logging
import re
import textwrap
import time
from typing import Mapping, MutableMapping, NamedTuple, Optional, Sequence, Tuple
import uuid

from google.protobuf import descriptor
from google.protobuf import json_format

from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers import v3_self_service_helper as v3_action_helper
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import hwid_v3_action
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import builder as v3_builder
from cros.factory.hwid.v3 import change_unit_utils
from cros.factory.hwid.v3 import common as v3_common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.hwid.v3 import yaml_wrapper as yaml
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
_MAX_MERGE_CONFLICT_HWID_DB_CL_AGE = datetime.timedelta(days=7)

_AnalysisReportMsg = hwid_api_messages_pb2.HwidDbEditableSectionAnalysisReport
_PROBE_VALUE_ALIGNMENT_STATUS = {
    hwid_action.DBHWIDPVAlignmentStatus.NO_PROBE_INFO:
        hwid_api_messages_pb2.ProbeValueAlignmentStatus.Case.NO_PROBE_INFO,
    hwid_action.DBHWIDPVAlignmentStatus.ALIGNED:
        hwid_api_messages_pb2.ProbeValueAlignmentStatus.Case.ALIGNED,
    hwid_action.DBHWIDPVAlignmentStatus.NOT_ALIGNED:
        hwid_api_messages_pb2.ProbeValueAlignmentStatus.Case.NOT_ALIGNED,
}

_APPROVAL_CASE = {
    hwid_api_messages_pb2.ClAction.ApprovalCase.APPROVED: (
        git_util.ApprovalCase.APPROVED),
    hwid_api_messages_pb2.ClAction.ApprovalCase.REJECTED: (
        git_util.ApprovalCase.REJECTED),
    hwid_api_messages_pb2.ClAction.ApprovalCase.NEED_MANUAL_REVIEW: (
        git_util.ApprovalCase.NEED_MANUAL_REVIEW),
}

_HWID_SECTION_CHANGE_STATUS = {
    hwid_action.DBHWIDTouchCase.TOUCHED: (
        _AnalysisReportMsg.HwidSectionChange.ChangeStatus.TOUCHED),
    hwid_action.DBHWIDTouchCase.UNTOUCHED: (
        _AnalysisReportMsg.HwidSectionChange.ChangeStatus.UNTOUCHED),
}

_SessionCache = hwid_action.SessionCache
_ChangeUnitMsg = hwid_api_messages_pb2.ChangeUnit
_CLActionMsg = hwid_api_messages_pb2.ClAction
_CHANGE_UNIT_APPROVAL_STATUS_MAP = {
    hwid_api_messages_pb2.ClAction.ApprovalCase.APPROVED: (
        change_unit_utils.ApprovalStatus.AUTO_APPROVED),
    hwid_api_messages_pb2.ClAction.ApprovalCase.REJECTED: (
        change_unit_utils.ApprovalStatus.REJECTED),
    hwid_api_messages_pb2.ClAction.ApprovalCase.NEED_MANUAL_REVIEW: (
        change_unit_utils.ApprovalStatus.MANUAL_REVIEW_REQUIRED),
    hwid_api_messages_pb2.ClAction.ApprovalCase.DONT_CARE: (
        change_unit_utils.ApprovalStatus.DONT_CARE),
}
_SplitChangeUnitException = change_unit_utils.SplitChangeUnitException
_ApplyChangeUnitException = change_unit_utils.ApplyChangeUnitException


def _ConvertTouchedSectionToMsg(
    touched_sections: Optional[hwid_action.DBHWIDTouchSections]
) -> _AnalysisReportMsg.HwidSectionChange:
  if not touched_sections:
    return _AnalysisReportMsg.HwidSectionChange()
  msg = _AnalysisReportMsg.HwidSectionChange()
  msg.image_id_change_status = _HWID_SECTION_CHANGE_STATUS[
      touched_sections.image_id_change_status]
  msg.pattern_change_status = _HWID_SECTION_CHANGE_STATUS[
      touched_sections.pattern_change_status]
  msg.components_change_status = _HWID_SECTION_CHANGE_STATUS[
      touched_sections.components_change_status]
  msg.rules_change_status = _HWID_SECTION_CHANGE_STATUS[
      touched_sections.rules_change_status]
  msg.framework_version_change_status = _HWID_SECTION_CHANGE_STATUS[
      touched_sections.framework_version_change_status]
  for k, v in touched_sections.encoded_fields_change_status.items():
    msg.encoded_fields_change_status[k] = _HWID_SECTION_CHANGE_STATUS[v]
  return msg


def _NormalizeProjectString(string: str) -> Optional[str]:
  """Normalizes a string to account for things like case."""
  return string.strip().upper() if string else None


def _SetupKnownSupportStatusCategories(report: _AnalysisReportMsg):
  # TODO(yhong): Don't add the status `duplicate` if the project is too old.
  report.unqualified_support_status.extend([
      v3_common.COMPONENT_STATUS.deprecated,
      v3_common.COMPONENT_STATUS.unsupported,
      v3_common.COMPONENT_STATUS.unqualified,
      v3_common.COMPONENT_STATUS.duplicate
  ])
  report.qualified_support_status.append(v3_common.COMPONENT_STATUS.supported)


class HWIDStatusConversionError(Exception):
  """Indicate a failure to convert HWID component status to
  `hwid_api_messages_pb2.SupportStatus`."""


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
  comp_info_msg.original_name = yaml.safe_dump(
      comp_info.comp_name).partition('\n')[0]
  comp_info_msg.original_status = comp_info.support_status
  comp_info_msg.is_newly_added = comp_info.is_newly_added
  if comp_info.comp_name_info is not None:
    comp_info_msg.avl_info.cid = comp_info.comp_name_info.cid
    comp_info_msg.avl_info.qid = comp_info.comp_name_info.qid or 0
    comp_info_msg.avl_info.is_subcomp = comp_info.comp_name_info.is_subcomp
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
            unchanged=diff.unchanged, name_changed=diff.name_changed,
            support_status_changed=diff.support_status_changed,
            values_changed=diff.values_changed,
            prev_comp_name=diff.prev_comp_name,
            prev_support_status=diff.prev_support_status,
            probe_value_alignment_status_changed=(
                diff.probe_value_alignment_status_changed),
            prev_probe_value_alignment_status=_PROBE_VALUE_ALIGNMENT_STATUS[
                diff.prev_probe_value_alignment_status]))
  comp_info_msg.probe_value_alignment_status = _PROBE_VALUE_ALIGNMENT_STATUS[
      comp_info.probe_value_alignment_status]
  return comp_info_msg


def _CheckIfHWIDDBCLShouldBeAbandoned(
    cl_info: hwid_repo.HWIDDBCLInfo) -> Tuple[bool, Optional[str]]:
  """Determines whether a HWID DB CL should be abandoned.

  Args:
    cl_info: The information of the CL to check.

  Returns:
    The expiration check result in a 2-value tuple.  The first value is
    `True` iff the CL is expired.  If the CL is considered expired,
    the second tuple value is a string message of the reason.
    If the CL is not expired, the second tuple value is `None`.
  """
  if cl_info.status == hwid_repo.HWIDDBCLStatus.NEW:
    if cl_info.review_status == hwid_repo.HWIDDBCLReviewStatus.REJECTED:
      return True, 'The CL is rejected by the reviewer.'
    cl_age = datetime.datetime.utcnow() - cl_info.created_time
    if cl_info.mergeable:
      if cl_age > _MAX_OPENED_HWID_DB_CL_AGE:
        return True, ('The CL is expired for not getting merged in time '
                      f'({_MAX_OPENED_HWID_DB_CL_AGE.days} days).')
    elif cl_age > _MAX_MERGE_CONFLICT_HWID_DB_CL_AGE:
      return True, 'The CL is expired because the contents are out-of-date.'
  return False, None


def _ConvertChangeUnitToMsg(
    change_unit: change_unit_utils.ChangeUnit) -> _ChangeUnitMsg:
  msg = _ChangeUnitMsg()
  if isinstance(change_unit, change_unit_utils.CompChange):
    msg.comp_change.CopyFrom(_ConvertCompInfoToMsg(change_unit.comp_analysis))
  elif isinstance(change_unit, change_unit_utils.AddEncodingCombination):
    msg.add_encoding_combination.comp_cls = change_unit.comp_cls
    msg.add_encoding_combination.comp_info.extend(
        _ConvertCompInfoToMsg(comp_analysis)
        for comp_analysis in change_unit.comp_analyses)
  elif isinstance(change_unit,
                  change_unit_utils.NewImageIdToExistingEncodingPattern):
    msg.new_image_id.image_names.append(change_unit.image_name)
  elif isinstance(change_unit,
                  change_unit_utils.AssignBitMappingToEncodingPattern):
    msg.new_image_id.image_names.extend(
        desc.name for desc in change_unit.image_descs)
    msg.new_image_id.with_new_encoding_pattern = True
  elif isinstance(change_unit, change_unit_utils.ReplaceRules):
    msg.replace_rules.CopyFrom(_ChangeUnitMsg.ReplaceRules())
  else:
    raise ValueError('Invalid change unit {change_unit!r}.')
  return msg


class _ApprovalInfo(NamedTuple):
  change_unit_repr: str
  reviewers: Sequence[str]
  ccs: Sequence[str]
  reasons: Sequence[str]


def _FormatApprovalStatusReasons(approval_info: _ApprovalInfo) -> str:
  outbuf = io.StringIO()
  outbuf.write(f'{approval_info.change_unit_repr}:\n')
  for reason in approval_info.reasons:
    outbuf.write(f'  - {reason}\n')
  return outbuf.getvalue()


def _CollectApprovalInfos(
    change_unit_manager: change_unit_utils.ChangeUnitManager,
    approval_status: Mapping[str, _CLActionMsg]) -> Mapping[str, _ApprovalInfo]:
  approval_info_per_identity: MutableMapping[str, _ApprovalInfo] = {}
  change_units = change_unit_manager.GetChangeUnits()
  for identity, cu_action in approval_status.items():
    approval_info_per_identity[identity] = _ApprovalInfo(
        repr(change_units[identity]), cu_action.reviewers, cu_action.ccs,
        cu_action.reasons)
  return approval_info_per_identity


def _SplitIntoDBSnapshots(
    change_unit_manager: change_unit_utils.ChangeUnitManager,
    approval_status: Mapping[str, _CLActionMsg]
) -> change_unit_utils.ChangeSplitResult:
  try:
    change_unit_manager.SetApprovalStatus({
        identity: _CHANGE_UNIT_APPROVAL_STATUS_MAP[cu_action.approval_case]
        for identity, cu_action in approval_status.items()
    })
  except KeyError as ex:
    raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

  try:
    return change_unit_manager.SplitChange()
  except (_SplitChangeUnitException, _ApplyChangeUnitException) as ex:
    raise common_helper.ConvertExceptionToProtoRPCException(ex) from None


class SelfServiceHelper:

  def __init__(self,
               hwid_action_manager_inst: hwid_action_manager.HWIDActionManager,
               hwid_repo_manager: hwid_repo.HWIDRepoManager,
               hwid_db_data_manager: hwid_db_data.HWIDDBDataManager,
               avl_converter_manager: converter_utils.ConverterManager,
               session_cache_adapter: memcache_adapter.MemcacheAdapter):
    self._hwid_action_manager = hwid_action_manager_inst
    self._hwid_repo_manager = hwid_repo_manager
    self._hwid_db_data_manager = hwid_db_data_manager
    self._avl_converter_manager = avl_converter_manager
    self._session_cache_adapter = session_cache_adapter

  def GetHWIDDBEditableSection(self, request):
    project = _NormalizeProjectString(request.project)
    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
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

  def _UpdateHWIDDBDataIfNeed(self, live_hwid_repo: hwid_repo.HWIDRepo,
                              project: str):
    live_raw_db = live_hwid_repo.LoadHWIDDBByName(project)
    curr_preproc_data = self._hwid_action_manager.GetHWIDPreprocDataFromCache(
        project)
    if (curr_preproc_data and
        getattr(curr_preproc_data, 'raw_database', None) == live_raw_db):
      return
    metadata = live_hwid_repo.GetHWIDDBMetadataByName(project)
    self._hwid_db_data_manager.UpdateProjectsByRepo(live_hwid_repo, [metadata],
                                                    delete_missing=False)
    self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
        limit_models=[project])

  def CreateHWIDDBEditableSectionChangeCL(self, request):
    project = _NormalizeProjectString(request.project)
    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    cache = self._session_cache_adapter.Get(request.validation_token)
    if cache is None:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.ABORTED,
          detail='The validation token is expired.')
    try:
      self._UpdateHWIDDBDataIfNeed(live_hwid_repo, project)

      action = self._hwid_action_manager.GetHWIDAction(project)
      analysis = action.AnalyzeDraftDBEditableSection(
          cache.new_hwid_db_editable_section, derive_fingerprint_only=False,
          require_hwid_db_lines=False, internal=True,
          avl_converter_manager=self._avl_converter_manager,
          avl_resource=request.db_external_resource)
    except (KeyError, ValueError, RuntimeError, hwid_repo.HWIDRepoError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

    if analysis.fingerprint != request.validation_token:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.ABORTED,
          detail='The validation token is expired.')

    commit_msg = [
        textwrap.dedent(f"""\
            ({int(time.time())}) {project}: HWID Config Update

            Requested by: {request.original_requester}
            Warning: all posted comments will be sent back to the requester.

            %s
            """) % request.description
    ]

    if request.dlm_validation_exemption:
      commit_msg.append(
          f'DLM-VALIDATION-EXEMPTION={request.dlm_validation_exemption}')

    commit_msg.append(f'BUG=b:{request.bug_number}')
    commit_msg = '\n'.join(commit_msg)

    try:
      cl_number = live_hwid_repo.CommitHWIDDB(
          name=project, hwid_db_contents=analysis.new_hwid_db_contents_external,
          commit_msg=commit_msg, reviewers=request.reviewer_emails,
          cc_list=request.cc_emails, bot_commit=request.auto_approved,
          commit_queue=request.auto_approved,
          hwid_db_contents_internal=analysis.new_hwid_db_contents_internal)
    except hwid_repo.HWIDRepoError:
      logging.exception(
          'Caught an unexpected exception while uploading a HWID CL.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
    resp = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClResponse(
        cl_number=cl_number)
    for reference_id, comp_info in analysis.hwid_components.items():
      resp.analysis_report.component_infos[reference_id].CopyFrom(
          _ConvertCompInfoToMsg(comp_info))

    resp.analysis_report.touched_sections.CopyFrom(
        _ConvertTouchedSectionToMsg(analysis.touched_sections))

    _SetupKnownSupportStatusCategories(resp.analysis_report)

    return resp

  def CreateHWIDDBFirmwareInfoUpdateCL(self, request):
    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    bundle_record = request.bundle_record
    request_uuid = str(uuid.uuid4())
    all_commits = []
    for firmware_record in bundle_record.firmware_records:
      model = _NormalizeProjectString(firmware_record.model)
      # Load HWID DB
      try:
        self._UpdateHWIDDBDataIfNeed(live_hwid_repo, model)
        action = self._hwid_action_manager.GetHWIDAction(model)
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
          raise common_helper.ConvertExceptionToProtoRPCException(
              ValueError('Cannot derive firmware key name from signer: '
                         f'{bundle_record.firmware_signer}.'))
        keys_comp_name = f'firmware_keys_{match.group(1)}'
        if match.group(2):
          keys_comp_name += f'_{match.group(2)}'

      changed = False
      # Add component to DB
      with v3_builder.DatabaseBuilder.FromExistingDB(
          db=action.GetDBV3()) as db_builder:
        for field, values in firmware_record.ListFields():
          if field.message_type is None:
            continue

          # Currently only ro_fp_firmware is repeated. Specially handle this
          # case.
          if field.label != descriptor.FieldDescriptor.LABEL_REPEATED:
            values = [values]

          for value in values:
            value = json_format.MessageToDict(value,
                                              preserving_proto_field_name=True)
            if field.name == v3_common.FirmwareComps.FIRMWARE_KEYS:
              comp_name = keys_comp_name
            elif v3_common.FirmwareComps.has_value(field.name):
              comp_name = v3_builder.DetermineComponentName(field.name, value)
            else:
              continue

            if comp_name not in db_builder.GetComponents(field.name):
              db_builder.AddComponentCheck(field.name, value, comp_name,
                                           supported=firmware_record.supported)

            comp = db_builder.GetComponents(field.name)[comp_name]
            db_builder.GetComponents(field.name)[comp_name] = comp.Replace(
                bundle_uuids=list(comp.bundle_uuids) + [request_uuid])
            changed = True

      if not changed:
        logging.info('No component is added/modified to DB: %s', model)
        continue

      db = db_builder.Build()

      # Create commit
      hwid_db_contents_internal = action.PatchHeader(
          db.DumpDataWithoutChecksum(internal=True,
                                     suppress_support_status=False))
      hwid_db_contents_external = action.PatchHeader(
          db.DumpDataWithoutChecksum(internal=False,
                                     suppress_support_status=False))
      commit_msg = textwrap.dedent(f"""\
          ({int(time.time())}) {db.project}: HWID Firmware Info Update

          Requested by: {request.original_requester}
          Warning: all posted comments will be sent back to the requester.

          %s

          BUG=b:{request.bug_number}""") % request.description
      all_commits.append((model, hwid_db_contents_external,
                          hwid_db_contents_internal, commit_msg))

    # Create CLs and rollback on exception
    resp = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClResponse()
    try:
      for model_name, external_db, internal_db, commit_msg in all_commits:
        try:
          cl_number = live_hwid_repo.CommitHWIDDB(
              name=model_name, hwid_db_contents=external_db,
              commit_msg=commit_msg, reviewers=request.reviewer_emails,
              cc_list=request.cc_emails, bot_commit=request.auto_approved,
              commit_queue=request.auto_approved,
              hwid_db_contents_internal=internal_db)
        except hwid_repo.HWIDRepoError:
          logging.exception(
              'Caught an unexpected exception while uploading a HWID CL.')
          raise protorpc_utils.ProtoRPCException(
              protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
        resp.commits[model_name].cl_number = cl_number
        resp.commits[model_name].new_hwid_db_contents = (
            v3_action_helper.HWIDV3SelfServiceActionHelper.RemoveHeader(
                external_db))
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

  def _PutCLChainIntoCQ(self, cl_info: hwid_repo.HWIDDBCLInfo):
    if cl_info.review_status != hwid_repo.HWIDDBCLReviewStatus.APPROVED:
      return
    put_cq = []
    if not cl_info.commit_queue:
      put_cq.append(cl_info.cl_number)

    # Collect parent CLs which have Bot-Commit+1 votes.
    for cl_number in cl_info.parent_cl_numbers:
      try:
        parent_cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(cl_number)
        if not parent_cl_info.bot_commit:
          logging.error('Some parent CL does not have Bot-Commit+1: %s',
                        cl_number)
          return
        if not parent_cl_info.commit_queue:
          put_cq.append(cl_number)
      except hwid_repo.HWIDRepoError as ex:
        logging.error('Failed to load the HWID DB CL info: %r.', ex)
        return

    parent_cl_cq_reasons = [f'CL:*{cl_info.cl_number} has been approved.']
    for cl_number in put_cq:
      try:
        git_util.ReviewCL(
            hwid_repo.INTERNAL_REPO_URL, git_util.GetGerritAuthCookie(),
            cl_number=cl_number, reasons=[]
            if cl_number == cl_info.cl_number else parent_cl_cq_reasons,
            approval_case=git_util.ApprovalCase.COMMIT_QUEUE)
      except git_util.GitUtilException as ex:
        raise protorpc_utils.ProtoRPCException(
            protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from ex

  def _GetHWIDDBCLInfo(self, cl_number):
    try:
      cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(cl_number)
    except hwid_repo.HWIDRepoError as ex:
      logging.error('Failed to load the HWID DB CL info: %r.', ex)
      return None

    is_cl_expired, cl_expiration_reason = False, None

    # Auto rebase metadata when bot commit merge conflict.
    merge_conflict = (
        cl_info.status == hwid_repo.HWIDDBCLStatus.NEW and
        not cl_info.mergeable and cl_info.bot_commit)

    if merge_conflict:
      logging.info('CL %d merge conflict, perform auto rebase.', cl_number)
      try:
        self._hwid_repo_manager.RebaseCLMetadata(cl_info)
      except (git_util.GitUtilException, hwid_repo.HWIDRepoError,
              ValueError) as ex:
        logging.warning(
            'Caught an exception during resolving merge conflict: %s', ex)
        is_cl_expired, cl_expiration_reason = (
            True, 'Unable to resolve merge conflict. CL rejected.')
    else:
      # TODO(yhong): Consider triggering legacy CL deprecation routine by
      # cronjobs instead.
      is_cl_expired, cl_expiration_reason = _CheckIfHWIDDBCLShouldBeAbandoned(
          cl_info)

    if is_cl_expired:
      try:
        self._hwid_repo_manager.AbandonCL(cl_number,
                                          reason=cl_expiration_reason)
      except git_util.GitUtilException as ex:
        logging.warning(
            'Caught an exception while abandoning the expired HWID DB CL: %r.',
            ex)
        return cl_info

    if not is_cl_expired and not merge_conflict:
      self._PutCLChainIntoCQ(cl_info)
      return cl_info

    try:
      cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(cl_number)
    except hwid_repo.HWIDRepoError as ex:
      logging.error(
          'Failed to refetch CL info after the abandon/rebase operation, '
          'caught exception: %r.', ex)
      return None
    if is_cl_expired and cl_info.status != hwid_repo.HWIDDBCLStatus.ABANDONED:
      logging.error('CL abandon seems failed.  The status flag in the '
                    'refetched CL info are not changed.')
      return None
    return cl_info

  def BatchGetHWIDDBEditableSectionChangeCLInfo(self, request):
    response = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))
    for cl_number in request.cl_numbers:
      cl_info = self._GetHWIDDBCLInfo(cl_number)
      if cl_info is None:
        continue

      cl_status = response.cl_status.get_or_create(cl_number)
      cl_status.status = _HWID_DB_COMMIT_STATUS_TO_PROTOBUF_HWID_CL_STATUS.get(
          cl_info.status, cl_status.STATUS_UNSPECIFIC)
      for comment_thread in cl_info.comment_threads:
        comment_thread_msg = cl_status.comment_threads.add(
            file_path=comment_thread.path or '',
            context=comment_thread.context or '')
        for comment in comment_thread.comments:
          kwargs = {
              'email': comment.email,
              'message': comment.message
          }
          cl_status.comments.add(**kwargs)
          comment_thread_msg.comments.add(**kwargs)

    return response

  def AnalyzeHWIDDBEditableSection(self, request):
    project = _NormalizeProjectString(request.project)
    response = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse()
    require_hwid_db_lines = request.require_hwid_db_lines

    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
      report = action.AnalyzeDraftDBEditableSection(
          request.hwid_db_editable_section, False, require_hwid_db_lines)
    except (KeyError, ValueError, RuntimeError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None
    response.validation_token = report.fingerprint
    self._session_cache_adapter.Put(
        report.fingerprint,
        _SessionCache(project, request.hwid_db_editable_section),
        expiry=hwid_action.SESSION_TIMEOUT)
    response.analysis_report.noop_for_external_db = (
        report.noop_for_external_db)

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

    _SetupKnownSupportStatusCategories(response.analysis_report)

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

    response.analysis_report.touched_sections.CopyFrom(
        _ConvertTouchedSectionToMsg(report.touched_sections))
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

      if mat.is_subcomp:
        name_info = name_pattern_adapter.NameInfo.from_subcomp(mat.avl_cid)
      else:
        name_info = name_pattern_adapter.NameInfo.from_comp(
            mat.avl_cid, qid=mat.avl_qid)
      response.component_names.append(
          np.GenerateAVLName(name_info, seq=str(mat.seq_no)))
    return response

  def GetHWIDBundleResourceInfo(self, request):
    project = _NormalizeProjectString(request.project)
    try:
      metadata = self._hwid_repo_manager.GetHWIDDBMetadataByProject(project)
      repo_file_contents = self._hwid_repo_manager.GetRepoFileContents(
          [metadata.path,
           hwid_repo.HWIDRepo.InternalDBPath(metadata.path)])
      commit_id = repo_file_contents.commit_id
      content, content_internal = repo_file_contents.file_contents
      self._hwid_db_data_manager.UpdateProjectContent(
          metadata, project, content, content_internal, commit_id)
      self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
          limit_models=[project])

      action = self._hwid_action_manager.GetHWIDAction(project)
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
    project = _NormalizeProjectString(request.project)
    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
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

  def CreateHWIDDBInitCL(self, request):
    project = _NormalizeProjectString(request.project)
    board = _NormalizeProjectString(request.board)
    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    if not request.bug_number:
      raise common_helper.ConvertExceptionToProtoRPCException(
          ValueError('Bug number is required.'))
    try:
      live_hwid_repo.GetHWIDDBMetadataByName(project)
    except ValueError:
      pass
    else:
      raise common_helper.ConvertExceptionToProtoRPCException(
          ValueError(f'Project: {project} already exists.'))

    init_db = v3_builder.DatabaseBuilder.FromEmpty(
        project=project, image_name=request.phase).Build()
    db_content = init_db.DumpDataWithoutChecksum(internal=True)
    checksum_updater = v3_builder.ChecksumUpdater()
    db_content = checksum_updater.ReplaceChecksum(db_content)

    expected_db_content = checksum_updater.ReplaceChecksum(db_content)

    if expected_db_content != db_content:
      logging.error('Checksummed text is not stable.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None

    action_helper_cls = v3_action_helper.HWIDV3SelfServiceActionHelper
    editable_section = action_helper_cls.RemoveHeader(db_content)

    commit_msg = textwrap.dedent(f"""\
        ({int(time.time())}) {project}: Initialize HWID Config

        Requested by: {request.original_requester}
        Warning: all posted comments will be sent back to the requester.

        BUG=b:{request.bug_number}
        """)
    new_metadata = hwid_repo.HWIDDBMetadata(project, board, 3, f'v3/{project}')
    try:
      cl_number = live_hwid_repo.CommitHWIDDB(
          name=project, hwid_db_contents=db_content, commit_msg=commit_msg,
          reviewers=request.reviewer_emails, cc_list=request.cc_emails,
          bot_commit=request.auto_approved, commit_queue=request.auto_approved,
          update_metadata=new_metadata)
    except hwid_repo.HWIDRepoError:
      logging.exception(
          'Caught an unexpected exception while uploading a HWID CL.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
    resp = hwid_api_messages_pb2.CreateHwidDbInitClResponse()
    resp.commit.cl_number = cl_number
    resp.commit.new_hwid_db_contents = editable_section
    return resp

  def SetChangeCLBotApprovalStatus(self, request):
    for cl_number, cl_action in request.cl_actions.items():
      if cl_action.approval_case not in _APPROVAL_CASE:
        logging.error('Approval case unspecified.')
        raise protorpc_utils.ProtoRPCException(
            protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT) from None
      approval_case = _APPROVAL_CASE[cl_action.approval_case]
      try:
        git_util.ReviewCL(hwid_repo.INTERNAL_REPO_URL,
                          git_util.GetGerritAuthCookie(), cl_number=cl_number,
                          reasons=cl_action.reasons,
                          approval_case=approval_case,
                          reviewers=cl_action.reviewers, ccs=cl_action.ccs)
      except git_util.GitUtilException as ex:
        raise protorpc_utils.ProtoRPCException(
            protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from ex
    return hwid_api_messages_pb2.SetChangeClBotApprovalStatusResponse()

  def SetFirmwareInfoSupportStatus(self, request):
    project = _NormalizeProjectString(request.project)
    live_hwid_repo, action = self._GetRepoAndAction(project)
    resp = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusResponse()

    firmware_comps = action.GetComponents(
        with_classes=list(v3_common.FirmwareComps))

    def _GetBundleUUIDsByVersionString(ro_main_firmware_comps):
      # TODO(wyuang): currently it is possible to create multiple UUIDs for
      # the same component. Need to investigate how to avoid duplicated
      # firmware components.
      bundle_uuids = set()
      pattern = re.compile(r'(?:google_[a-z0-9]+\.)?(\d+\.\d+\.\d+)',
                           flags=re.I)
      match = pattern.fullmatch(request.version_string)
      if not match:
        return bundle_uuids
      ro_version = match.group(1)
      for comp_info in ro_main_firmware_comps.values():
        if not comp_info.bundle_uuids:
          continue
        match = pattern.fullmatch(comp_info.values.get('version', ''))
        if match and match.group(1) == ro_version:
          bundle_uuids.update(comp_info.bundle_uuids)
      return bundle_uuids

    bundle_uuids = _GetBundleUUIDsByVersionString(
        firmware_comps.get(v3_common.FirmwareComps.RO_MAIN_FIRMWARE, {}))
    db = action.GetDBV3()
    changed = False
    for comp_cls, comps in firmware_comps.items():
      for comp_name, comp_info in comps.items():
        if comp_info.status in (v3_common.COMPONENT_STATUS.deprecated,
                                v3_common.COMPONENT_STATUS.supported):
          continue
        if bundle_uuids.intersection(comp_info.bundle_uuids):
          db.SetComponentStatus(comp_cls, comp_name,
                                v3_common.COMPONENT_STATUS.supported)
          changed = True

    if not changed:
      logging.info('No component is added/modified to DB: %s', project)
      return resp

    # Create commit
    internal_db = action.PatchHeader(
        db.DumpDataWithoutChecksum(internal=True,
                                   suppress_support_status=False))
    external_db = action.PatchHeader(
        db.DumpDataWithoutChecksum(internal=False,
                                   suppress_support_status=False))

    commit_msg = textwrap.dedent(f"""\
        ({int(time.time())}) {project}: HWID Firmware Support Status Update

        Requested by: {request.original_requester}
        Warning: all posted comments will be sent back to the requester.

        %s

        BUG=b:{request.bug_number}""") % request.description

    try:
      cl_number = live_hwid_repo.CommitHWIDDB(
          name=project, hwid_db_contents=external_db, commit_msg=commit_msg,
          reviewers=request.reviewer_emails, cc_list=request.cc_emails,
          bot_commit=request.auto_approved, commit_queue=request.auto_approved,
          hwid_db_contents_internal=internal_db)
    except hwid_repo.HWIDRepoError:
      logging.exception(
          'Caught an unexpected exception while uploading a HWID CL.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
    resp.commit.cl_number = cl_number
    resp.commit.new_hwid_db_contents = (
        v3_action_helper.HWIDV3SelfServiceActionHelper.RemoveHeader(external_db)
    )

    return resp

  def SplitHWIDDBChange(self, request):
    session_cache = self._GetSessionCache(request.session_token)
    project = session_cache.project
    avl_resource = request.db_external_resource
    try:
      action = self._hwid_action_manager.GetHWIDAction(project)
    except (KeyError, ValueError, RuntimeError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

    old_db = database.Database.LoadData(
        action.PatchHeader(action.GetDBEditableSection(internal=True)))
    new_hwid_db_contents_internal = action.ConvertToInternalHWIDDBContent(
        self._avl_converter_manager,
        action.PatchHeader(session_cache.new_hwid_db_editable_section),
        avl_resource)
    new_db = database.Database.LoadData(new_hwid_db_contents_internal)

    change_unit_manager = change_unit_utils.ChangeUnitManager(old_db, new_db)
    self._session_cache_adapter.Put(
        request.session_token,
        session_cache._replace(change_unit_manager=change_unit_manager,
                               avl_resource=avl_resource),
        expiry=hwid_action.SESSION_TIMEOUT)
    return hwid_api_messages_pb2.SplitHwidDbChangeResponse(
        change_units={
            identity: _ConvertChangeUnitToMsg(change_unit)
            for identity, change_unit in
            change_unit_manager.GetChangeUnits().items()
        })

  def CreateSplittedHWIDDBCLs(self, request):

    def _CommitSplittedCL(db: database.Database, msg: str,
                          change_unit_identities: Sequence[str],
                          bot_commit: bool = False,
                          commit_queue: bool = False) -> Tuple[int, str]:
      commit_msg_list = [msg]

      commit_msg_list.append('Reasons:\n')
      commit_msg_list.extend(
          _FormatApprovalStatusReasons(approval_infos[identity])
          for identity in change_unit_identities
          if approval_infos[identity].reasons)

      commit_msg_list.append(f'BUG=b:{request.bug_number}')
      commit_msg = '\n'.join(commit_msg_list)
      new_hwid_db_editable_section = (
          db.DumpDataWithoutChecksum(suppress_support_status=False))
      new_hwid_db_contents_external = action.PatchHeader(
          new_hwid_db_editable_section)
      new_hwid_db_contents_internal = action.ConvertToInternalHWIDDBContent(
          self._avl_converter_manager, new_hwid_db_contents_external,
          session_cache.avl_resource)
      reviewers = set()
      ccs = set()
      for identity in change_unit_identities:
        ccs.update(approval_infos[identity].ccs)
        reviewers.update(approval_infos[identity].reviewers)
      try:
        cl_number = live_hwid_repo.CommitHWIDDB(
            name=project, hwid_db_contents=new_hwid_db_contents_external,
            commit_msg=commit_msg, reviewers=list(reviewers), cc_list=list(ccs),
            bot_commit=bot_commit, commit_queue=commit_queue,
            hwid_db_contents_internal=new_hwid_db_contents_internal)
      except hwid_repo.HWIDRepoError:
        logging.exception(
            'Caught an unexpected exception while uploading a HWID CL.')
        raise protorpc_utils.ProtoRPCException(
            protorpc_utils.RPCCanonicalErrorCode.INTERNAL) from None
      return cl_number, new_hwid_db_contents_external

    # Fetch resources.
    session_cache = self._GetSessionCache(request.session_token)
    change_unit_manager = session_cache.change_unit_manager
    project = session_cache.project
    live_hwid_repo, action = self._GetRepoAndAction(project)
    approval_infos = _CollectApprovalInfos(change_unit_manager,
                                           request.approval_status)

    # Perform change unit related actions.
    split_result = _SplitIntoDBSnapshots(change_unit_manager,
                                         request.approval_status)

    auto_mergeable_change_cl_number = review_required_change_cl_number = 0
    final_hwid_db_content = ''
    final_cl_number = 0

    if not split_result.auto_mergeable_noop:
      commit_msg = textwrap.dedent(f"""\
          ({int(time.time())}) {project}: (Auto-approved) HWID Config Update

          Requested by: {request.original_requester}
          Warning: this CL will be automatically merged or abandoned with the
                   following CL if exists.

          %s
      """) % request.description
      auto_mergeable_change_cl_number, final_hwid_db_content = (
          _CommitSplittedCL(split_result.auto_mergeable_db, commit_msg,
                            split_result.auto_mergeable_change_unit_identities,
                            bot_commit=True,
                            commit_queue=split_result.review_required_noop))
      final_cl_number = auto_mergeable_change_cl_number

    if not split_result.review_required_noop:
      commit_msg = textwrap.dedent(f"""\
          ({int(time.time())}) {project}: HWID Config Update

          Requested by: {request.original_requester}
          Warning: all posted comments will be sent back to the
                   requester.

          %s
      """) % request.description
      review_required_change_cl_number, final_hwid_db_content = (
          _CommitSplittedCL(
              split_result.review_required_db, commit_msg,
              split_result.review_required_change_unit_identities))
      final_cl_number = review_required_change_cl_number

    return hwid_api_messages_pb2.CreateSplittedHwidDbClsResponse(
        auto_mergeable_change_cl_created=not split_result.auto_mergeable_noop,
        auto_mergeable_change_cl_number=auto_mergeable_change_cl_number,
        auto_mergeable_change_unit_identities=(
            split_result.auto_mergeable_change_unit_identities),
        review_required_change_cl_created=not split_result.review_required_noop,
        review_required_change_cl_number=review_required_change_cl_number,
        review_required_change_unit_identities=(
            split_result.review_required_change_unit_identities),
        final_hwid_db_commit=hwid_api_messages_pb2.HwidDbCommit(
            cl_number=final_cl_number,
            new_hwid_db_contents=final_hwid_db_content))

  def _GetRepoAndAction(self, project: str) -> hwid_v3_action.HWIDV3Action:
    live_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    try:
      self._UpdateHWIDDBDataIfNeed(live_repo, project)
      return live_repo, self._hwid_action_manager.GetHWIDAction(project)
    except (KeyError, ValueError, RuntimeError, hwid_repo.HWIDRepoError) as ex:
      raise common_helper.ConvertExceptionToProtoRPCException(ex) from None

  def _GetSessionCache(self, session_token: str) -> _SessionCache:
    session_cache = self._session_cache_adapter.Get(session_token)
    if session_cache is None:
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.ABORTED,
          detail='The validation token is expired.')
    return session_cache
