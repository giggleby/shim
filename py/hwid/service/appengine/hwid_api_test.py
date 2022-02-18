#!/usr/bin/env python3
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for cros.hwid.service.appengine.hwid_api"""

import os.path
import unittest
from unittest import mock

from cros.chromeoshwid import update_checksum

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_api
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.utils import file_utils


TEST_MODEL = 'FOO'
TEST_HWID = 'Foo'
TEST_HWID_CONTENT = 'prefix\nchecksum: 1234\nsuffix\n'
EXPECTED_REPLACE_RESULT = update_checksum.ReplaceChecksum(TEST_HWID_CONTENT)
GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata', 'v3-golden.yaml')
GOLDEN_HWIDV3_CONTENT = file_utils.ReadFile(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'testdata',
        'v3-golden.yaml'))
HWIDV3_CONTENT_SCHEMA_ERROR_CHANGE = file_utils.ReadFile(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'testdata',
        'v3-schema-error-change.yaml'))

ComponentMsg = hwid_api_messages_pb2.Component
StatusMsg = hwid_api_messages_pb2.Status


# pylint: disable=protected-access
class ProtoRPCServiceTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    self._modules = test_utils.FakeModuleCollection()

    patcher = mock.patch('__main__.hwid_api._hwid_action_manager',
                         new=self._modules.fake_hwid_action_manager)
    self.fake_hwid_action_manager = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.hwid_api._decoder_data_manager',
                         new=self._modules.fake_decoder_data_manager)
    self.fake_decoder_data_manager = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.hwid_api._goldeneye_memcache_adapter',
                         new=self._modules.fake_goldeneye_memcache)
    self.fake_goldeneye_memcache_adapter = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.hwid_api._hwid_repo_manager')
    self.patch_hwid_repo_manager = patcher.start()
    hwid_live_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    hwid_live_repo.ListHWIDDBMetadata.return_value = []
    hwid_live_repo.GetHWIDDBMetadataByName.side_effect = ValueError
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.hwid_api._hwid_validator')
    self.patch_hwid_validator = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.hwid_api._hwid_db_data_manager',
                         new=self._modules.fake_hwid_db_data_manager)
    self.fake_hwid_db_data_manager = patcher.start()
    self.addCleanup(patcher.stop)

    self.service = hwid_api.ProtoRPCService()

  def tearDown(self):
    super().tearDown()

    self._modules.ClearAll()

  def testGetProjects(self):
    self._modules.ConfigHWID('ALPHA', '2', 'db1')
    self._modules.ConfigHWID('BRAVO', '3', 'db2')
    self._modules.ConfigHWID('CHARLIE', '3', 'db3')

    req = hwid_api_messages_pb2.ProjectsRequest()
    msg = self.service.GetProjects(req)

    self.assertEqual(
        hwid_api_messages_pb2.ProjectsResponse(
            status=StatusMsg.SUCCESS,
            projects=sorted(['ALPHA', 'BRAVO', 'CHARLIE'])), msg)

  def testGetBom_InternalError(self):
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMEntry.return_value = {}

      req = hwid_api_messages_pb2.BomRequest(hwid=TEST_HWID)
      msg = self.service.GetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BomResponse(error='Internal error',
                                          status=StatusMsg.SERVER_ERROR), msg)

  def testGetBom_Success(self):
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMEntry.return_value = {
          TEST_HWID:
              bc_helper.BOMEntry([
                  ComponentMsg(name='qux', component_class='baz'),
              ], [], '', '', StatusMsg.SUCCESS)
      }

      req = hwid_api_messages_pb2.BomRequest(hwid=TEST_HWID)
      msg = self.service.GetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BomResponse(
            status=StatusMsg.SUCCESS, components=[
                ComponentMsg(name='qux', component_class='baz'),
            ]), msg)

  def testGetBom_WithError(self):
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMEntry.return_value = {
          TEST_HWID:
              bc_helper.BOMEntry([], [], '', 'bad hwid', StatusMsg.BAD_REQUEST)
      }

      req = hwid_api_messages_pb2.BomRequest(hwid=TEST_HWID)
      msg = self.service.GetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BomResponse(status=StatusMsg.BAD_REQUEST,
                                          error='bad hwid'), msg)

  def testBatchGetBom(self):
    hwid1 = 'TEST HWID 1'
    hwid2 = 'TEST HWID 2'
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMEntry.return_value = {
          hwid1:
              bc_helper.BOMEntry([
                  ComponentMsg(name='qux1', component_class='baz1'),
                  ComponentMsg(name='rox1', component_class='baz1'),
              ], [], '', '', StatusMsg.SUCCESS),
          hwid2:
              bc_helper.BOMEntry([
                  ComponentMsg(name='qux2', component_class='baz2'),
                  ComponentMsg(name='rox2', component_class='baz2'),
              ], [], '', '', StatusMsg.SUCCESS),
      }

      req = hwid_api_messages_pb2.BatchGetBomRequest(hwid=[hwid1, hwid2])
      msg = self.service.BatchGetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BatchGetBomResponse(
            boms={
                hwid1:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SUCCESS, components=[
                            ComponentMsg(name='qux1', component_class='baz1'),
                            ComponentMsg(name='rox1', component_class='baz1'),
                        ]),
                hwid2:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SUCCESS, components=[
                            ComponentMsg(name='qux2', component_class='baz2'),
                            ComponentMsg(name='rox2', component_class='baz2'),
                        ]),
            }, status=StatusMsg.SUCCESS), msg)

  def testBatchGetBom_WithError(self):
    hwid1 = 'TEST HWID 1'
    hwid2 = 'TEST HWID 2'
    hwid3 = 'TEST HWID 3'
    hwid4 = 'TEST HWID 4'
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMEntry.return_value = {
          hwid1:
              bc_helper.BOMEntry([], [], '', 'value error',
                                 StatusMsg.BAD_REQUEST),
          hwid2:
              bc_helper.BOMEntry([], [], '', "'Invalid key'",
                                 StatusMsg.NOT_FOUND),
          hwid3:
              bc_helper.BOMEntry([], [], '', 'index error',
                                 StatusMsg.SERVER_ERROR),
          hwid4:
              bc_helper.BOMEntry([
                  ComponentMsg(name='qux', component_class='baz'),
                  ComponentMsg(name='rox', component_class='baz'),
                  ComponentMsg(name='bar', component_class='foo'),
              ], [], '', '', StatusMsg.SUCCESS),
      }

      req = hwid_api_messages_pb2.BatchGetBomRequest(hwid=[hwid1, hwid2])
      msg = self.service.BatchGetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BatchGetBomResponse(
            boms={
                hwid1:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.BAD_REQUEST, error='value error'),
                hwid2:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.NOT_FOUND, error="'Invalid key'"),
                hwid3:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SERVER_ERROR, error='index error'),
                hwid4:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SUCCESS, components=[
                            ComponentMsg(name='qux', component_class='baz'),
                            ComponentMsg(name='rox', component_class='baz'),
                            ComponentMsg(name='bar', component_class='foo'),
                        ]),
            }, status=StatusMsg.BAD_REQUEST, error='value error'), msg)

  def testGetHwids_ProjectNotFound(self):
    # There's no project in the backend datastore by default.

    req = hwid_api_messages_pb2.HwidsRequest(project='no_such_project')
    msg = self.service.GetHwids(req)

    self.assertEqual(msg.status, StatusMsg.NOT_FOUND)

  def testGetHwids_InternalError(self):
    self._modules.ConfigHWID('FOO', '3', 'db data', None)

    req = hwid_api_messages_pb2.HwidsRequest(project='foo')
    msg = self.service.GetHwids(req)

    self.assertEqual(msg.status, StatusMsg.SERVER_ERROR)

  def testGetHwids_BadRequestError(self):
    hwid_action_inst = hwid_action.HWIDAction()
    with mock.patch.object(hwid_action_inst, '_EnumerateHWIDs') as method:
      method.return_value = ['alfa', 'bravo', 'charlie']
      self._modules.ConfigHWID('FOO', '3', 'db data', hwid_action_inst)

      req = hwid_api_messages_pb2.HwidsRequest(project='foo',
                                               with_classes=['foo', 'bar'],
                                               without_classes=['bar', 'baz'])
      msg = self.service.GetHwids(req)

    self.assertEqual(msg.status, StatusMsg.BAD_REQUEST)

  def testGetHwids_Success(self):
    hwid_action_inst = hwid_action.HWIDAction()
    with mock.patch.object(hwid_action_inst, '_EnumerateHWIDs') as method:
      method.return_value = ['alfa', 'bravo', 'charlie']
      self._modules.ConfigHWID('FOO', '3', 'db data', hwid_action_inst)

      req = hwid_api_messages_pb2.HwidsRequest(project='foo')
      msg = self.service.GetHwids(req)

    self.assertEqual(
        hwid_api_messages_pb2.HwidsResponse(
            status=StatusMsg.SUCCESS, hwids=['alfa', 'bravo', 'charlie']), msg)

  def testGetComponentClasses_ProjectNotFoundError(self):
    # There's no project in the backend datastore by default.

    req = hwid_api_messages_pb2.ComponentClassesRequest(project='nosuchproject')
    msg = self.service.GetComponentClasses(req)

    self.assertEqual(msg.status, StatusMsg.NOT_FOUND)

  def testGetComponentClasses_ProjectUnavailableError(self):
    self._modules.ConfigHWID('FOO', '3', 'db data', None)

    req = hwid_api_messages_pb2.ComponentClassesRequest(project='foo')
    msg = self.service.GetComponentClasses(req)

    self.assertEqual(msg.status, StatusMsg.SERVER_ERROR)

  def testGetComponentClasses_Success(self):
    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponentClasses.return_value = ['dram', 'storage']
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentClassesRequest(project='foo')
    msg = self.service.GetComponentClasses(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(list(msg.component_classes), ['dram', 'storage'])

  def testGetComponents_ProjectNotFoundError(self):
    # There's no project in the backend datastore by default.

    req = hwid_api_messages_pb2.ComponentsRequest(project='nosuchproject')
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.NOT_FOUND)

  def testGetComponents_ProjectUnavailableError(self):
    self._modules.ConfigHWID('FOO', '3', 'db data', None)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo')
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SERVER_ERROR)

  def testGetComponents_SuccessWithAllComponentClasses(self):
    sampled_components = {
        'dram': ['dram1', 'dram2'],
        'storage': ['storage1', 'storage2'],
    }

    def FakeGetComponents(with_classes=None):
      return {
          k: v
          for k, v in sampled_components.items()
          if with_classes is None or k in with_classes
      }

    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponents.side_effect = FakeGetComponents
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo')
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(
        list(msg.components), [
            ComponentMsg(component_class='dram', name='dram1'),
            ComponentMsg(component_class='dram', name='dram2'),
            ComponentMsg(component_class='storage', name='storage1'),
            ComponentMsg(component_class='storage', name='storage2'),
        ])

  def testGetComponents_SuccessWithLimitedComponentClasses(self):
    sampled_components = {
        'dram': ['dram1', 'dram2'],
        'storage': ['storage1', 'storage2'],
    }

    def FakeGetComponents(with_classes=None):
      return {
          k: v
          for k, v in sampled_components.items()
          if with_classes is None or k in with_classes
      }

    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponents.side_effect = FakeGetComponents
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo',
                                                  with_classes=['dram'])
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(
        list(msg.components), [
            ComponentMsg(component_class='dram', name='dram1'),
            ComponentMsg(component_class='dram', name='dram2'),
        ])

  def testValidateConfig(self):
    req = hwid_api_messages_pb2.ValidateConfigRequest(
        hwid_config_contents='test')
    msg = self.service.ValidateConfig(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigResponse(status=StatusMsg.SUCCESS),
        msg)

  def testValidateConfigErrors(self):
    self.patch_hwid_validator.Validate.side_effect = (
        hwid_validator.ValidationError([
            hwid_validator.Error(hwid_validator.ErrorCode.CONTENTS_ERROR, 'msg')
        ]))

    req = hwid_api_messages_pb2.ValidateConfigRequest(
        hwid_config_contents='test')
    msg = self.service.ValidateConfig(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigResponse(
            status=StatusMsg.BAD_REQUEST, error_message='msg'), msg)

  def testValidateConfigAndUpdateChecksum(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {})

    req = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumRequest(
        hwid_config_contents=TEST_HWID_CONTENT)
    msg = self.service.ValidateConfigAndUpdateChecksum(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=StatusMsg.SUCCESS,
            new_hwid_config_contents=EXPECTED_REPLACE_RESULT, model=TEST_MODEL),
        msg)

  def testValidateConfigAndUpdateUpdatedComponents(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {
        'wireless': [
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1234_5678', 1234, 5678,
                common.COMPONENT_STATUS.supported, True, False,
                contents_analyzer.DiffStatus(
                    unchanged=False,
                    name_changed=True,
                    support_status_changed=False,
                    values_changed=False,
                    prev_comp_name='wireless_1234_5677',
                    prev_support_status=common.COMPONENT_STATUS.supported,
                )),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1111_2222', 1111, 2222,
                common.COMPONENT_STATUS.unqualified, True, False, None),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_hello_world', 0, 0, common.COMPONENT_STATUS.supported,
                False, True, None)
        ]
    })

    req = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumRequest(
        hwid_config_contents=TEST_HWID_CONTENT)
    msg = self.service.ValidateConfigAndUpdateChecksum(req)

    supported = hwid_api_messages_pb2.NameChangedComponent.SUPPORTED
    unqualified = hwid_api_messages_pb2.NameChangedComponent.UNQUALIFIED

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=StatusMsg.SUCCESS,
            new_hwid_config_contents=EXPECTED_REPLACE_RESULT,
            name_changed_components_per_category={
                'wireless':
                    hwid_api_messages_pb2.NameChangedComponents(entries=[
                        hwid_api_messages_pb2.NameChangedComponent(
                            cid=1234, qid=5678, support_status=supported,
                            component_name='wireless_1234_5678',
                            has_cid_qid=True,
                            diff_prev=hwid_api_messages_pb2.DiffStatus(
                                unchanged=False,
                                name_changed=True,
                                support_status_changed=False,
                                values_changed=False,
                                prev_comp_name='wireless_1234_5677',
                                prev_support_status='supported',
                            )),
                        hwid_api_messages_pb2.NameChangedComponent(
                            cid=1111, qid=2222, support_status=unqualified,
                            component_name='wireless_1111_2222',
                            has_cid_qid=True),
                        hwid_api_messages_pb2.NameChangedComponent(
                            cid=0, qid=0, support_status=supported,
                            component_name='wireless_hello_world',
                            has_cid_qid=False)
                    ])
            }, model=TEST_MODEL), msg)

  def testValidateConfigAndUpdateChecksumErrors(self):
    self.patch_hwid_validator.ValidateChange.side_effect = (
        hwid_validator.ValidationError([
            hwid_validator.Error(hwid_validator.ErrorCode.CONTENTS_ERROR, 'msg')
        ]))

    req = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumRequest(
        hwid_config_contents=TEST_HWID_CONTENT)
    msg = self.service.ValidateConfigAndUpdateChecksum(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=StatusMsg.BAD_REQUEST, error_message='msg'), msg)

  def testValidateConfigAndUpdateChecksumSchemaError(self):
    validation_error = hwid_validator.ValidationError(
        [hwid_validator.Error(hwid_validator.ErrorCode.SCHEMA_ERROR, 'msg')])
    self.patch_hwid_validator.ValidateChange.side_effect = validation_error
    req = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumRequest(
        hwid_config_contents=HWIDV3_CONTENT_SCHEMA_ERROR_CHANGE,
        prev_hwid_config_contents=GOLDEN_HWIDV3_CONTENT)
    msg = self.service.ValidateConfigAndUpdateChecksum(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=StatusMsg.SCHEMA_ERROR, error_message='msg'), msg)

  def testValidateConfigAndUpdateChecksumUnknwonStatus(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {
        'wireless': [
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1234_5678', 1234, 5678,
                common.COMPONENT_STATUS.supported, True, False, None),
            contents_analyzer.NameChangedComponentInfo('wireless_1111_2222',
                                                       1111, 2222, 'new_status',
                                                       True, False, None)
        ]
    })
    req = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumRequest(
        hwid_config_contents=TEST_HWID_CONTENT)
    msg = self.service.ValidateConfigAndUpdateChecksum(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=StatusMsg.BAD_REQUEST,
            error_message="Unknown status: 'new_status'."), msg)

  def testGetSku(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': ['bar1', 'bar2'],
        'dram': ['foo']
    })
    bom.project = 'foo'
    configless = None
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMAndConfigless.return_value = {
          TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None)
      }

      with mock.patch.object(self.service._sku_helper,
                             'GetTotalRAMFromHWIDData') as mock_func:
        mock_func.return_value = ('1MB', 100000000, [])

        req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
        msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS, project='foo', cpu='bar1_bar2',
            memory='1MB', memory_in_bytes=100000000, sku='foo_bar1_bar2_1MB'),
        msg)

  def testGetSku_WithConfigless(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': ['bar1', 'bar2'],
        'dram': ['foo']
    })
    bom.project = 'foo'
    configless = {
        'memory': 4
    }
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMAndConfigless.return_value = {
          TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None)
      }

      with mock.patch.object(self.service._sku_helper,
                             'GetTotalRAMFromHWIDData') as mock_func:
        mock_func.return_value = ('1MB', 100000000, [])

        req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
        msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS, project='foo', cpu='bar1_bar2',
            memory='4GB', memory_in_bytes=4294967296, sku='foo_bar1_bar2_4GB'),
        msg)

  def testGetSku_DramWithoutSize(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': 'bar',
        'dram': ['fail']
    })
    bom.project = 'foo'
    configless = None
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMAndConfigless.return_value = {
          TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None)
      }

      req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
      msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            project='foo', cpu='bar', memory_in_bytes=0, sku='foo_bar_0B',
            memory='0B', status=StatusMsg.SUCCESS,
            warnings=["'fail' does not contain size field"]), msg)

  def testGetDutLabels(self):
    with mock.patch.object(self.service, '_dut_label_helper') as mock_helper:
      mock_helper.GetDUTLabels.return_value = (
          hwid_api_messages_pb2.DutLabelsResponse())

      req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
      msg = self.service.GetDutLabels(req)

    mock_helper.GetDUTLabels.assert_called_once_with(req)
    self.assertEqual(msg, mock_helper.GetDUTLabels.return_value)

  def testGetHwidDbEditableSection_ProjectNotFound(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(project='foo')
      self.service.GetHwidDbEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testAnalyzeHwidDbEditableSectionChange_ProjectNotFound(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
          project='foo')
      self.service.AnalyzeHwidDbEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testValidateHwidDbEditableSectionChange_Deprecated(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeRequest()
      self.service.ValidateHwidDbEditableSectionChange(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.UNIMPLEMENTED)

  def testCreateHwidDbEditableSectionChangeCl_InvalidRequest(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
          project='foo')
      self.service.CreateHwidDbEditableSectionChangeCl(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)

  def testBatchGetHwidDbEditableSectionChangeClInfo_Empty(self):
    resp = self.service.BatchGetHwidDbEditableSectionChangeClInfo(
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
        ))

    self.assertEqual(
        resp,
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoResponse(
        ))

  def testBatchGenerateAvlComponentName_Empty(self):
    resp = self.service.BatchGenerateAvlComponentName(
        hwid_api_messages_pb2.BatchGenerateAvlComponentNameRequest())

    self.assertEqual(
        resp, hwid_api_messages_pb2.BatchGenerateAvlComponentNameResponse())

  def testAnalyzeHwidDbEditableSection_ProjectNotFound(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
          project='foo')
      self.service.AnalyzeHwidDbEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testGetHwidBundleResourceInfo_ProjectNotFound(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.GetHwidBundleResourceInfoRequest(
          project='foo')
      self.service.GetHwidBundleResourceInfo(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testCreateHwidBundle_ProjectNotFound(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.CreateHwidBundleRequest(project='foo')
      self.service.CreateHwidBundle(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)


if __name__ == '__main__':
  unittest.main()
