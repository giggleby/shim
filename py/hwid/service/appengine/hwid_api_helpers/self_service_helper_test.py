# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import os
import re
import textwrap
from typing import Mapping, Optional, Sequence
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import change_unit_utils
from cros.factory.hwid.service.appengine.data import avl_metadata_util
from cros.factory.hwid.service.appengine.data import config_data
from cros.factory.hwid.service.appengine.data.converter import converter as converter_module
from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers import v3_self_service_helper as v3_action_helper
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import self_service_helper as ss_helper_module
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import hwid_v3_action
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import builder as v3_builder
from cros.factory.hwid.v3 import database
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils


_ErrorMsg = (
    hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.Error)
_ErrorCodeMsg = (
    hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.ErrorCode)
_AnalysisReportMsg = hwid_api_messages_pb2.HwidDbEditableSectionAnalysisReport
_DiffStatus = hwid_action.DBHWIDComponentDiffStatus
_DiffStatusMsg = hwid_api_messages_pb2.DiffStatus
_SupportStatusCase = hwid_api_messages_pb2.ComponentSupportStatus.Case
_ComponentInfoMsg = _AnalysisReportMsg.ComponentInfo
_PVAlignmentStatus = hwid_action.DBHWIDPVAlignmentStatus
_PVAlignmentStatusMsg = hwid_api_messages_pb2.ProbeValueAlignmentStatus.Case
_AvlInfoMsg = hwid_api_messages_pb2.AvlInfo
_HWIDSectionChangeMsg = _AnalysisReportMsg.HwidSectionChange
_HWIDSectionChangeStatusMsg = _HWIDSectionChangeMsg.ChangeStatus
_ChangeUnitMsg = hwid_api_messages_pb2.ChangeUnit
_AddEncodingCombinationMsg = _ChangeUnitMsg.AddEncodingCombination
_NewImageIdMsg = _ChangeUnitMsg.NewImageId
_ClActionMsg = hwid_api_messages_pb2.ClAction
_ReplaceRulesMsg = _ChangeUnitMsg.ReplaceRules
_FactoryBundleRecord = hwid_api_messages_pb2.FactoryBundleRecord
_FirmwareRecord = _FactoryBundleRecord.FirmwareRecord
_SessionCache = hwid_action.SessionCache
_ApprovalStatus = change_unit_utils.ApprovalStatus
_ActionHelperCls = v3_action_helper.HWIDV3SelfServiceActionHelper

HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '../testdata/v3-from-factory-bundle.yaml')
_HWID_V3_CHANGE_UNIT_BEFORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '../testdata/change-unit-before.yaml')
_HWID_V3_CHANGE_UNIT_AFTER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '../testdata/change-unit-after.yaml')
_HWID_V3_GOLDEN_WITH_AUDIO_CODEC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '../testdata/v3-golden-audio-codec.yaml')
_HWID_V3_CHANGE_UNIT_INTERNAL_BEFORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '../testdata/change-unit-with-internal-before.yaml')
_HWID_V3_CHANGE_UNIT_INTERNAL_AFTER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '../testdata/change-unit-with-internal-after.yaml')


def _ApplyUnifiedDiff(src: str, diff: str) -> str:
  src_lines = src.splitlines(keepends=True)
  src_next_line_no = 0
  result_lines = []
  for diff_line in diff.splitlines(keepends=True)[2:]:
    hunk_header = re.fullmatch(r'@@\s+-(\d+)(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@',
                               diff_line.rstrip())
    if hunk_header:
      hunk_begin_line_no = int(hunk_header.group(1)) - 1
      while src_next_line_no < hunk_begin_line_no:
        result_lines.append(src_lines[src_next_line_no])
        src_next_line_no += 1
      continue
    if diff_line[0] in (' ', '\n'):
      result_lines.append(src_lines[src_next_line_no])
      src_next_line_no += 1
    elif diff_line[0] == '-':
      src_next_line_no += 1
    elif diff_line[0] == '+':
      result_lines.append(diff_line[1:])
  return ''.join(result_lines + src_lines[src_next_line_no:])


def _CreateFakeSelfServiceHelper(
    modules: test_utils.FakeModuleCollection,
    hwid_repo_manager: hwid_repo.HWIDRepoManager,
    hwid_action_manager_inst: Optional[
        hwid_action_manager.HWIDActionManager] = None,
    hwid_db_data_manager: Optional[hwid_db_data.HWIDDBDataManager] = None,
    avl_converter_manager: Optional[converter_utils.ConverterManager] = None,
    session_cache_adapter: Optional[memcache_adapter.MemcacheAdapter] = None,
    avl_metadata_manager: Optional[avl_metadata_util.AVLMetadataManager] = None,
) -> ss_helper_module.SelfServiceHelper:
  avl_metadata_manager = (
      avl_metadata_manager or avl_metadata_util.AVLMetadataManager(
          modules.ndb_connector,
          config_data.AVLMetadataSetting.CreateInstance(
              False, 'namespace.prefix', 'avl-metadata-topic',
              ['cc1@notgoogle.com'])))
  return ss_helper_module.SelfServiceHelper(
      hwid_action_manager_inst or modules.fake_hwid_action_manager,
      hwid_repo_manager,
      hwid_db_data_manager or modules.fake_hwid_db_data_manager,
      avl_converter_manager or modules.fake_avl_converter_manager,
      session_cache_adapter or modules.fake_session_cache_adapter,
      avl_metadata_manager,
  )


def _AnalyzeHWIDDBEditableSection(ss_helper: ss_helper_module.SelfServiceHelper,
                                  project: str, hwid_db_editable_section: str):
  analyze_req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
      project=project, hwid_db_editable_section=hwid_db_editable_section,
      require_hwid_db_lines=False)

  return ss_helper.AnalyzeHWIDDBEditableSection(analyze_req)


def _SplitHWIDDBChange(
    ss_helper: ss_helper_module.SelfServiceHelper, session_token: str,
    db_external_resource: hwid_api_messages_pb2.HwidDbExternalResource):
  split_req = hwid_api_messages_pb2.SplitHwidDbChangeRequest(
      session_token=session_token, db_external_resource=db_external_resource)
  return ss_helper.SplitHWIDDBChange(split_req)


class SelfServiceHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._mock_hwid_repo_manager = mock.create_autospec(
        hwid_repo.HWIDRepoManager, instance=True)
    self._ss_helper = _CreateFakeSelfServiceHelper(self._modules,
                                                   self._mock_hwid_repo_manager)

  def tearDown(self):
    self._modules.ClearAll()

  def testGetHWIDDBEditableSection_ProjectDoesntExist(self):
    # Default there's no project in the datastore.
    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(
        project='testproject')

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.GetHWIDDBEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testGetHWIDDBEditableSection_InternalError(self):
    self._modules.ConfigHWID('PROJ', '2', 'db data', hwid_action=None)

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(project='proj')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.GetHWIDDBEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INTERNAL)

  def testGetHWIDDBEditableSection_NotV3(self):
    action = hwid_action.HWIDAction()  # Default doesn't support any operations.
    action.HWID_VERSION = 0
    self._modules.ConfigHWID('PROJ', '0', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(project='proj')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.GetHWIDDBEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)

  def testGetHWIDDBEditableSection_Success(self):
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBEditableSection.return_value = 'aa\nbb'
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(project='proj')
    resp = self._ss_helper.GetHWIDDBEditableSection(req)

    self.assertEqual(resp.hwid_db_editable_section, 'aa\nbb')

  def testGetHWIDDBEditableSectionChange_ProjectNotV3(self):
    action = hwid_action.HWIDAction()  # Default doesn't support any operations.
    action.HWID_VERSION = 0
    self._modules.ConfigHWID('PROJ', '0', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(project='proj')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.GetHWIDDBEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)

  def testCreateHWIDDBEditableSectionChangeCL_InvalidValidationToken(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)
    action.AnalyzeDraftDBEditableSection.return_value = (
        hwid_action.DBEditableSectionAnalysisReport(
            'validation-token-value-2', 'db data after change 2',
            'db data after change 2 (internal)', False, [], [], [], {}))

    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='proj', validation_token='validation-token-value-1')

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBEditableSectionChangeCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.ABORTED)

  def testCreateHWIDDBEditableSectionChangeCL_Succeed(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)
    action.AnalyzeDraftDBEditableSection.return_value = (
        hwid_action.DBEditableSectionAnalysisReport(
            'validation-token-value-1', 'db data after change 1',
            'db data after change 1 (internal)', False, [], [], [], {
                'comp1':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls1', comp_name='comp_name1',
                        support_status='unqualified', is_newly_added=False,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=False,
                        diff_prev=_DiffStatus(
                            unchanged=True, name_changed=False,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='comp_name1',
                            prev_support_status='unqualified',
                            probe_value_alignment_status_changed=False,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatus.NO_PROBE_INFO),
                            converter_changed=False), link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO),
                        skip_avl_check=False),
                'comp2':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_cls2_111_222#9',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=(
                            hwid_action.DBHWIDComponentNameInfo.from_comp(
                                111, 222)), seq_no=1,
                        comp_name_with_correct_seq_no='comp_cls2_111_222#1',
                        null_values=False, diff_prev=_DiffStatus(
                            unchanged=False, name_changed=True,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='old_comp_name',
                            prev_support_status='unqualified',
                            probe_value_alignment_status_changed=True,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatus.NO_PROBE_INFO),
                            converter_changed=False), link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.ALIGNED), skip_avl_check=False),
                'comp3':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_name3',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=True,
                        diff_prev=None, link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO),
                        skip_avl_check=False),
            }))

    self._modules.fake_session_cache_adapter.Put(
        'validation-token-value-1', _SessionCache('PROJ',
                                                  'db data after change'))
    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='proj', validation_token='validation-token-value-1')
    resp = self._ss_helper.CreateHWIDDBEditableSectionChangeCL(req)

    self.assertEqual(resp.cl_number, 123)
    self.assertEqual(
        {
            'comp1':
                _ComponentInfoMsg(
                    component_class='comp_cls1',
                    original_name='comp_name1',
                    original_status='unqualified',
                    support_status_case=_SupportStatusCase.UNQUALIFIED,
                    is_newly_added=False,
                    seq_no=2,
                    null_values=False,
                    diff_prev=_DiffStatusMsg(
                        unchanged=True, name_changed=False,
                        support_status_changed=False, values_changed=False,
                        prev_comp_name='comp_name1',
                        prev_support_status='unqualified',
                        prev_support_status_case=_SupportStatusCase.UNQUALIFIED,
                        probe_value_alignment_status_changed=False,
                        prev_probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                    probe_value_alignment_status=(
                        _PVAlignmentStatusMsg.NO_PROBE_INFO),
                ),
            'comp2':
                _ComponentInfoMsg(
                    component_class='comp_cls2',
                    original_name='comp_cls2_111_222#9',
                    original_status='unqualified',
                    support_status_case=_SupportStatusCase.UNQUALIFIED,
                    is_newly_added=True, avl_info=_AvlInfoMsg(
                        cid=111,
                        qid=222,
                    ), has_avl=True, seq_no=1,
                    component_name_with_correct_seq_no='comp_cls2_111_222#1',
                    null_values=False, diff_prev=_DiffStatusMsg(
                        unchanged=False, name_changed=True,
                        support_status_changed=False, values_changed=False,
                        prev_comp_name='old_comp_name',
                        prev_support_status='unqualified',
                        prev_support_status_case=_SupportStatusCase.UNQUALIFIED,
                        probe_value_alignment_status_changed=True,
                        prev_probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                    probe_value_alignment_status=(
                        _PVAlignmentStatusMsg.ALIGNED)),
            'comp3':
                _ComponentInfoMsg(
                    component_class='comp_cls2', original_name='comp_name3',
                    original_status='unqualified',
                    support_status_case=_SupportStatusCase.UNQUALIFIED,
                    is_newly_added=True, seq_no=2, null_values=True,
                    probe_value_alignment_status=(
                        _PVAlignmentStatusMsg.NO_PROBE_INFO)),
        }, resp.analysis_report.component_infos)
    self.assertCountEqual(
        ['deprecated', 'unsupported', 'unqualified', 'duplicate'],
        resp.analysis_report.unqualified_support_status)
    self.assertCountEqual(['supported'],
                          resp.analysis_report.qualified_support_status)
    unused_args, kwargs = live_hwid_repo.CommitHWIDDB.call_args
    self.assertEqual('db data after change 1', kwargs['hwid_db_contents'])
    self.assertEqual('db data after change 1 (internal)',
                     kwargs['hwid_db_contents_internal'])

  def testCreateHWIDDBEditableSectionChangeCL_ValidationExpired(self):
    """Test that the validation token becomes expired once the live HWID repo is
    updated."""

    def CreateMockHWIDAction(hwid_data):
      # Configure the mocked HWIDAction so that it returns the change
      # fingerprint based on the contents of the HWID DB.
      action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
      action.AnalyzeDraftDBEditableSection.return_value = (
          hwid_action.DBEditableSectionAnalysisReport(hwid_data.raw_db, '', '',
                                                      False, [], [], [], {}))
      return action

    self._modules.ConfigHWID('PROJ', '3', 'db data ver 1',
                             hwid_action_factory=CreateMockHWIDAction)
    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='proj', hwid_db_editable_section='db data after change')
    resp = self._ss_helper.AnalyzeHWIDDBEditableSection(req)
    token_that_will_become_expired = resp.validation_token

    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data ver 2')

    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='proj', validation_token=token_that_will_become_expired)

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBEditableSectionChangeCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.ABORTED)

  def _CreateHWIDDBCLWithDefaults(
      self, cl_number: int, status: hwid_repo.HWIDDBCLStatus,
      subject: str = 'subject',
      review_status: Optional[hwid_repo.HWIDDBCLReviewStatus] = (
          hwid_repo.HWIDDBCLReviewStatus.NEUTRAL), comment_threads: Optional[
              Sequence[hwid_repo.HWIDDBCLCommentThread]] = None,
      mergeable: Optional[bool] = None,
      created_time: Optional[datetime.datetime] = None,
      bot_commit: Optional[bool] = None, commit_queue: Optional[bool] = None,
      parent_cl_numbers: Optional[Sequence[int]] = None,
      verified: Optional[bool] = None) -> hwid_repo.HWIDDBCLInfo:
    change_id = str(cl_number)
    if mergeable is None:
      mergeable = status == hwid_repo.HWIDDBCLStatus.NEW
    created_time = created_time or datetime.datetime.utcnow()
    comment_threads = comment_threads or []
    return hwid_repo.HWIDDBCLInfo(change_id, cl_number, subject, status,
                                  review_status, mergeable, created_time,
                                  comment_threads, bot_commit, commit_queue,
                                  parent_cl_numbers, verified)

  def testBatchGetHWIDDBEditableSectionChangeCLInfo(self):
    all_hwid_commit_infos = {
        1:
            self._CreateHWIDDBCLWithDefaults(1, hwid_repo.HWIDDBCLStatus.NEW),
        2:
            self._CreateHWIDDBCLWithDefaults(2,
                                             hwid_repo.HWIDDBCLStatus.MERGED),
        3:
            self._CreateHWIDDBCLWithDefaults(
                3, hwid_repo.HWIDDBCLStatus.ABANDONED),
        4:
            self._CreateHWIDDBCLWithDefaults(
                4, hwid_repo.HWIDDBCLStatus.NEW, comment_threads=[
                    hwid_repo.HWIDDBCLCommentThread(
                        'v3/file1', context='v3/file1:123:text123', comments=[
                            hwid_repo.HWIDDBCLComment('user1@email', 'msg1')
                        ])
                ])
    }

    def _MockGetHWIDDBCLInfo(cl_number):
      try:
        return all_hwid_commit_infos[cl_number]
      except KeyError:
        raise hwid_repo.HWIDRepoError from None

    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = (
        _MockGetHWIDDBCLInfo)

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[1, 2, 3, 4, 5, 6]))
    resp = self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)
    expected_resp = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))

    cl_status = expected_resp.cl_status.get_or_create(1)
    cl_status.status = cl_status.PENDING
    cl_status = expected_resp.cl_status.get_or_create(2)
    cl_status.status = cl_status.MERGED
    cl_status = expected_resp.cl_status.get_or_create(3)
    cl_status.status = cl_status.ABANDONED
    cl_status = expected_resp.cl_status.get_or_create(4)
    cl_status.status = cl_status.PENDING
    cl_status.comments.add(email='user1@email', message='msg1')
    expected_comment_thread = cl_status.comment_threads.add(
        file_path='v3/file1', context='v3/file1:123:text123')
    expected_comment_thread.comments.add(email='user1@email', message='msg1')
    self.assertEqual(resp, expected_resp)

  def testBatchGetHWIDDBEditableSectionChangeCLInfo_AbandonLegacyCLs(self):
    long_time_ago = datetime.datetime.utcnow() - datetime.timedelta(days=365 *
                                                                    9)
    orig_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW, mergeable=True,
        created_time=long_time_ago, parent_cl_numbers=[])
    abandoned_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.ABANDONED, created_time=long_time_ago)

    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [
        orig_cl_info, abandoned_cl_info
    ]

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))
    resp = self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)
    expected_resp = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))

    cl_status = expected_resp.cl_status.get_or_create(2)
    cl_status.status = cl_status.ABANDONED
    self.assertEqual(resp, expected_resp)

  def testBatchGetHWIDDBEditableSectionChangeCLInfo_AbandonMergeConflictCLs(
      self):
    long_time_ago = datetime.datetime.utcnow() - datetime.timedelta(days=35)
    orig_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW, mergeable=False,
        created_time=long_time_ago, parent_cl_numbers=[])
    abandoned_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.ABANDONED, created_time=long_time_ago)

    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [
        orig_cl_info, abandoned_cl_info
    ]

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))
    resp = self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)
    expected_resp = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))

    cl_status = expected_resp.cl_status.get_or_create(2)
    cl_status.status = cl_status.ABANDONED
    self.assertEqual(resp, expected_resp)

  def testBatchGetHWIDDBEditableSectionChangeCLInfo_AbandonReviewRejectedCLs(
      self):
    now = datetime.datetime.utcnow()
    orig_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW,
        review_status=hwid_repo.HWIDDBCLReviewStatus.REJECTED, mergeable=True,
        created_time=now, parent_cl_numbers=[])
    abandoned_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.ABANDONED, created_time=now)

    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [
        orig_cl_info, abandoned_cl_info
    ]

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))
    resp = self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)
    expected_resp = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))

    cl_status = expected_resp.cl_status.get_or_create(2)
    cl_status.status = cl_status.ABANDONED
    self.assertEqual(resp, expected_resp)

  def testBatchGetHWIDDBEditableSectionChangeCLInfo_AbandonCLChain(self):
    # Arrange.
    now = datetime.datetime.utcnow()
    cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW,
        review_status=hwid_repo.HWIDDBCLReviewStatus.REJECTED, mergeable=True,
        created_time=now, parent_cl_numbers=[3, 4])
    parent_cls_info = [
        self._CreateHWIDDBCLWithDefaults(
            3, hwid_repo.HWIDDBCLStatus.NEW,
            review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
            bot_commit=True, created_time=now, parent_cl_numbers=[4]),
        self._CreateHWIDDBCLWithDefaults(
            4, hwid_repo.HWIDDBCLStatus.ABANDONED,
            review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
            bot_commit=True, created_time=now, parent_cl_numbers=[]),
    ]
    abandoned_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.ABANDONED, created_time=now)

    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [
        cl_info, *parent_cls_info, abandoned_cl_info
    ]

    # Act.
    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))
    resp = self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)

    # Assert.
    abandon_reason = 'The CL is rejected by the reviewer.'
    parent_cl_abandon_reason = 'CL:*2 is rejected by the reviewer.'
    self.assertCountEqual([
        mock.call(2, reason=abandon_reason),
        mock.call(3, reason=parent_cl_abandon_reason),
    ], self._mock_hwid_repo_manager.AbandonCL.call_args_list)
    expected_resp = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))
    cl_status = expected_resp.cl_status.get_or_create(2)
    cl_status.status = cl_status.ABANDONED
    self.assertEqual(expected_resp, resp)

  def testBatchGetHWIDDBEditableSectionChangeCLInfo_RebaseMergeConflict(self):
    now = datetime.datetime.utcnow()
    cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW, mergeable=False, created_time=now,
        bot_commit=True)
    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.return_value = cl_info

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))
    self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)

    self._mock_hwid_repo_manager.RebaseCLMetadata.assert_called_once()

  def testBatchGetHWIDDBEditableSectionChangeCLInfo_RebaseFailed(self):
    now = datetime.datetime.utcnow()
    orig_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW, mergeable=False, created_time=now,
        bot_commit=True, parent_cl_numbers=[])
    abandoned_cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.ABANDONED, created_time=now)

    self._mock_hwid_repo_manager.RebaseCLMetadata.side_effect = ValueError
    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [
        orig_cl_info, abandoned_cl_info
    ]

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))
    resp = self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)
    expected_resp = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))

    cl_status = expected_resp.cl_status.get_or_create(2)
    cl_status.status = cl_status.ABANDONED
    self.assertEqual(resp, expected_resp)

  @mock.patch('cros.factory.hwid.service.appengine.git_util.ReviewCL')
  @mock.patch(
      'cros.factory.hwid.service.appengine.git_util.GetGerritAuthCookie')
  def testBatchGetHWIDDBEditableSectionChangeCLInfo_TriggerParentCQ(
      self, mock_auth_cookie, mock_review_cl):
    del mock_auth_cookie
    now = datetime.datetime.utcnow()
    cl_info_with_parents = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW, created_time=now,
        review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
        parent_cl_numbers=[3, 4, 5], verified=True)
    parent_cls_info = [
        self._CreateHWIDDBCLWithDefaults(
            3, hwid_repo.HWIDDBCLStatus.NEW,
            review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
            bot_commit=True, created_time=now, parent_cl_numbers=[4, 5]),
        self._CreateHWIDDBCLWithDefaults(
            4, hwid_repo.HWIDDBCLStatus.NEW,
            review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
            bot_commit=True, created_time=now, parent_cl_numbers=[5]),
        self._CreateHWIDDBCLWithDefaults(
            5, hwid_repo.HWIDDBCLStatus.NEW,
            review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
            bot_commit=True, created_time=now, parent_cl_numbers=[]),
    ]
    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [
        cl_info_with_parents,
        *parent_cls_info,
    ]
    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))

    self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)

    # Verify that the CL and its parent CLs are put into CQ.
    self.assertCountEqual([
        mock.call(hwid_repo.INTERNAL_REPO_REVIEW_URL, mock.ANY,
                  approval_case=git_util.ApprovalCase.COMMIT_QUEUE, cl_number=2,
                  reasons=[]),
        *(mock.call(hwid_repo.INTERNAL_REPO_REVIEW_URL, mock.ANY,
                    approval_case=git_util.ApprovalCase.COMMIT_QUEUE,
                    cl_number=cl_number, reasons=['CL:*2 has been approved.'])
          for cl_number in [3, 4, 5])
    ], mock_review_cl.call_args_list)

  @mock.patch('cros.factory.hwid.service.appengine.git_util.ReviewCL')
  @mock.patch(
      'cros.factory.hwid.service.appengine.git_util.GetGerritAuthCookie')
  def testBatchGetHWIDDBEditableSectionChangeCLInfo_NotCQReady(
      self, mock_auth_cookie, mock_review_cl):
    del mock_auth_cookie
    now = datetime.datetime.utcnow()
    cl_info = self._CreateHWIDDBCLWithDefaults(
        2, hwid_repo.HWIDDBCLStatus.NEW, created_time=now,
        review_status=hwid_repo.HWIDDBCLReviewStatus.APPROVED,
        parent_cl_numbers=[], verified=False)
    self._mock_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = [cl_info]
    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[2]))

    self._ss_helper.BatchGetHWIDDBEditableSectionChangeCLInfo(req)

    # Verify that the CL and its parent CLs are not put into CQ since the
    # Verified vote has not been set.
    self.assertFalse(mock_review_cl.call_args_list)

  def testBatchGenerateAVLComponentName(self):
    req = hwid_api_messages_pb2.BatchGenerateAvlComponentNameRequest()
    for comp_cls, cid, qid, seq_no in [('class1', 1, 0, 1), ('class2', 4, 5, 6),
                                       ('class2', 7, 8, 0)]:
      req.component_name_materials.add(component_class=comp_cls, avl_cid=cid,
                                       avl_qid=qid, seq_no=seq_no)

    resp = self._ss_helper.BatchGenerateAVLComponentName(req)

    self.assertEqual(resp.component_names,
                     ['class1_1#1', 'class2_4_5#6', 'class2_7_8#0'])

  def testAnalyzeHWIDDBEditableSection_PreconditionErrors(self):
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)
    action.AnalyzeDraftDBEditableSection.return_value = (
        hwid_action.DBEditableSectionAnalysisReport(
            'fingerprint', 'new_db_content', None, False, [
                hwid_action.DBValidationError(
                    hwid_action.DBValidationErrorCode.SCHEMA_ERROR,
                    'some_schema_error')
            ], [
                hwid_action.DBPreconditionError(
                    hwid_action.DBPreconditionErrorCode.CONTENTS_ERROR,
                    'some_contents_error')
            ], [], {}))

    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='proj', hwid_db_editable_section='editable contents')
    resp = self._ss_helper.AnalyzeHWIDDBEditableSection(req)

    ValidationResultMsg = (
        hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult)
    self.assertCountEqual(
        list(resp.validation_result.errors), [
            ValidationResultMsg.Error(code=ValidationResultMsg.SCHEMA_ERROR,
                                      message='some_schema_error'),
            ValidationResultMsg.Error(code=ValidationResultMsg.CONTENTS_ERROR,
                                      message='some_contents_error'),
        ])

  def testAnalyzeHWIDDBEditableSection_Pass(self):
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)
    ModificationStatus = (
        hwid_action.DBEditableSectionLineAnalysisResult.ModificationStatus)
    Part = hwid_action.DBEditableSectionLineAnalysisResult.Part
    action.AnalyzeDraftDBEditableSection.return_value = (
        hwid_action.DBEditableSectionAnalysisReport(
            'fingerprint', 'new_db_content', None, False, [], [], [
                hwid_action.DBEditableSectionLineAnalysisResult(
                    ModificationStatus.NOT_MODIFIED,
                    [Part(Part.Type.TEXT, 'text1')]),
                hwid_action.DBEditableSectionLineAnalysisResult(
                    ModificationStatus.MODIFIED,
                    [Part(Part.Type.COMPONENT_NAME, 'comp1')]),
                hwid_action.DBEditableSectionLineAnalysisResult(
                    ModificationStatus.NEWLY_ADDED, [
                        Part(Part.Type.COMPONENT_NAME, 'comp2'),
                        Part(Part.Type.COMPONENT_STATUS, 'comp1')
                    ]),
            ], {
                'comp1':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls1', comp_name='comp_name1',
                        support_status='unqualified', is_newly_added=False,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=True,
                        diff_prev=None, link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO),
                        skip_avl_check=False),
                'comp2':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_cls2_111_222#9',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=(
                            hwid_action.DBHWIDComponentNameInfo.from_comp(
                                111, 222)), seq_no=1,
                        comp_name_with_correct_seq_no='comp_cls2_111_222#1',
                        null_values=False, diff_prev=None, link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO),
                        skip_avl_check=False),
            },
            hwid_action.DBHWIDTouchSections(
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
                {
                    'comp_cls1_fields': hwid_action.DBHWIDTouchCase.TOUCHED,
                    'comp_cls2_fields': hwid_action.DBHWIDTouchCase.UNTOUCHED,
                },
                hwid_action.DBHWIDTouchCase.TOUCHED,
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
            )))

    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='proj', hwid_db_editable_section='editable contents',
        require_hwid_db_lines=True)
    resp = self._ss_helper.AnalyzeHWIDDBEditableSection(req)

    LineMsg = _AnalysisReportMsg.HwidDbLine
    LinePartMsg = _AnalysisReportMsg.HwidDbLinePart
    expected_resp = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse(
        analysis_report=_AnalysisReportMsg(
            unqualified_support_status=[
                'deprecated', 'unsupported', 'unqualified', 'duplicate'
            ], qualified_support_status=['supported'], hwid_config_lines=[
                LineMsg(
                    modification_status=LineMsg.NOT_MODIFIED,
                    parts=[LinePartMsg(fixed_text='text1')],
                ),
                LineMsg(
                    modification_status=LineMsg.MODIFIED,
                    parts=[LinePartMsg(component_name_field_id='comp1')],
                ),
                LineMsg(
                    modification_status=LineMsg.NEWLY_ADDED,
                    parts=[
                        LinePartMsg(component_name_field_id='comp2'),
                        LinePartMsg(support_status_field_id='comp1'),
                    ],
                ),
            ], component_infos={
                'comp1':
                    _ComponentInfoMsg(
                        component_class='comp_cls1', original_name='comp_name1',
                        original_status='unqualified',
                        support_status_case=_SupportStatusCase.UNQUALIFIED,
                        is_newly_added=False, has_avl=False, seq_no=2,
                        null_values=True, probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                'comp2':
                    _ComponentInfoMsg(
                        component_class='comp_cls2',
                        original_name='comp_cls2_111_222#9',
                        original_status='unqualified',
                        support_status_case=_SupportStatusCase.UNQUALIFIED,
                        is_newly_added=True,
                        has_avl=True,
                        avl_info=_AvlInfoMsg(cid=111, qid=222),
                        seq_no=1,
                        component_name_with_correct_seq_no=(
                            'comp_cls2_111_222#1'),
                        probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO),
                    ),
            }, touched_sections=_HWIDSectionChangeMsg(
                image_id_change_status=_HWIDSectionChangeStatusMsg.UNTOUCHED,
                pattern_change_status=_HWIDSectionChangeStatusMsg.UNTOUCHED,
                encoded_fields_change_status={
                    'comp_cls1_fields': _HWIDSectionChangeStatusMsg.TOUCHED,
                    'comp_cls2_fields': _HWIDSectionChangeStatusMsg.UNTOUCHED,
                },
                components_change_status=_HWIDSectionChangeStatusMsg.TOUCHED,
                rules_change_status=_HWIDSectionChangeStatusMsg.UNTOUCHED,
                framework_version_change_status=(
                    _HWIDSectionChangeStatusMsg.UNTOUCHED),
            )), validation_token='fingerprint')
    self.assertEqual(resp, expected_resp)

  def testAnalyzeHWIDDBEditableSection_NoopChange(self):
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)
    action.AnalyzeDraftDBEditableSection.return_value = (
        hwid_action.DBEditableSectionAnalysisReport(
            'fingerprint', 'new_db_content', None, True, [], [], [], {}))

    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='proj', hwid_db_editable_section='new_db_content')
    resp = self._ss_helper.AnalyzeHWIDDBEditableSection(req)

    expected_resp = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse(
        analysis_report=_AnalysisReportMsg(
            unqualified_support_status=[
                'deprecated', 'unsupported', 'unqualified', 'duplicate'
            ], qualified_support_status=['supported'],
            touched_sections=_HWIDSectionChangeMsg(),
            noop_for_external_db=True), validation_token='fingerprint')
    self.assertEqual(resp, expected_resp)

  def testGetHWIDBundleResourceInfo_RefreshDatastoreFirst(self):

    def CreateMockHWIDAction(hwid_data):
      # Configure the mocked HWIDAction so that it returns the resource info
      # fingerprint based on the contents of the HWID DB.
      action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
      action.GetHWIDBundleResourceInfo.return_value = (
          hwid_action.BundleResourceInfo('fingerprint of ' + hwid_data.raw_db,
                                         {}))
      return action

    self._modules.ConfigHWID('PROJ', '3', '',
                             hwid_action_factory=CreateMockHWIDAction)
    self._ConfigHWIDRepoManager('PROJ', 3, 'db data ver 1',
                                'db data ver 1(internal)')
    req1 = hwid_api_messages_pb2.GetHwidBundleResourceInfoRequest(
        project='proj')
    resp1 = self._ss_helper.GetHWIDBundleResourceInfo(req1)
    self._ConfigHWIDRepoManager('PROJ', 3, 'db data ver 2',
                                'db data ver 2(internal)')
    req2 = hwid_api_messages_pb2.GetHwidBundleResourceInfoRequest(
        project='proj')
    resp2 = self._ss_helper.GetHWIDBundleResourceInfo(req2)

    self.assertNotEqual(resp1.bundle_creation_token,
                        resp2.bundle_creation_token)

  def testGetHWIDBundleResourceInfo_Pass(self):

    def CreateMockHWIDAction(hwid_data):
      # Configure the mocked HWIDAction so that it returns the resource info
      # fingerprint based on the contents of the HWID DB.
      action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
      action.GetHWIDBundleResourceInfo.return_value = (
          hwid_action.BundleResourceInfo(
              'fingerprint of ' + hwid_data.raw_db, {
                  'comp1':
                      hwid_action.DBHWIDComponentAnalysisResult(
                          comp_cls='comp_cls1', comp_name='comp_name1',
                          support_status='unqualified', is_newly_added=False,
                          comp_name_info=None, seq_no=2,
                          comp_name_with_correct_seq_no=None, null_values=True,
                          diff_prev=None, link_avl=False,
                          probe_value_alignment_status=(
                              _PVAlignmentStatus.NO_PROBE_INFO),
                          skip_avl_check=False),
                  'comp2':
                      hwid_action.DBHWIDComponentAnalysisResult(
                          comp_cls='comp_cls2', comp_name='comp_cls2_111_222#9',
                          support_status='unqualified', is_newly_added=False,
                          comp_name_info=(
                              hwid_action.DBHWIDComponentNameInfo.from_comp(
                                  111, 222)), seq_no=1,
                          comp_name_with_correct_seq_no='comp_cls2_111_222#1',
                          null_values=True, diff_prev=None, link_avl=True,
                          probe_value_alignment_status=(
                              _PVAlignmentStatus.NO_PROBE_INFO),
                          skip_avl_check=False),
              }))
      return action

    self._modules.ConfigHWID('PROJ', '3', 'db data',
                             hwid_action_factory=CreateMockHWIDAction,
                             raw_db_internal='db data')
    self._ConfigHWIDRepoManager('PROJ', 3, 'db data', 'db data(internal)')
    req = hwid_api_messages_pb2.GetHwidBundleResourceInfoRequest(project='proj')
    resp = self._ss_helper.GetHWIDBundleResourceInfo(req)
    expected_resp = hwid_api_messages_pb2.GetHwidBundleResourceInfoResponse(
        bundle_creation_token='fingerprint of db data',
        resource_info=hwid_api_messages_pb2.HwidBundleResourceInfo(
            db_info=_AnalysisReportMsg(
                component_infos={
                    'comp1':
                        _ComponentInfoMsg(
                            component_class='comp_cls1',
                            original_name='comp_name1',
                            original_status='unqualified',
                            support_status_case=_SupportStatusCase.UNQUALIFIED,
                            is_newly_added=False, avl_info=None, has_avl=False,
                            seq_no=2, component_name_with_correct_seq_no=None,
                            diff_prev=None, null_values=True,
                            probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                    'comp2':
                        _ComponentInfoMsg(
                            component_class='comp_cls2',
                            original_name='comp_cls2_111_222#9',
                            original_status='unqualified',
                            support_status_case=_SupportStatusCase.UNQUALIFIED,
                            is_newly_added=False, avl_info=_AvlInfoMsg(
                                cid=111, qid=222), has_avl=True, seq_no=1,
                            component_name_with_correct_seq_no=(
                                'comp_cls2_111_222#1'), diff_prev=None,
                            null_values=True, probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                })))
    self.assertEqual(resp, expected_resp)

  def testCreateHWIDBundle_ResourceInfoTokenInvalid(self):
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetHWIDBundleResourceInfo.return_value = (
        hwid_action.BundleResourceInfo('fingerprint_value_1', {}))
    self._modules.ConfigHWID('PROJ', '3', 'db data ver 1', hwid_action=action)

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.CreateHwidBundleRequest(
          project='proj', bundle_creation_token='fingerprint_value_2')
      self._ss_helper.CreateHWIDBundle(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.ABORTED)

  def testAnalyzeHWIDDBEditableSection_DiffStatus(self):
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)
    action.AnalyzeDraftDBEditableSection.return_value = (
        hwid_action.DBEditableSectionAnalysisReport(
            'fingerprint', 'new_db_content', None, False, [], [], [], {
                'comp1':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls1', comp_name='comp_name1',
                        support_status='unqualified', is_newly_added=False,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=False,
                        diff_prev=_DiffStatus(
                            unchanged=True, name_changed=False,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='comp_name1',
                            prev_support_status='unqualified',
                            probe_value_alignment_status_changed=False,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatus.NO_PROBE_INFO),
                            converter_changed=False), link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO),
                        skip_avl_check=False),
                'comp2':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_cls2_111_222#9',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=(
                            hwid_action.DBHWIDComponentNameInfo.from_comp(
                                111, 222)), seq_no=1,
                        comp_name_with_correct_seq_no='comp_cls2_111_222#1',
                        null_values=False, diff_prev=_DiffStatus(
                            unchanged=False, name_changed=True,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='old_comp_name',
                            prev_support_status='unqualified',
                            probe_value_alignment_status_changed=True,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatus.NO_PROBE_INFO),
                            converter_changed=False), link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.ALIGNED), skip_avl_check=False),
                'comp3':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_name3',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=True,
                        diff_prev=None, link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO),
                        skip_avl_check=False),
            },
            hwid_action.DBHWIDTouchSections(
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
                {
                    'comp_cls1_fields': hwid_action.DBHWIDTouchCase.TOUCHED,
                    'comp_cls2_fields': hwid_action.DBHWIDTouchCase.TOUCHED,
                    'comp_cls3_fields': hwid_action.DBHWIDTouchCase.UNTOUCHED,
                },
                hwid_action.DBHWIDTouchCase.TOUCHED,
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
                hwid_action.DBHWIDTouchCase.UNTOUCHED,
            )))

    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='proj', hwid_db_editable_section='editable contents',
        require_hwid_db_lines=False)
    resp = self._ss_helper.AnalyzeHWIDDBEditableSection(req)

    expected_resp = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse(
        analysis_report=_AnalysisReportMsg(
            unqualified_support_status=[
                'deprecated', 'unsupported', 'unqualified', 'duplicate'
            ], qualified_support_status=['supported'], hwid_config_lines=[],
            component_infos={
                'comp1':
                    _ComponentInfoMsg(
                        component_class='comp_cls1', original_name='comp_name1',
                        original_status='unqualified',
                        support_status_case=_SupportStatusCase.UNQUALIFIED,
                        is_newly_added=False, has_avl=False, seq_no=2,
                        diff_prev=_DiffStatusMsg(
                            unchanged=True, name_changed=False,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='comp_name1',
                            prev_support_status='unqualified',
                            prev_support_status_case=(
                                _SupportStatusCase.UNQUALIFIED),
                            probe_value_alignment_status_changed=False,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                        probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                'comp2':
                    _ComponentInfoMsg(
                        component_class='comp_cls2',
                        original_name='comp_cls2_111_222#9',
                        original_status='unqualified',
                        support_status_case=_SupportStatusCase.UNQUALIFIED,
                        is_newly_added=True, has_avl=True, avl_info=_AvlInfoMsg(
                            cid=111, qid=222), seq_no=1,
                        component_name_with_correct_seq_no=(
                            'comp_cls2_111_222#1'),
                        diff_prev=_DiffStatusMsg(
                            unchanged=False, name_changed=True,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='old_comp_name',
                            prev_support_status='unqualified',
                            prev_support_status_case=(
                                _SupportStatusCase.UNQUALIFIED),
                            probe_value_alignment_status_changed=True,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                        probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.ALIGNED)),
                'comp3':
                    _ComponentInfoMsg(
                        component_class='comp_cls2', original_name='comp_name3',
                        original_status='unqualified',
                        support_status_case=_SupportStatusCase.UNQUALIFIED,
                        is_newly_added=True, has_avl=False, seq_no=2,
                        null_values=True, probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
            }, touched_sections=_HWIDSectionChangeMsg(
                image_id_change_status=_HWIDSectionChangeStatusMsg.UNTOUCHED,
                pattern_change_status=_HWIDSectionChangeStatusMsg.UNTOUCHED,
                encoded_fields_change_status={
                    'comp_cls1_fields': _HWIDSectionChangeStatusMsg.TOUCHED,
                    'comp_cls2_fields': _HWIDSectionChangeStatusMsg.TOUCHED,
                    'comp_cls3_fields': _HWIDSectionChangeStatusMsg.UNTOUCHED,
                },
                components_change_status=_HWIDSectionChangeStatusMsg.TOUCHED,
                rules_change_status=_HWIDSectionChangeStatusMsg.UNTOUCHED,
                framework_version_change_status=(
                    _HWIDSectionChangeStatusMsg.UNTOUCHED),
            )), validation_token='fingerprint')

    self.assertEqual(resp, expected_resp)

  def testCreateHWIDDBInitCL_Succeed(self):
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    live_hwid_repo.GetHWIDDBMetadataByName.side_effect = ValueError

    builder = v3_builder.DatabaseBuilder.FromEmpty(project='proj',
                                                   image_name='EVT')
    db_content = builder.Build().DumpDataWithoutChecksum(internal=True)
    expected_db_content = _ActionHelperCls.RemoveHeader(db_content)

    req = hwid_api_messages_pb2.CreateHwidDbInitClRequest(
        project='proj', board='board', phase='EVT', bug_number=12345)
    resp = self._ss_helper.CreateHWIDDBInitCL(req)

    self.assertEqual(resp.commit.cl_number, 123)
    self.assertEqual(expected_db_content, resp.commit.new_hwid_db_contents)

  def testCreateHWIDDBInitCL_ProjectExists(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')

    req = hwid_api_messages_pb2.CreateHwidDbInitClRequest(
        project='proj', board='board', phase='EVT', bug_number=12345)

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBInitCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)

  def testCreateHWIDDBInitCL_NoBugNumber(self):
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    live_hwid_repo.GetHWIDDBMetadataByName.side_effect = ValueError

    req = hwid_api_messages_pb2.CreateHwidDbInitClRequest(
        project='proj', board='board', phase='EVT')

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBInitCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)

  def testCreateHWIDDBFirmwareInfoUpdateCL_Succeed(self):
    raw_db = file_utils.ReadFile(HWIDV3_FILE)
    self._ConfigLiveHWIDRepo('PROJ', 3, raw_db)
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    action = self._CreateFakeHWIDBAction('PROJ', raw_db)
    self._modules.ConfigHWID('PROJ', '3', raw_db, hwid_action=action)

    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=self._CreateBundleRecord(['proj']))
    resp = self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)
    comps = action.GetComponents(
        ['ro_main_firmware', 'ro_fp_firmware', 'firmware_keys'])

    self.assertIn('Google_Proj_1111_1_1', comps['ro_main_firmware'])
    self.assertIn('fp_firmware_1', comps['ro_fp_firmware'])
    self.assertIn('fp_firmware_2', comps['ro_fp_firmware'])
    self.assertIn('firmware_keys_mp_default', comps['firmware_keys'])
    self.assertIn('PROJ', resp.commits)
    self.assertEqual(resp.commits['PROJ'].cl_number, 123)
    self.assertEqual(resp.commits['PROJ'].new_hwid_db_contents,
                     action.GetDBEditableSection())

  def testCreateHWIDDBFirmwareInfoUpdateCL_Succeed_DevSignedFirmware(self):
    raw_db = file_utils.ReadFile(HWIDV3_FILE)
    self._ConfigLiveHWIDRepo('PROJ', 3, raw_db)
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    action = self._CreateFakeHWIDBAction('PROJ', raw_db)
    self._modules.ConfigHWID('PROJ', '3', raw_db, hwid_action=action)

    firmware_record = _FirmwareRecord(
        model='proj', firmware_keys=[
            _FirmwareRecord.FirmwareKeys(key_recovery='#devkeys/recoverykey',
                                         key_root='#devkeys/rootkey')
        ])
    bundle_record = _FactoryBundleRecord(board='board', firmware_signer='',
                                         firmware_records=[firmware_record])
    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=bundle_record)
    resp = self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)
    comps = action.GetComponents(['firmware_keys'])

    self.assertIn('firmware_keys_dev', comps['firmware_keys'])
    self.assertIn('PROJ', resp.commits)
    self.assertEqual(resp.commits['PROJ'].cl_number, 123)
    self.assertEqual(resp.commits['PROJ'].new_hwid_db_contents,
                     action.GetDBEditableSection())

  def testCreateHWIDDBFirmwareInfoUpdateCL_ProjectNotFound(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')

    firmware_record = _FirmwareRecord(model='notproj')
    bundle_record = _FactoryBundleRecord(firmware_records=[firmware_record])
    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=bundle_record)
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testCreateHWIDDBFirmwareInfoUpdateCL_InvalidSigner(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock.MagicMock(spec=database.WritableDatabase)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)

    firmware_record = _FirmwareRecord(model='proj')
    bundle_record = _FactoryBundleRecord(board='board',
                                         firmware_signer='InvalidSigner-V1',
                                         firmware_records=[firmware_record])
    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=bundle_record)
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)

  def testCreateHWIDDBFirmwareInfoUpdateCL_InternalError(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.side_effect = [hwid_repo.HWIDRepoError]
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock.MagicMock(spec=database.WritableDatabase)
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=self._CreateBundleRecord(['proj']))
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INTERNAL)

  @mock.patch('cros.factory.hwid.service.appengine.hwid_action_helpers'
              '.v3_self_service_helper.HWIDV3SelfServiceActionHelper'
              '.RemoveHeader')
  def testCreateHWIDDBFirmwareInfoUpdateCL_InternalError_AbandonCL(
      self, remove_header):
    self._ConfigLiveHWIDRepo('PROJ1', 3, 'db data')
    self._ConfigLiveHWIDRepo('PROJ2', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.side_effect = [123, hwid_repo.HWIDRepoError]
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock.MagicMock(spec=database.WritableDatabase)
    remove_header.return_value = 'db data'
    self._modules.ConfigHWID('PROJ1', '3', 'db data', hwid_action=action)
    self._modules.ConfigHWID('PROJ2', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=self._CreateBundleRecord(['proj1', 'proj2']))
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)

    self._mock_hwid_repo_manager.AbandonCL.assert_called_with(123)
    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INTERNAL)

  def testSetFirmwareInfoSupportStatus_Succeed(self):
    raw_db = file_utils.ReadFile(HWIDV3_FILE)
    self._ConfigLiveHWIDRepo('PROJ', 3, raw_db)
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    action = self._CreateFakeHWIDBAction('PROJ', raw_db)
    self._modules.ConfigHWID('PROJ', '3', raw_db, hwid_action=action)

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='proj', version_string='google_proj.1111.1.1')
    resp = self._ss_helper.SetFirmwareInfoSupportStatus(req)
    comps = action.GetComponents(['ro_main_firmware', 'ro_ec_firmware'])

    self.assertEqual(comps['ro_main_firmware']['ro_main_firmware_1'].status,
                     'supported')
    self.assertEqual(comps['ro_ec_firmware']['ro_ec_firmware_1'].status,
                     'supported')
    self.assertEqual(resp.commit.cl_number, 123)
    self.assertEqual(resp.commit.new_hwid_db_contents,
                     action.GetDBEditableSection())

  def testSetFirmwareInfoSupportStatus_ProjectNotFound(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='notproj')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.SetFirmwareInfoSupportStatus(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testSetFirmwareInfoSupportStatus_NoChange(self):
    raw_db = file_utils.ReadFile(HWIDV3_FILE)
    self._ConfigLiveHWIDRepo('PROJ', 3, raw_db)
    action = self._CreateFakeHWIDBAction('PROJ', raw_db)
    self._modules.ConfigHWID('PROJ', '3', raw_db, hwid_action=action)

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='proj', version_string='google_proj.2222.2.2')
    resp = self._ss_helper.SetFirmwareInfoSupportStatus(req)
    comps = action.GetComponents(['ro_main_firmware', 'ro_ec_firmware'])

    self.assertEqual(comps['ro_main_firmware']['ro_main_firmware_2'].status,
                     'unqualified')
    self.assertEqual(
        resp, hwid_api_messages_pb2.SetFirmwareInfoSupportStatusResponse())

  def testSetFirmwareInfoSupportStatus_InternalError(self):
    raw_db = file_utils.ReadFile(HWIDV3_FILE)
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.side_effect = [hwid_repo.HWIDRepoError]
    action = self._CreateFakeHWIDBAction('PROJ', raw_db)
    self._modules.ConfigHWID('PROJ', '3', raw_db, hwid_action=action)

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='proj', version_string='google_proj.1111.1.1')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.SetFirmwareInfoSupportStatus(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INTERNAL)

  def testSplitHWIDDBChange_InvalidToken(self):
    req = hwid_api_messages_pb2.SplitHwidDbChangeRequest(
        session_token='invalid_token')

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.SplitHWIDDBChange(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.ABORTED)
    self.assertEqual(ex.exception.detail, 'The validation token is expired.')

  def testSplitHWIDDBChange_Pass(self):
    project = 'CHROMEBOOK'
    old_db_data = file_utils.ReadFile(_HWID_V3_CHANGE_UNIT_BEFORE)
    new_db_data = file_utils.ReadFile(_HWID_V3_CHANGE_UNIT_AFTER)
    # Config repo and action.
    self._ConfigLiveHWIDRepo(project, 3, old_db_data)
    action = self._CreateFakeHWIDBAction(project, old_db_data)
    self._modules.ConfigHWID(project, '3', old_db_data, hwid_action=action)

    # Call AnalyzeHWIDDBEditableSection to start a HWID DB change workflow.
    analyze_resp = _AnalyzeHWIDDBEditableSection(self._ss_helper, project,
                                                 new_db_data)
    session_token = analyze_resp.validation_token

    db_external_resource = hwid_api_messages_pb2.HwidDbExternalResource()
    split_req = hwid_api_messages_pb2.SplitHwidDbChangeRequest(
        session_token=session_token, db_external_resource=db_external_resource)

    split_resp = self._ss_helper.SplitHWIDDBChange(split_req)

    new_comp_msg = _ComponentInfoMsg(
        component_class='comp_cls_1', original_name='new_comp',
        original_status='supported',
        support_status_case=_SupportStatusCase.SUPPORTED, is_newly_added=True,
        seq_no=3,
        probe_value_alignment_status=_PVAlignmentStatusMsg.NO_PROBE_INFO)
    self.assertCountEqual([
        _ChangeUnitMsg(
            add_encoding_combination=_AddEncodingCombinationMsg(
                comp_cls='comp_cls_1', comp_info=[new_comp_msg])),
        _ChangeUnitMsg(comp_change=new_comp_msg),
        _ChangeUnitMsg(
            new_image_id=_NewImageIdMsg(
                image_names=['NEW_PHASE'],
            )),
        _ChangeUnitMsg(
            add_encoding_combination=_AddEncodingCombinationMsg(
                comp_cls='comp_cls_1', comp_info=[new_comp_msg, new_comp_msg])),
        _ChangeUnitMsg(
            new_image_id=_NewImageIdMsg(
                image_names=[
                    'PHASE_NO_NEW_PATTERN_1', 'PHASE_NO_NEW_PATTERN_2'
                ], with_new_encoding_pattern=True)),
        _ChangeUnitMsg(
            new_image_id=_NewImageIdMsg(
                image_names=['PHASE_NEW_PATTERN_1', 'PHASE_NEW_PATTERN_2'],
                with_new_encoding_pattern=True)),
    ], list(split_resp.change_units.values()))

  def testCreateSplittedHWIDDBCLs_Pass(self):
    # Arrange.
    project = 'CHROMEBOOK'
    old_db_data = file_utils.ReadFile(_HWID_V3_CHANGE_UNIT_BEFORE)
    new_db_data = file_utils.ReadFile(_HWID_V3_CHANGE_UNIT_AFTER)
    # Config repo and action.
    self._ConfigLiveHWIDRepo(project, 3, old_db_data)
    action = self._CreateFakeHWIDBAction(project, old_db_data)
    self._modules.ConfigHWID(project, '3', old_db_data, hwid_action=action)

    # Call AnalyzeHWIDDBEditableSection to start a HWID DB change workflow.
    analyze_resp = _AnalyzeHWIDDBEditableSection(self._ss_helper, project,
                                                 new_db_data)
    session_token = analyze_resp.validation_token
    split_resp = _SplitHWIDDBChange(
        self._ss_helper, session_token,
        hwid_api_messages_pb2.HwidDbExternalResource())

    create_cl_req = hwid_api_messages_pb2.CreateSplittedHwidDbClsRequest(
        session_token=session_token,
        original_requester='requester@notgoogle.com', description='description',
        bug_number=100)
    approval_status = create_cl_req.approval_status

    # Act: only set one AddEncodingCombination change unit as
    # MANUAL_REVIEW_REQUIRED.
    change_unit_mapping = split_resp.change_units
    approved_cl_action = _ClActionMsg(
        approval_case=_ClActionMsg.ApprovalCase.APPROVED,
        reviewers=['reviewer1@notgoogle.com', 'reviewer2@notgoogle.com'],
        ccs=['cc1@notgoogle.com', 'cc2@notgoogle.com'])
    review_required_cl_action = _ClActionMsg(
        approval_case=_ClActionMsg.ApprovalCase.NEED_MANUAL_REVIEW,
        reviewers=['reviewer3@notgoogle.com', 'reviewer4@notgoogle.com'],
        ccs=['cc3@notgoogle.com', 'cc4@notgoogle.com'])

    for identity, change_unit in change_unit_mapping.items():
      if change_unit.WhichOneof(
          'change_unit_type') != 'add_encoding_combination':
        approval_status[identity].CopyFrom(approved_cl_action)
      elif len(change_unit.add_encoding_combination.comp_info) != 1:
        approval_status[identity].CopyFrom(approved_cl_action)
      else:
        # The combination of
        #   comp_cls_1: new_comp
        approval_status[identity].CopyFrom(review_required_cl_action)
      approval_status[identity].reasons[:] = [
          f'reason1 of {identity}.',
          f'reason2 of {identity}.',
      ]

    create_cl_resp = self._ss_helper.CreateSplittedHWIDDBCLs(create_cl_req)

    # Assert: both auto-approved and reviewed-required CLs are created.
    self.assertTrue(create_cl_resp.auto_mergeable_change_cl_created)
    self.assertTrue(create_cl_resp.review_required_change_cl_created)

    # Validate the two CommitHWIDDB calls.
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    self.assertEqual(2, live_hwid_repo.CommitHWIDDB.call_count)
    auto_approved_call, review_required_call = (
        kwargs for (unused_args,
                    kwargs) in live_hwid_repo.CommitHWIDDB.call_args_list)

    expected_auto_approved_diff = textwrap.dedent('''\
        ---
        +++
        @@ -11,7 +11,7 @@
         # 若修改将使设备配置變為无效，并且不得销售此设备。
         #
         #####
        -checksum: 3e9825a9a00edbbce83997944d47a6d412f604ca
        +checksum: 222abbbca451589a2cc44535fbe67f4feccb9ac2

         ##### END CHECKSUM BLOCK. See the warning above. 请参考上面的警告。

        @@ -24,11 +24,15 @@
         image_id:
           0: PROTO
           1: EVT
        +  2: NEW_PHASE
        +  3: PHASE_NO_NEW_PATTERN_1
        +  4: PHASE_NO_NEW_PATTERN_2

         pattern:
         - image_ids:
           - 0
           - 1
        +  - 2
           encoding_scheme: base8192
           fields:
           - mainboard_field: 3
        @@ -41,6 +45,14 @@
           - ro_main_firmware_field: 1
           - comp_cls_1_field: 2
           - comp_cls_23_field: 2
        +- image_ids:
        +  - 3
        +  - 4
        +  encoding_scheme: base8192
        +  fields:
        +  - cpu_field: 5
        +  - comp_cls_1_field: 2
        +  - ro_main_firmware_field: 1

         encoded_fields:
           chassis_field:
        @@ -122,6 +134,10 @@
                 status: supported
                 values:
                   value: '2'
        +      new_comp:
        +        status: supported
        +        values:
        +          value: '3'
           comp_cls_2:
             items:
               comp_2_1:
    ''')

    expected_review_required_diff = textwrap.dedent('''\
        ---
        +++
        @@ -11,7 +11,7 @@
         # 若修改将使设备配置變為无效，并且不得销售此设备。
         #
         #####
        -checksum: 222abbbca451589a2cc44535fbe67f4feccb9ac2
        +checksum: 72f58aceddca8779c32728e7f35989c7ea839dc9

         ##### END CHECKSUM BLOCK. See the warning above. 请参考上面的警告。

        @@ -27,6 +27,8 @@
           2: NEW_PHASE
           3: PHASE_NO_NEW_PATTERN_1
           4: PHASE_NO_NEW_PATTERN_2
        +  5: PHASE_NEW_PATTERN_1
        +  6: PHASE_NEW_PATTERN_2

         pattern:
         - image_ids:
        @@ -45,6 +47,8 @@
           - ro_main_firmware_field: 1
           - comp_cls_1_field: 2
           - comp_cls_23_field: 2
        +  - new_field: 0
        +  - new_field: 1
         - image_ids:
           - 3
           - 4
        @@ -53,6 +57,13 @@
           - cpu_field: 5
           - comp_cls_1_field: 2
           - ro_main_firmware_field: 1
        +- image_ids:
        +  - 5
        +  - 6
        +  encoding_scheme: base8192
        +  fields:
        +  - comp_cls_1_field: 2
        +  - new_field: 2

         encoded_fields:
           chassis_field:
        @@ -91,6 +102,13 @@
             1:
               comp_cls_2: comp_2_2
               comp_cls_3: comp_3_2
        +  new_field:
        +    0:
        +      comp_cls_1: new_comp
        +    1:
        +      comp_cls_1:
        +      - new_comp
        +      - new_comp

         components:
           mainboard:
    ''')

    auto_approved_db_content = _ApplyUnifiedDiff(old_db_data,
                                                 expected_auto_approved_diff)
    review_required_db_content = _ApplyUnifiedDiff(
        auto_approved_db_content, expected_review_required_diff)

    # Validate auto-approved HWID DB CL.
    self.assertTrue(auto_approved_call['bot_commit'])
    self.assertFalse(auto_approved_call['commit_queue'])
    self.assertCountEqual([
        'cc1@notgoogle.com',
        'cc2@notgoogle.com',
    ], auto_approved_call['cc_list'])
    self.assertCountEqual([
        'reviewer1@notgoogle.com',
        'reviewer2@notgoogle.com',
    ], auto_approved_call['reviewers'])
    self.assertEqual(auto_approved_db_content,
                     auto_approved_call['hwid_db_contents'])
    self.assertEqual(auto_approved_db_content,
                     auto_approved_call['hwid_db_contents_internal'])
    self.assertTrue(
        all(f'reason1 of {identity}.' in auto_approved_call['commit_msg'] and
            f'reason2 of {identity}.' in auto_approved_call['commit_msg'] for
            identity in create_cl_resp.auto_mergeable_change_unit_identities))

    # Validate review-required HWID DB CL.
    self.assertFalse(review_required_call['bot_commit'])
    self.assertFalse(review_required_call['commit_queue'])
    self.assertCountEqual([
        'cc1@notgoogle.com',
        'cc2@notgoogle.com',
        'cc3@notgoogle.com',
        'cc4@notgoogle.com',
    ], review_required_call['cc_list'])
    self.assertCountEqual([
        'reviewer1@notgoogle.com',
        'reviewer2@notgoogle.com',
        'reviewer3@notgoogle.com',
        'reviewer4@notgoogle.com',
    ], review_required_call['reviewers'])

    self.assertEqual(review_required_db_content,
                     review_required_call['hwid_db_contents'])
    self.assertEqual(review_required_db_content,
                     review_required_call['hwid_db_contents_internal'])
    self.assertTrue(
        all(f'reason1 of {identity}.' in review_required_call['commit_msg'] and
            f'reason2 of {identity}.' in review_required_call['commit_msg'] for
            identity in create_cl_resp.review_required_change_unit_identities))

  def testCreateSplittedHWIDDBCLs_AVLAlignmentChanges(self):

    def CreateMockAVLConverterManager(
        match_result_mapping: Mapping[
            str, Sequence[converter_module.CollectionMatchResult]]
    ) -> converter_utils.ConverterManager:
      converter_collections = {}
      for comp_cls, match_results in match_result_mapping.items():
        converter_collection = mock.create_autospec(
            converter_module.ConverterCollection, instance=True)
        converter_collection.Match.side_effect = match_results
        converter_collections[comp_cls] = converter_collection
      return converter_utils.ConverterManager(converter_collections)

    # Arrange.
    project = 'CHROMEBOOK'
    old_db_data = file_utils.ReadFile(_HWID_V3_CHANGE_UNIT_INTERNAL_BEFORE)
    # The internal format is unused but just as a reference of the expected
    # final resut.
    new_db_data = file_utils.ReadFile(_HWID_V3_CHANGE_UNIT_INTERNAL_AFTER)
    editable_content = _ActionHelperCls.RemoveHeader(
        database.Database.LoadData(new_db_data).DumpDataWithoutChecksum(
            suppress_support_status=False))
    # Config repo and action.
    self._ConfigLiveHWIDRepo(project, 3, old_db_data)
    action = self._CreateFakeHWIDBAction(project, old_db_data)
    self._modules.ConfigHWID(project, '3', old_db_data, hwid_action=action)

    mock_avl_converter_manager = CreateMockAVLConverterManager({
        'comp_cls1': [
            # comp_cls1_2: both converter and alignment status are unchanged.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter1',
            ),
            # comp_cls1_3: change to aligned with converter1 from non-AVL one.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter1',
            ),
            # comp_cls1_4: change to aligned with converter changed.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter2',
            ),
            # comp_cls1_5: new component with converter and alignment status.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter1',
            ),
        ],
        'comp_cls2': [
            # comp_cls2_2: both converter and alignment status are unchanged.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter1',
            ),
            # comp_cls2_3: change to aligned with converter1 from non-AVL one.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter1',
            ),
            # comp_cls2_4: change to aligned with converter changed.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter2',
            ),
            # comp_cls2_5: new component with converter and alignment status.
            converter_module.CollectionMatchResult(
                _PVAlignmentStatus.ALIGNED,
                'converter1',
            ),
        ],
    })
    # Mock ConverterManager instance in SelfServiceHelper.
    ss_helper = _CreateFakeSelfServiceHelper(
        self._modules,
        self._mock_hwid_repo_manager,
        avl_converter_manager=mock_avl_converter_manager,
    )
    # Call AnalyzeHWIDDBEditableSection to start a HWID DB change workflow.
    analyze_resp = _AnalyzeHWIDDBEditableSection(ss_helper, project,
                                                 editable_content)
    session_token = analyze_resp.validation_token

    # ConverterCollection.Match will look up probe_info by CID.  Since we are
    # mocking ConverterCollection.Match, only filling CID is enough.
    db_external_resource = hwid_api_messages_pb2.HwidDbExternalResource(
        component_probe_infos=[
            stubby_pb2.ComponentProbeInfo(
                component_identity=stubby_pb2.ComponentIdentity(component_id=i))
            # CID 1 and 6 are skipped as non-AVL-linked cases.
            for i in [2, 3, 4, 5, 7, 8, 9, 10]
        ])
    split_resp = _SplitHWIDDBChange(ss_helper, session_token,
                                    db_external_resource)

    create_cl_req = hwid_api_messages_pb2.CreateSplittedHwidDbClsRequest(
        session_token=session_token,
        original_requester='requester@notgoogle.com', description='description',
        bug_number=100)
    approval_status = create_cl_req.approval_status

    # Act
    change_unit_mapping = split_resp.change_units
    approved_cl_action = _ClActionMsg(
        approval_case=_ClActionMsg.ApprovalCase.APPROVED)
    review_required_cl_action = _ClActionMsg(
        approval_case=_ClActionMsg.ApprovalCase.NEED_MANUAL_REVIEW)
    # Set the changes of comp_cls1 comps AUTO_APPROVED and set the
    # other changes as MANUAL_REVIEW_REQUIRED.
    for identity, change_unit in change_unit_mapping.items():
      if (change_unit.WhichOneof('change_unit_type') == 'comp_change' and
          change_unit.comp_change.component_class == 'comp_cls1'):
        approval_status[identity].CopyFrom(approved_cl_action)
      else:
        approval_status[identity].CopyFrom(review_required_cl_action)

    ss_helper.CreateSplittedHWIDDBCLs(create_cl_req)

    # Assert
    # Validate the two CommitHWIDDB calls.
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    self.assertEqual(2, live_hwid_repo.CommitHWIDDB.call_count)
    auto_approved_call, review_required_call = (
        kwargs for (unused_args,
                    kwargs) in live_hwid_repo.CommitHWIDDB.call_args_list)

    expected_auto_approved_diff = textwrap.dedent('''\
        ---
        +++
        @@ -11,7 +11,7 @@
         # 若修改将使设备配置變為无效，并且不得销售此设备。
         #
         #####
        -checksum:
        +checksum: 24ab053b998f9bd18273c6b2ebfb3d17285eb893

         ##### END CHECKSUM BLOCK. See the warning above. 请参考上面的警告。

        @@ -133,15 +133,25 @@
                   probe_value_matched: true
               comp_cls1_3:
                 status: supported
        -        values:
        -          incorrect_value: '3'
        +        values: !link_avl
        +          converter: converter1
        +          original_values:
        +            value: '3'
        +          probe_value_matched: true
               comp_cls1_4:
        +        status: supported
        +        values: !link_avl
        +          converter: converter2
        +          original_values:
        +            value2: '4'
        +          probe_value_matched: true
        +      comp_cls1_5:
                 status: supported
                 values: !link_avl
                   converter: converter1
                   original_values:
        -            value: '4'
        -          probe_value_matched: false
        +            value: '5'
        +          probe_value_matched: true
           comp_cls2:
             items:
               comp_cls2_6:
    ''')
    expected_review_required_diff = textwrap.dedent('''\
        ---
        +++
        @@ -11,7 +10,7 @@
         # 若修改将使设备配置變為无效，并且不得销售此设备。
         #
         #####
        -checksum: 24ab053b998f9bd18273c6b2ebfb3d17285eb893
        +checksum: b5ff010eb9860e7733b7fa21bc0444c4091b4eea

         ##### END CHECKSUM BLOCK. See the warning above. 请参考上面的警告。

        @@ -41,6 +40,7 @@
           - ro_main_firmware_field: 1
           - comp_cls1_field: 2
           - comp_cls2_field: 3
        +  - comp_cls1_field: 1

         encoded_fields:
           chassis_field:
        @@ -76,6 +76,8 @@
               comp_cls1: comp_cls1_3
             3:
               comp_cls1: comp_cls1_4
        +    4:
        +      comp_cls1: comp_cls1_5
           comp_cls2_field:
             0:
               comp_cls2: comp_cls2_6
        @@ -85,6 +87,8 @@
               comp_cls2: comp_cls2_8
             3:
               comp_cls2: comp_cls2_9
        +    4:
        +      comp_cls2: comp_cls2_10

         components:
           mainboard:
        @@ -167,14 +171,24 @@
                   probe_value_matched: true
               comp_cls2_8:
                 status: supported
        -        values:
        -          incorrect_value: '3'
        +        values: !link_avl
        +          converter: converter1
        +          original_values:
        +            value: '3'
        +          probe_value_matched: true
               comp_cls2_9:
        +        status: supported
        +        values: !link_avl
        +          converter: converter2
        +          original_values:
        +            value2: '4'
        +          probe_value_matched: true
        +      comp_cls2_10:
                 status: supported
                 values: !link_avl
                   converter: converter1
                   original_values:
        -            value: '4'
        -          probe_value_matched: false
        +            value: '5'
        +          probe_value_matched: true

         rules: []
    ''')
    auto_approved_db_content_internal = _ApplyUnifiedDiff(
        old_db_data, expected_auto_approved_diff)
    auto_approved_db_content_external = action.PatchHeader(
        database.Database.LoadData(auto_approved_db_content_internal)
        .DumpDataWithoutChecksum(suppress_support_status=False))

    review_required_db_content_internal = _ApplyUnifiedDiff(
        auto_approved_db_content_internal, expected_review_required_diff)
    review_required_db_content_external = action.PatchHeader(
        database.Database.LoadData(review_required_db_content_internal)
        .DumpDataWithoutChecksum(suppress_support_status=False))

    # Validate contents of auto-approved HWID DB CL.
    self.assertEqual(auto_approved_db_content_external,
                     auto_approved_call['hwid_db_contents'])
    self.assertEqual(auto_approved_db_content_internal,
                     auto_approved_call['hwid_db_contents_internal'])

    # Validate contents review-required HWID DB CL.
    self.assertEqual(review_required_db_content_external,
                     review_required_call['hwid_db_contents'])
    self.assertEqual(review_required_db_content_internal,
                     review_required_call['hwid_db_contents_internal'])

  def testUpdateAudioCodecKernelNames_HasIntersection(self):
    req = hwid_api_messages_pb2.UpdateAudioCodecKernelNamesRequest(
        allowlisted_kernel_names=['common', 'allowlist1', 'allowlist2'],
        blocklisted_kernel_names=['blocklist1', 'blocklist2', 'common'])

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.UpdateAudioCodecKernelNames(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)
    self.assertEqual(
        'Allowlist and blocklist should be disjoint, and the '
        "overlapped part: {'common'}.", ex.exception.detail)

  @mock.patch('cros.factory.hwid.service.appengine.git_util.CreateCL')
  @mock.patch('cros.factory.hwid.service.appengine.git_util.GetCurrentBranch')
  @mock.patch(
      'cros.factory.hwid.service.appengine.git_util.GetGerritCredentials')
  def testUpdateAudioCodecKernelNames_CreateCL(
      self, mock_gerrit_cred, mock_get_curr_branch, mock_create_cl):
    del mock_get_curr_branch
    # Arrange.
    mock_gerrit_cred.return_value = ('unused_service_account', 'unused_token')

    # Act.
    # Update blocklist of audio codec kernel names.
    blocklist_req = hwid_api_messages_pb2.UpdateAudioCodecKernelNamesRequest(
        allowlisted_kernel_names=['allowed1', 'allowed2', 'allowed3'],
        blocklisted_kernel_names=['blocked3', 'blocked2', 'blocked1'])
    self._ss_helper.UpdateAudioCodecKernelNames(blocklist_req)

    # Assert.
    unused_args, kwargs = mock_create_cl.call_args
    new_files = kwargs['new_files']
    self.assertEqual(1, len(new_files))
    file_path, unused_mode, file_content = new_files[0]
    self.assertEqual('vars/namespace.prefix.yaml', file_path)
    self.assertEqual(
        'namespace.prefix.allowlist: '
        '\'["allowed1", "allowed2", "allowed3"]\'\n'
        'namespace.prefix.blocklist: '
        '\'["blocked1", "blocked2", "blocked3"]\'\n', file_content)
    self.assertCountEqual(['cc1@notgoogle.com'], kwargs['cc'])
    self.assertEqual('avl-metadata-topic', kwargs['topic'])
    self.assertTrue(kwargs['auto_submit'])
    self.assertTrue(kwargs['rubber_stamper'])

  @mock.patch('cros.factory.hwid.service.appengine.git_util.CreateCL')
  @mock.patch('cros.factory.hwid.service.appengine.git_util.GetCurrentBranch')
  @mock.patch(
      'cros.factory.hwid.service.appengine.git_util.GetGerritCredentials')
  def testAnalyzeHWIDDBEditableSection_ReportAVLSkippableComps(
      self, mock_gerrit_cred, mock_get_curr_branch, mock_create_cl):
    # Arrange.
    del mock_get_curr_branch
    del mock_create_cl
    mock_gerrit_cred.return_value = ('unused_service_account', 'unused_token')
    project = 'CHROMEBOOK'
    old_db_data = file_utils.ReadFile(_HWID_V3_GOLDEN_WITH_AUDIO_CODEC)
    new_db_data = _ActionHelperCls.RemoveHeader(old_db_data)
    # Config repo and action.
    self._ConfigLiveHWIDRepo(project, 3, old_db_data)
    action = self._CreateFakeHWIDBAction(project, old_db_data)
    self._modules.ConfigHWID(project, '3', old_db_data, hwid_action=action)
    # Update blocklist of audio codec kernel names.
    blocklist_req = hwid_api_messages_pb2.UpdateAudioCodecKernelNamesRequest(
        blocklisted_kernel_names=['skippable_kernel_names'])
    self._ss_helper.UpdateAudioCodecKernelNames(blocklist_req)

    # Act.
    analysis_resp = _AnalyzeHWIDDBEditableSection(self._ss_helper, project,
                                                  new_db_data)

    # Assert.
    skippable_comps = [
        comp_analysis_msg for comp_analysis_msg in
        analysis_resp.analysis_report.component_infos.values()
        if comp_analysis_msg.skip_avl_check
    ]
    self.assertCountEqual([
        _ComponentInfoMsg(
            component_class='audio_codec',
            original_name='avl_skipped_comp',
            original_status='supported',
            is_newly_added=False,
            avl_info=None,
            has_avl=False,
            seq_no=5,
            diff_prev=_DiffStatusMsg(
                unchanged=True, prev_comp_name='avl_skipped_comp',
                prev_support_status='supported',
                prev_probe_value_alignment_status=(
                    _PVAlignmentStatusMsg.NO_PROBE_INFO),
                prev_support_status_case=_SupportStatusCase.SUPPORTED),
            probe_value_alignment_status=_PVAlignmentStatusMsg.NO_PROBE_INFO,
            support_status_case=_SupportStatusCase.SUPPORTED,
            skip_avl_check=True,
        )
    ], skippable_comps)

  @classmethod
  def _CreateFakeHWIDBAction(cls, project: str, raw_db: str):
    return hwid_v3_action.HWIDV3Action(
        hwid_preproc_data.HWIDV3PreprocData(project, raw_db, raw_db,
                                            'TEST-COMMIT-ID'))

  @classmethod
  def _CreateBundleRecord(cls, projects):
    firmware_records = []
    for proj in projects:
      firmware_records.append(
          _FirmwareRecord(
              model=proj, firmware_keys=[
                  _FirmwareRecord.FirmwareKeys(key_recovery='key_recovery',
                                               key_root='key_root',
                                               key_id='default')
              ], ro_fp_firmware=[
                  _FirmwareRecord.FirmwareInfo(hash='hash_string',
                                               version='fp_firmware_1'),
                  _FirmwareRecord.FirmwareInfo(hash='hash_string',
                                               version='fp_firmware_2'),
              ], ro_main_firmware=[
                  _FirmwareRecord.FirmwareInfo(hash='hash_string',
                                               version='Google_Proj.1111.1.1')
              ]))

    return _FactoryBundleRecord(board='board', firmware_signer='BoardMPKeys-V1',
                                firmware_records=firmware_records)

  def _ConfigLiveHWIDRepo(self, project, version, db_contents,
                          commit_id='TEST-COMMIT-ID'):
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    hwid_db_metadata = hwid_repo.HWIDDBMetadata(project, project, version,
                                                f'v{version}/{project}')
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = hwid_db_metadata
    live_hwid_repo.ListHWIDDBMetadata.return_value = [hwid_db_metadata]
    live_hwid_repo.LoadHWIDDBByName.return_value = db_contents
    live_hwid_repo.LoadHWIDDB.return_value = db_contents
    live_hwid_repo.hwid_db_commit_id = commit_id

  def _ConfigHWIDRepoManager(self, project, version, db_contents,
                             db_contents_internal, commit_id='TEST-COMMIT-ID'):
    hwid_db_metadata = hwid_repo.HWIDDBMetadata(project, project, version,
                                                f'v{version}/{project}')
    self._mock_hwid_repo_manager.GetRepoFileContents.return_value = (
        hwid_repo.RepoFileContents(commit_id,
                                   [db_contents, db_contents_internal]))
    self._mock_hwid_repo_manager.GetHWIDDBMetadata.return_value = (
        hwid_db_metadata)


if __name__ == '__main__':
  unittest.main()
