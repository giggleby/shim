# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
from typing import Optional, Sequence
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_api_helpers import self_service_helper as ss_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.probe_info_service.app_engine import protorpc_utils


_ErrorMsg = (
    hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.Error)
_ErrorCodeMsg = (
    hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.ErrorCode)
_AnalysisReportMsg = hwid_api_messages_pb2.HwidDbEditableSectionAnalysisReport
_DiffStatus = hwid_action.DBHWIDComponentDiffStatus
_DiffStatusMsg = hwid_api_messages_pb2.DiffStatus
_ComponentInfoMsg = _AnalysisReportMsg.ComponentInfo


class SelfServiceHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._mock_hwid_repo_manager = mock.create_autospec(
        hwid_repo.HWIDRepoManager, instance=True)
    self._ss_helper = ss_helper.SelfServiceHelper(
        self._modules.fake_hwid_action_manager, self._mock_hwid_repo_manager,
        self._modules.fake_hwid_db_data_manager)

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
        hwid_action.DBEditableSectionAnalysisReport('validation-token-value-2',
                                                    'db data after change 2',
                                                    [], [], [], {}))

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
        hwid_action.DBEditableSectionAnalysisReport('validation-token-value-1',
                                                    'db data after change 1',
                                                    [], [], [], {}))

    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='proj', new_hwid_db_editable_section='db data after change',
        validation_token='validation-token-value-1')
    resp = self._ss_helper.CreateHWIDDBEditableSectionChangeCL(req)

    self.assertEqual(resp.cl_number, 123)

  def testCreateHWIDDBEditableSectionChangeCL_ValidationExpired(self):
    """Test that the validation token becomes expired once the live HWID repo is
    updated."""

    def CreateMockHWIDAction(hwid_data):
      # Configure the mocked HWIDAction so that it returns the change
      # fingerprint based on the contents of the HWID DB.
      action = mock.create_autospec(hwid_action.HWIDAction, instance=True)
      action.AnalyzeDraftDBEditableSection.return_value = (
          hwid_action.DBEditableSectionAnalysisReport(hwid_data.raw_db, '', [],
                                                      [], [], {}))
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
      messages: Optional[Sequence[hwid_repo.HWIDDBCLMessage]] = None,
      mergeable: Optional[bool] = None,
      created_time: Optional[datetime.datetime] = None
  ) -> hwid_repo.HWIDDBCLInfo:
    change_id = str(cl_number)
    if mergeable is None:
      mergeable = status == hwid_repo.HWIDDBCLStatus.NEW
    created_time = created_time or datetime.datetime.utcnow()
    messages = messages or []
    return hwid_repo.HWIDDBCLInfo(change_id, cl_number, status, messages,
                                  mergeable, created_time)

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
                4, hwid_repo.HWIDDBCLStatus.NEW, messages=[
                    hwid_repo.HWIDDBCLMessage('msg1', 'user1@email'),
                    hwid_repo.HWIDDBCLMessage('msg2', 'user2@email'),
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
    cl_status.comments.add(email='user2@email', message='msg2')
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
            'fingerprint', 'new_db_content', [
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
            'fingerprint', 'new_db_content', [], [], [
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
                        'comp_cls1', 'comp_name1', 'unqualified', False, None,
                        2, None, True, None),
                'comp2':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        'comp_cls2', 'comp_cls2_111_222#9', 'unqualified', True,
                        (111, 222), 1, 'comp_cls2_111_222#1', False, None),
            }))

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
                        component_class='comp_cls1',
                        original_name='comp_name1',
                        original_status='unqualified',
                        is_newly_added=False,
                        has_avl=False,
                        seq_no=2,
                        null_values=True,
                    ),
                'comp2':
                    _ComponentInfoMsg(
                        component_class='comp_cls2',
                        original_name='comp_cls2_111_222#9',
                        original_status='unqualified',
                        is_newly_added=True,
                        has_avl=True,
                        avl_info=hwid_api_messages_pb2.AvlInfo(
                            cid=111, qid=222),
                        seq_no=1,
                        component_name_with_correct_seq_no=(
                            'comp_cls2_111_222#1'),
                    ),
            }), validation_token='fingerprint')
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
    self._ConfigHWIDRepoManager('PROJ', 3, 'db data ver 1')
    req1 = hwid_api_messages_pb2.GetHwidBundleResourceInfoRequest(
        project='proj')
    resp1 = self._ss_helper.GetHWIDBundleResourceInfo(req1)
    self._ConfigHWIDRepoManager('PROJ', 3, 'db data ver 2')
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
                          'comp_cls1', 'comp_name1', 'unqualified', False, None,
                          2, None, True, None),
                  'comp2':
                      hwid_action.DBHWIDComponentAnalysisResult(
                          'comp_cls2', 'comp_cls2_111_222#9', 'unqualified',
                          False,
                          (111, 222), 1, 'comp_cls2_111_222#1', True, None),
              }))
      return action

    self._modules.ConfigHWID('PROJ', '3', 'db data',
                             hwid_action_factory=CreateMockHWIDAction)
    self._ConfigHWIDRepoManager('PROJ', 3, 'db data')
    req = hwid_api_messages_pb2.GetHwidBundleResourceInfoRequest(project='proj')
    resp = self._ss_helper.GetHWIDBundleResourceInfo(req)
    # TODO(b/209362238): add selected components which require the AVL
    # information.
    expected_resp = hwid_api_messages_pb2.GetHwidBundleResourceInfoResponse(
        bundle_creation_token='fingerprint of db data')
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
            'fingerprint', 'new_db_content', [], [], [], {
                'comp1':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        'comp_cls1', 'comp_name1', 'unqualified', False, None,
                        2, None, False,
                        _DiffStatus(unchanged=True, name_changed=False,
                                    support_status_changed=False,
                                    values_changed=False,
                                    prev_comp_name='comp_name1',
                                    prev_support_status='unqualified')),
                'comp2':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        'comp_cls2', 'comp_cls2_111_222#9', 'unqualified', True,
                        (111, 222), 1, 'comp_cls2_111_222#1', False,
                        _DiffStatus(unchanged=False, name_changed=True,
                                    support_status_changed=False,
                                    values_changed=False,
                                    prev_comp_name='old_comp_name',
                                    prev_support_status='unqualified')),
                'comp3':
                    hwid_action.DBHWIDComponentAnalysisResult(
                        'comp_cls2', 'comp_name3', 'unqualified', True, None, 2,
                        None, True, None),
            }))

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
                            prev_support_status='unqualified')),
                'comp2':
                    _ComponentInfoMsg(
                        component_class='comp_cls2',
                        original_name='comp_cls2_111_222#9',
                        original_status='unqualified', is_newly_added=True,
                        has_avl=True, avl_info=hwid_api_messages_pb2.AvlInfo(
                            cid=111, qid=222), seq_no=1,
                        component_name_with_correct_seq_no=(
                            'comp_cls2_111_222#1'), diff_prev=_DiffStatusMsg(
                                unchanged=False, name_changed=True,
                                support_status_changed=False,
                                values_changed=False,
                                prev_comp_name='old_comp_name',
                                prev_support_status='unqualified')),
                'comp3':
                    _ComponentInfoMsg(
                        component_class='comp_cls2', original_name='comp_name3',
                        original_status='unqualified', is_newly_added=True,
                        has_avl=False, seq_no=2, null_values=True),
            }), validation_token='fingerprint')

    self.assertEqual(resp, expected_resp)

  def _ConfigLiveHWIDRepo(self, project, version, db_contents):
    live_hwid_repo = self._mock_hwid_repo_manager.GetLiveHWIDRepo.return_value
    hwid_db_metadata = hwid_repo.HWIDDBMetadata(project, project, version,
                                                f'v{version}/{project}')
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = hwid_db_metadata
    live_hwid_repo.ListHWIDDBMetadata.return_value = [hwid_db_metadata]
    live_hwid_repo.LoadHWIDDBByName.return_value = db_contents
    live_hwid_repo.LoadHWIDDB.return_value = db_contents

  def _ConfigHWIDRepoManager(self, project, version, db_contents):
    hwid_db_metadata = hwid_repo.HWIDDBMetadata(project, project, version,
                                                f'v{version}/{project}')
    self._mock_hwid_repo_manager.GetFileContent.return_value = db_contents
    self._mock_hwid_repo_manager.GetHWIDDBMetadata.return_value = (
        hwid_db_metadata)


if __name__ == '__main__':
  unittest.main()
