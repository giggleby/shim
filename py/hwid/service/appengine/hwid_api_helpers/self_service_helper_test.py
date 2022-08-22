# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
from typing import Optional, Sequence
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers import v3_self_service_helper as v3_action_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import self_service_helper as ss_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import builder as v3_builder
from cros.factory.hwid.v3 import database
from cros.factory.probe_info_service.app_engine import protorpc_utils

_ErrorMsg = (
    hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.Error)
_ErrorCodeMsg = (
    hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.ErrorCode)
_AnalysisReportMsg = hwid_api_messages_pb2.HwidDbEditableSectionAnalysisReport
_DiffStatus = hwid_action.DBHWIDComponentDiffStatus
_DiffStatusMsg = hwid_api_messages_pb2.DiffStatus
_ComponentInfoMsg = _AnalysisReportMsg.ComponentInfo
_PVAlignmentStatus = hwid_action.DBHWIDPVAlignmentStatus
_PVAlignmentStatusMsg = hwid_api_messages_pb2.ProbeValueAlignmentStatus.Case
_AvlInfoMsg = hwid_api_messages_pb2.AvlInfo
_HWIDSectionChangeMsg = _AnalysisReportMsg.HwidSectionChange
_HWIDSectionChangeStatusMsg = _HWIDSectionChangeMsg.ChangeStatus
_FactoryBundleRecord = hwid_api_messages_pb2.FactoryBundleRecord
_FirmwareRecord = _FactoryBundleRecord.FirmwareRecord


class SelfServiceHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._mock_hwid_repo_manager = mock.create_autospec(
        hwid_repo.HWIDRepoManager, instance=True)
    self._ss_helper = ss_helper.SelfServiceHelper(
        self._modules.fake_hwid_action_manager, self._mock_hwid_repo_manager,
        self._modules.fake_hwid_db_data_manager,
        self._modules.fake_avl_converter_manager)

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
        project='proj', new_hwid_db_editable_section='db data after change 1',
        validation_token='validation-token-value-1')

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
                                _PVAlignmentStatus.NO_PROBE_INFO)),
                        link_avl=False, probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO)),
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
                                _PVAlignmentStatus.NO_PROBE_INFO)),
                        link_avl=False, probe_value_alignment_status=(
                            _PVAlignmentStatus.ALIGNED)),
                'comp3':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_name3',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=True,
                        diff_prev=None, link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO)),
            }))

    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='proj', new_hwid_db_editable_section='db data after change',
        validation_token='validation-token-value-1')
    resp = self._ss_helper.CreateHWIDDBEditableSectionChangeCL(req)

    self.assertEqual(resp.cl_number, 123)
    self.assertEqual(
        {
            'comp1':
                _ComponentInfoMsg(
                    component_class="comp_cls1", original_name="comp_name1",
                    original_status="unqualified", is_newly_added=False,
                    seq_no=2, null_values=False, diff_prev=_DiffStatusMsg(
                        unchanged=True, name_changed=False,
                        support_status_changed=False, values_changed=False,
                        prev_comp_name="comp_name1",
                        prev_support_status="unqualified",
                        probe_value_alignment_status_changed=False,
                        prev_probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                    probe_value_alignment_status=(
                        _PVAlignmentStatusMsg.NO_PROBE_INFO)),
            'comp2':
                _ComponentInfoMsg(
                    component_class="comp_cls2",
                    original_name="comp_cls2_111_222#9",
                    original_status="unqualified", is_newly_added=True,
                    avl_info=_AvlInfoMsg(
                        cid=111,
                        qid=222,
                    ), has_avl=True, seq_no=1,
                    component_name_with_correct_seq_no="comp_cls2_111_222#1",
                    null_values=False, diff_prev=_DiffStatusMsg(
                        unchanged=False, name_changed=True,
                        support_status_changed=False, values_changed=False,
                        prev_comp_name="old_comp_name",
                        prev_support_status="unqualified",
                        probe_value_alignment_status_changed=True,
                        prev_probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                    probe_value_alignment_status=(
                        _PVAlignmentStatusMsg.ALIGNED)),
            'comp3':
                _ComponentInfoMsg(
                    component_class="comp_cls2", original_name="comp_name3",
                    original_status="unqualified", is_newly_added=True,
                    seq_no=2, null_values=True, probe_value_alignment_status=(
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
        project='proj', new_hwid_db_editable_section='db data after change',
        validation_token=token_that_will_become_expired)

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
      bot_commit: Optional[bool] = None) -> hwid_repo.HWIDDBCLInfo:
    change_id = str(cl_number)
    if mergeable is None:
      mergeable = status == hwid_repo.HWIDDBCLStatus.NEW
    created_time = created_time or datetime.datetime.utcnow()
    comment_threads = comment_threads or []
    return hwid_repo.HWIDDBCLInfo(change_id, cl_number, subject, status,
                                  review_status, mergeable, created_time,
                                  comment_threads, bot_commit)

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
        created_time=long_time_ago)
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
        created_time=long_time_ago)
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
        created_time=now)
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
        bot_commit=True)
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
                            _PVAlignmentStatus.NO_PROBE_INFO)),
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
                            _PVAlignmentStatus.NO_PROBE_INFO)),
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
                        original_status='unqualified', is_newly_added=False,
                        has_avl=False, seq_no=2, null_values=True,
                        probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                'comp2':
                    _ComponentInfoMsg(
                        component_class='comp_cls2',
                        original_name='comp_cls2_111_222#9',
                        original_status='unqualified',
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
                              _PVAlignmentStatus.NO_PROBE_INFO)),
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
                              _PVAlignmentStatus.NO_PROBE_INFO)),
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
                            original_status='unqualified', is_newly_added=False,
                            avl_info=None, has_avl=False, seq_no=2,
                            component_name_with_correct_seq_no=None,
                            diff_prev=None, null_values=True,
                            probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                    'comp2':
                        _ComponentInfoMsg(
                            component_class='comp_cls2',
                            original_name='comp_cls2_111_222#9',
                            original_status='unqualified',
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
                                _PVAlignmentStatus.NO_PROBE_INFO)),
                        link_avl=False, probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO)),
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
                                _PVAlignmentStatus.NO_PROBE_INFO)),
                        link_avl=False, probe_value_alignment_status=(
                            _PVAlignmentStatus.ALIGNED)),
                'comp3':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        comp_cls='comp_cls2', comp_name='comp_name3',
                        support_status='unqualified', is_newly_added=True,
                        comp_name_info=None, seq_no=2,
                        comp_name_with_correct_seq_no=None, null_values=True,
                        diff_prev=None, link_avl=False,
                        probe_value_alignment_status=(
                            _PVAlignmentStatus.NO_PROBE_INFO)),
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
                        original_status='unqualified', is_newly_added=False,
                        has_avl=False, seq_no=2, diff_prev=_DiffStatusMsg(
                            unchanged=True, name_changed=False,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='comp_name1',
                            prev_support_status='unqualified',
                            probe_value_alignment_status_changed=False,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                        probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                'comp2':
                    _ComponentInfoMsg(
                        component_class='comp_cls2',
                        original_name='comp_cls2_111_222#9',
                        original_status='unqualified', is_newly_added=True,
                        has_avl=True, avl_info=_AvlInfoMsg(cid=111, qid=222),
                        seq_no=1, component_name_with_correct_seq_no=(
                            'comp_cls2_111_222#1'),
                        diff_prev=_DiffStatusMsg(
                            unchanged=False, name_changed=True,
                            support_status_changed=False, values_changed=False,
                            prev_comp_name='old_comp_name',
                            prev_support_status='unqualified',
                            probe_value_alignment_status_changed=True,
                            prev_probe_value_alignment_status=(
                                _PVAlignmentStatusMsg.NO_PROBE_INFO)),
                        probe_value_alignment_status=(
                            _PVAlignmentStatusMsg.ALIGNED)),
                'comp3':
                    _ComponentInfoMsg(
                        component_class='comp_cls2', original_name='comp_name3',
                        original_status='unqualified', is_newly_added=True,
                        has_avl=False, seq_no=2, null_values=True,
                        probe_value_alignment_status=(
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
    action_helper_cls = v3_action_helper.HWIDV3SelfServiceActionHelper
    expected_db_content = action_helper_cls.RemoveHeader(db_content)

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

  @mock.patch('cros.factory.hwid.service.appengine.hwid_action_helpers'
              '.v3_self_service_helper.HWIDV3SelfServiceActionHelper'
              '.RemoveHeader')
  def testCreateHWIDDBFirmwareInfoUpdateCL_Succeed(self, remove_header):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock.MagicMock(spec=database.WritableDatabase)
    remove_header.return_value = 'db data'
    self._modules.ConfigHWID('PROJ', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest(
        bundle_record=self._CreateBundleRecord(['proj']))
    resp = self._ss_helper.CreateHWIDDBFirmwareInfoUpdateCL(req)

    self.assertIn('PROJ', resp.commits)
    self.assertEqual(resp.commits['PROJ'].cl_number, 123)
    self.assertEqual(resp.commits['PROJ'].new_hwid_db_contents, 'db data')

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

  @mock.patch('cros.factory.hwid.service.appengine.hwid_action_helpers'
              '.v3_self_service_helper.HWIDV3SelfServiceActionHelper'
              '.RemoveHeader')
  def testSetFirmwareInfoSupportStatus_Succeed(self, remove_header):
    self._ConfigLiveHWIDRepo('PROJ1', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.return_value = 123
    mock_db = mock.MagicMock(spec=database.WritableDatabase)
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock_db
    action.GetComponents.return_value = self._CreateFirmwareComponents()
    remove_header.return_value = 'db data'
    self._modules.ConfigHWID('PROJ1', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='proj1', version_string='google_proj1.1111.1.1')
    resp = self._ss_helper.SetFirmwareInfoSupportStatus(req)

    self.assertEqual(mock_db.SetComponentStatus.call_count, 2)
    mock_db.SetComponentStatus.assert_has_calls([
        mock.call('ro_main_firmware', 'ro_main_firmware_1', 'supported'),
        mock.call('firmware_keys', 'firmware_keys_1', 'supported')
    ], any_order=True)
    self.assertEqual(resp.commit.cl_number, 123)
    self.assertEqual(resp.commit.new_hwid_db_contents, 'db data')

  def testSetFirmwareInfoSupportStatus_ProjectNotFound(self):
    self._ConfigLiveHWIDRepo('PROJ', 3, 'db data')

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='notproj')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.SetFirmwareInfoSupportStatus(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testSetFirmwareInfoSupportStatus_NoChange(self):
    self._ConfigLiveHWIDRepo('PROJ1', 3, 'db data')
    mock_db = mock.MagicMock(spec=database.WritableDatabase)
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock_db
    action.GetComponents.return_value = self._CreateFirmwareComponents()
    self._modules.ConfigHWID('PROJ1', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='proj1', version_string='google_proj1.2222.2.2')
    resp = self._ss_helper.SetFirmwareInfoSupportStatus(req)

    mock_db.SetComponentStatus.assert_not_called()
    self.assertEqual(
        resp, hwid_api_messages_pb2.SetFirmwareInfoSupportStatusResponse())

  def testSetFirmwareInfoSupportStatus_InternalError(self):
    self._ConfigLiveHWIDRepo('PROJ1', 3, 'db data')
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.CommitHWIDDB.side_effect = [hwid_repo.HWIDRepoError]
    mock_db = mock.MagicMock(spec=database.WritableDatabase)
    action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    action.GetDBV3.return_value = mock_db
    action.GetComponents.return_value = self._CreateFirmwareComponents()
    self._modules.ConfigHWID('PROJ1', '3', 'db data', hwid_action=action)

    req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
        project='proj1', version_string='google_proj1.1111.1.1')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self._ss_helper.SetFirmwareInfoSupportStatus(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INTERNAL)

  @classmethod
  def _CreateFirmwareComponents(cls):
    return {
        'ro_main_firmware': {
            'ro_main_firmware_1':
                database.ComponentInfo(
                    values={'version': 'Google_Proj1.1111.1.1'},
                    status='unsupported', bundle_uuids=['uuid1']),
            'ro_main_firmware_local_build':
                database.ComponentInfo(
                    values={'version': 'Google_Proj1.2222.2.2_2022_08_22_1144'},
                    status='unsupported', bundle_uuids=['uuid2'])
        },
        'firmware_keys': {
            'firmware_keys_1':
                database.ComponentInfo(values={}, status='unsupported',
                                       bundle_uuids=['uuid1'])
        }
    }

  @classmethod
  def _CreateBundleRecord(cls, projects):
    firmware_records = []
    for proj in projects:
      firmware_records.append(
          _FirmwareRecord(
              model=proj, firmware_keys=_FirmwareRecord.FirmwareKeys(
                  key_recovery='key_recovery', key_root='key_root'),
              ro_main_firmware=_FirmwareRecord.FirmwareInfo(
                  hash='hash_string', version='1111.1.1')))

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
