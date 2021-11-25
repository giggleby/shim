#!/usr/bin/env python3
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for cros.hwid.service.appengine.hwid_api"""

import os.path
import textwrap
import unittest
from unittest import mock

from cros.chromeoshwid import update_checksum
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_api
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import contents_analyzer
# pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2
# pylint: enable=import-error, no-name-in-module
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
HWIDV3_CONTENT_SYNTAX_ERROR_CHANGE = file_utils.ReadFile(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'testdata',
        'v3-syntax-error-change.yaml'))
HWIDV3_CONTENT_SCHEMA_ERROR_CHANGE = file_utils.ReadFile(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'testdata',
        'v3-schema-error-change.yaml'))

TEST_PREV_HWID_DB_CONTENT = 'prefix\nchecksum: 1234\nimage_id:\nsuffix_v0\n'
TEST_HWID_DB_EDITABLE_SECTION_CONTENT = 'image_id:\nsuffix_v1\n'

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
                common.COMPONENT_STATUS.supported, True),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1111_2222', 1111, 2222,
                common.COMPONENT_STATUS.unqualified, True),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_hello_world', 0, 0, common.COMPONENT_STATUS.supported,
                False)
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
                            has_cid_qid=True),
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
                common.COMPONENT_STATUS.supported, True),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1111_2222', 1111, 2222, 'new_status', True)
        ]
    })
    req = hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumRequest(
        hwid_config_contents=TEST_HWID_CONTENT)
    msg = self.service.ValidateConfigAndUpdateChecksum(req)

    self.assertEqual(
        hwid_api_messages_pb2.ValidateConfigAndUpdateChecksumResponse(
            status=StatusMsg.BAD_REQUEST,
            error_message='Unknown status: \'new_status\''), msg)

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
        mock_func.return_value = ('1MB', 100000000)

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
        mock_func.return_value = ('1MB', 100000000)

        req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
        msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS, project='foo', cpu='bar1_bar2',
            memory='4GB', memory_in_bytes=4294967296, sku='foo_bar1_bar2_4GB'),
        msg)

  def testGetSku_BadDRAM(self):
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

      with mock.patch.object(self.service._sku_helper,
                             'GetTotalRAMFromHWIDData') as mock_func:
        mock_func.side_effect = sku_helper.SKUDeductionError('X')

        req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
        msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(status=StatusMsg.BAD_REQUEST,
                                          error='X'), msg)

  def testGetDutLabels(self):
    with mock.patch.object(self.service, '_dut_label_helper') as mock_helper:
      mock_helper.GetDUTLabels.return_value = (
          hwid_api_messages_pb2.DutLabelsResponse())

      req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
      msg = self.service.GetDutLabels(req)

    mock_helper.GetDUTLabels.assert_called_once_with(req)
    self.assertEqual(msg, mock_helper.GetDUTLabels.return_value)

  def testGetHwidDbEditableSectionProjectDoesntExist(self):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.side_effect = ValueError

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(
        project='test_project')

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.GetHwidDbEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND)

  def testGetHwidDbEditableSectionNotV3(self):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 2,
                                 'v2/test_project'))

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(
        project='test_project')

    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.GetHwidDbEditableSection(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.FAILED_PRECONDITION)

  def testGetHwidDbEditableSectionSuccess(self):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = textwrap.dedent("""\
        # some prefix
        checksum: "string"

        image_id:
          line0

          line1
          line2\r
        line3

        """)

    req = hwid_api_messages_pb2.GetHwidDbEditableSectionRequest(
        project='test_project')
    resp = self.service.GetHwidDbEditableSection(req)

    self.assertEqual(
        resp.hwid_db_editable_section,
        '\n'.join(['image_id:', '  line0', '', '  line1', '  line2', 'line3']))

  def testValidateHwidDbEditableSectionChangeSchemaError(self):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT
    validation_error = hwid_validator.ValidationError(
        [hwid_validator.Error(hwid_validator.ErrorCode.SCHEMA_ERROR, 'msg')])
    self.patch_hwid_validator.ValidateChange.side_effect = validation_error

    req = hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.ValidateHwidDbEditableSectionChange(req)

    self.assertEqual(len(resp.validation_result.errors), 1)
    self.assertEqual(
        resp.validation_result.errors[0],
        hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult.Error(
            code=hwid_api_messages_pb2
            .HwidDbEditableSectionChangeValidationResult.SCHEMA_ERROR,
            message='msg'))

  def testValidateHwidDbEditableSectionChangePassed(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {})
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT

    req = hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.ValidateHwidDbEditableSectionChange(req)

    self.assertTrue(resp.validation_token)
    self.assertFalse(resp.validation_result.errors)

  def testValidateHwidDbEditableSectionChangeReturnUpdatedComponents(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {
        'wireless': [
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1234_5678', 1234, 5678,
                common.COMPONENT_STATUS.supported, True),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1111_2222', 1111, 2222,
                common.COMPONENT_STATUS.unqualified, True),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_hello_world', 0, 0, common.COMPONENT_STATUS.supported,
                False)
        ]
    })
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT

    req = hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.ValidateHwidDbEditableSectionChange(req)

    supported = hwid_api_messages_pb2.NameChangedComponent.SUPPORTED
    unqualified = hwid_api_messages_pb2.NameChangedComponent.UNQUALIFIED

    ValidationResultMsg = (
        hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult)
    self.assertEqual(
        ValidationResultMsg(
            name_changed_components_per_category={
                'wireless':
                    hwid_api_messages_pb2.NameChangedComponents(entries=[
                        hwid_api_messages_pb2.NameChangedComponent(
                            cid=1234, qid=5678, support_status=supported,
                            component_name='wireless_1234_5678',
                            has_cid_qid=True),
                        hwid_api_messages_pb2.NameChangedComponent(
                            cid=1111, qid=2222, support_status=unqualified,
                            component_name='wireless_1111_2222',
                            has_cid_qid=True),
                        hwid_api_messages_pb2.NameChangedComponent(
                            cid=0, qid=0, support_status=supported,
                            component_name='wireless_hello_world',
                            has_cid_qid=False)
                    ])
            }), resp.validation_result)

  def testValidateHwidDbEditableSectionChangeUnknownStatus(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {
        'wireless': [
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1234_5678', 1234, 5678,
                common.COMPONENT_STATUS.supported, True),
            contents_analyzer.NameChangedComponentInfo(
                'wireless_1111_2222', 1111, 2222, 'new_status', True)
        ]
    })
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT

    req = hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.ValidateHwidDbEditableSectionChange(req)

    self.assertEqual(len(resp.validation_result.errors), 1)
    self.assertEqual(resp.validation_result.errors[0].code,
                     resp.validation_result.CONTENTS_ERROR)

  def testCreateHwidDbEditableSectionChangeClValidationExpired(self):
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {})
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT

    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT,
        validation_token='this_is_an_invalid_verification_id')
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.CreateHwidDbEditableSectionChangeCl(req)
    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.ABORTED)

  def testCreateHwidDbEditableSectionChangeClSucceed(self):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT
    self.patch_hwid_validator.ValidateChange.return_value = (TEST_MODEL, {})
    req = hwid_api_messages_pb2.ValidateHwidDbEditableSectionChangeRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.ValidateHwidDbEditableSectionChange(req)
    validation_token = resp.validation_token
    live_hwid_repo.CommitHWIDDB.return_value = 123

    req = hwid_api_messages_pb2.CreateHwidDbEditableSectionChangeClRequest(
        project='test_project',
        new_hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT,
        validation_token=validation_token)
    resp = self.service.CreateHwidDbEditableSectionChangeCl(req)
    self.assertEqual(resp.cl_number, 123)

  def testBatchGetHwidDbEditableSectionChangeClInfo(self):
    all_hwid_commit_infos = {
        1:
            hwid_repo.HWIDDBCLInfo(hwid_repo.HWIDDBCLStatus.NEW, []),
        2:
            hwid_repo.HWIDDBCLInfo(hwid_repo.HWIDDBCLStatus.MERGED, []),
        3:
            hwid_repo.HWIDDBCLInfo(hwid_repo.HWIDDBCLStatus.ABANDONED, []),
        4:
            hwid_repo.HWIDDBCLInfo(hwid_repo.HWIDDBCLStatus.NEW, [
                hwid_repo.HWIDDBCLComment('msg1', 'user1@email'),
                hwid_repo.HWIDDBCLComment('msg2', 'user2@email'),
            ])
    }

    def _MockGetHWIDDBCLInfo(cl_number):
      try:
        return all_hwid_commit_infos[cl_number]
      except KeyError:
        raise hwid_repo.HWIDRepoError from None

    self.patch_hwid_repo_manager.GetHWIDDBCLInfo.side_effect = (
        _MockGetHWIDDBCLInfo)

    req = (
        hwid_api_messages_pb2.BatchGetHwidDbEditableSectionChangeClInfoRequest(
            cl_numbers=[1, 2, 3, 4, 5, 6]))
    resp = self.service.BatchGetHwidDbEditableSectionChangeClInfo(req)
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

  def testBatchGenerateAvlComponentName_NoQid(self):
    req = hwid_api_messages_pb2.BatchGenerateAvlComponentNameRequest()
    req.component_name_materials.add(component_class='class1', avl_cid=123,
                                     avl_qid=0, seq_no=3)
    resp = self.service.BatchGenerateAvlComponentName(req)
    self.assertEqual(resp.component_names, ['class1_123#3'])

  def testBatchGenerateAvlComponentName_HasQid(self):
    req = hwid_api_messages_pb2.BatchGenerateAvlComponentNameRequest()
    req.component_name_materials.add(component_class='class1', avl_cid=123,
                                     avl_qid=456, seq_no=3)
    req.component_name_materials.add(component_class='class2', avl_cid=234,
                                     avl_qid=567, seq_no=4)
    resp = self.service.BatchGenerateAvlComponentName(req)
    self.assertEqual(resp.component_names,
                     ['class1_123_456#3', 'class2_234_567#4'])

  def CheckForLabelValue(self, response, label_to_check_for,
                         value_to_check_for=None):
    for label in response.labels:
      if label.name == label_to_check_for:
        if value_to_check_for and label.value != value_to_check_for:
          return False
        return True
    return False

  @mock.patch('cros.factory.hwid.v3.contents_analyzer.ContentsAnalyzer')
  def testAnalyzeHwidDbEditableSection_PreconditionErrors(
      self, mock_contents_analyzer_constructor):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT

    fake_contents_analyzer_inst = (
        mock_contents_analyzer_constructor.return_value)
    fake_contents_analyzer_inst.AnalyzeChange.return_value = (
        contents_analyzer.ChangeAnalysisReport([
            contents_analyzer.Error(contents_analyzer.ErrorCode.SCHEMA_ERROR,
                                    'some_schema_error')
        ], [], {}))

    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='test_project',
        hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.AnalyzeHwidDbEditableSection(req)
    ValidationResultMsg = (
        hwid_api_messages_pb2.HwidDbEditableSectionChangeValidationResult)
    self.assertCountEqual(
        list(resp.validation_result.errors), [
            ValidationResultMsg.Error(code=ValidationResultMsg.SCHEMA_ERROR,
                                      message='some_schema_error')
        ])

  @mock.patch('cros.factory.hwid.v3.contents_analyzer.ContentsAnalyzer')
  def testAnalyzeHwidDbEditableSection_Pass(self,
                                            mock_contents_analyzer_constructor):
    live_hwid_repo = self.patch_hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.GetHWIDDBMetadataByName.return_value = (
        hwid_repo.HWIDDBMetadata('test_project', 'test_project', 3,
                                 'v3/test_project'))
    live_hwid_repo.LoadHWIDDBByName.return_value = TEST_PREV_HWID_DB_CONTENT

    ModificationStatus = (
        contents_analyzer.DBLineAnalysisResult.ModificationStatus)
    Part = contents_analyzer.DBLineAnalysisResult.Part
    fake_contents_analyzer_inst = (
        mock_contents_analyzer_constructor.return_value)
    fake_contents_analyzer_inst.AnalyzeChange.return_value = (
        contents_analyzer.ChangeAnalysisReport(
            [], [
                contents_analyzer.DBLineAnalysisResult(
                    ModificationStatus.NOT_MODIFIED,
                    [Part(Part.Type.TEXT, 'text1')]),
                contents_analyzer.DBLineAnalysisResult(
                    ModificationStatus.MODIFIED,
                    [Part(Part.Type.COMPONENT_NAME, 'comp1')]),
                contents_analyzer.DBLineAnalysisResult(
                    ModificationStatus.NEWLY_ADDED, [
                        Part(Part.Type.COMPONENT_NAME, 'comp2'),
                        Part(Part.Type.COMPONENT_STATUS, 'comp1')
                    ]),
            ], {
                'comp1':
                    contents_analyzer.HWIDComponentAnalysisResult(
                        'comp_cls1', 'comp_name1', 'unqualified', False, None,
                        2, None),
                'comp2':
                    contents_analyzer.HWIDComponentAnalysisResult(
                        'comp_cls2', 'comp_cls2_111_222#9', 'unqualified', True,
                        (111, 222), 1, 'comp_cls2_111_222#1'),
            }))

    req = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionRequest(
        project='test_project',
        hwid_db_editable_section=TEST_HWID_DB_EDITABLE_SECTION_CONTENT)
    resp = self.service.AnalyzeHwidDbEditableSection(req)

    AnalysisReportMsg = (
        hwid_api_messages_pb2.HwidDbEditableSectionAnalysisReport)
    LineMsg = AnalysisReportMsg.HwidDbLine
    LinePartMsg = AnalysisReportMsg.HwidDbLinePart
    ComponentInfoMsg = AnalysisReportMsg.ComponentInfo
    expected_resp = hwid_api_messages_pb2.AnalyzeHwidDbEditableSectionResponse(
        analysis_report=AnalysisReportMsg(
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
                    ComponentInfoMsg(
                        component_class='comp_cls1',
                        original_name='comp_name1',
                        original_status='unqualified',
                        is_newly_added=False,
                        has_avl=False,
                        seq_no=2,
                    ),
                'comp2':
                    ComponentInfoMsg(
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
            }))

    self.assertEqual(resp, expected_resp)


if __name__ == '__main__':
  unittest.main()
