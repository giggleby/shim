#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for cros.hwid.service.appengine.hwid_api"""

import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import config as config_module
from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_api
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.probe_info_service.app_engine import protorpc_utils


TEST_HWID = 'Foo'

StatusMsg = hwid_api_messages_pb2.Status
_BOMAndConfigless = bc_helper.BOMAndConfigless


def _CreateMockConfig(fake_modules: test_utils.FakeModuleCollection):
  mock_config = mock.Mock(
      spec=config_module._Config,  # pylint: disable=protected-access
      wraps=config_module.CONFIG)
  mock_config.hwid_action_manager = fake_modules.fake_hwid_action_manager
  mock_config.decoder_data_manager = fake_modules.fake_decoder_data_manager
  mock_config.hwid_repo_manager = mock.create_autospec(
      hwid_repo.HWIDRepoManager, instance=True)
  hwid_live_repo = mock_config.hwid_repo_manager.GetLiveHWIDRepo.return_value
  hwid_live_repo.ListHWIDDBMetadata.return_value = []
  hwid_live_repo.GetHWIDDBMetadataByName.side_effect = ValueError
  mock_config.hwid_db_data_manager = fake_modules.fake_hwid_db_data_manager
  mock_config.bom_data_cacher = fake_modules.fake_bom_data_cacher
  mock_config.avl_metadata_manager = fake_modules.fake_avl_metadata_manager
  mock_config.avl_converter_manager = converter_utils.ConverterManager({})
  return mock_config


class ProtoRPCServiceTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._config = _CreateMockConfig(self._modules)
    self.service = hwid_api.ProtoRPCService(self._config)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def _SetupFakeHWIDActionForFeatureEnablementLabel(
      self, project_name: str,
      feature_enablement_label: str = 'just_a_random_default_value'):
    instance = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    instance.GetFeatureEnablementLabel.return_value = feature_enablement_label
    self._modules.ConfigHWID(project_name, 3, 'unused raw HWID DB contents',
                             hwid_action=instance)
    return instance

  def testGetSku(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': ['bar1', 'bar2'],
        'dram': ['foo']
    })
    bom.project = 'foo'
    configless = None
    self._SetupFakeHWIDActionForFeatureEnablementLabel(bom.project,
                                                       'feature_value')
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMAndConfigless.return_value = {
          TEST_HWID: _BOMAndConfigless(bom, configless, None)
      }

      with mock.patch.object(
          self.service._sku_helper,  # pylint: disable=protected-access
          'GetTotalRAMFromHWIDData') as mock_func:
        mock_func.return_value = ('1MB', 100000000, [])

        req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
        msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS, project='foo', cpu='bar1_bar2',
            memory='1MB', memory_in_bytes=100000000, sku='foo_bar1_bar2_1MB',
            feature_enablement_status='feature_value'), msg)

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
    self._SetupFakeHWIDActionForFeatureEnablementLabel(bom.project,
                                                       'feature_value')
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMAndConfigless.return_value = {
          TEST_HWID: _BOMAndConfigless(bom, configless, None)
      }

      with mock.patch.object(
          self.service._sku_helper,  # pylint: disable=protected-access
          'GetTotalRAMFromHWIDData') as mock_func:
        mock_func.return_value = ('1MB', 100000000, [])

        req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
        msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS, project='foo', cpu='bar1_bar2',
            memory='4GB', memory_in_bytes=4294967296, sku='foo_bar1_bar2_4GB',
            feature_enablement_status='feature_value'), msg)

  def testGetSku_DramWithoutSize(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': 'bar',
        'dram': ['fail']
    })
    bom.project = 'foo'
    configless = None
    self._SetupFakeHWIDActionForFeatureEnablementLabel(bom.project,
                                                       'feature_value')
    with mock.patch.object(self.service, '_bc_helper') as mock_helper:
      mock_helper.BatchGetBOMAndConfigless.return_value = {
          TEST_HWID: _BOMAndConfigless(bom, configless, None)
      }

      req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
      msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            project='foo', cpu='bar', memory_in_bytes=0, sku='foo_bar_0B',
            memory='0B', status=StatusMsg.SUCCESS, warnings=[
                "'fail' does not contain size field"
            ], feature_enablement_status='feature_value'), msg)

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

    # No token is provided which causes no cache found.
    self.assertEqual(protorpc_utils.RPCCanonicalErrorCode.ABORTED,
                     ex.exception.code)
    self.assertEqual('The validation token is expired.', ex.exception.detail)

  def testCreateHwidDbFirmwareInfoUpdateCl_Empty(self):
    resp = self.service.CreateHwidDbFirmwareInfoUpdateCl(
        hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClRequest())

    self.assertEqual(
        resp, hwid_api_messages_pb2.CreateHwidDbFirmwareInfoUpdateClResponse())

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
    gerrit_tot_hwid_repo = (
        self._config.hwid_repo_manager.GetGerritToTHWIDRepo.return_value)
    gerrit_tot_hwid_repo.GetHWIDDBMetadataByName.side_effect = KeyError
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

  def testSetFirmwareInfoSupportStatus_InvalidRequest(self):
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      req = hwid_api_messages_pb2.SetFirmwareInfoSupportStatusRequest(
          project='foo')
      self.service.SetFirmwareInfoSupportStatus(req)

    self.assertEqual(ex.exception.code,
                     protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT)


if __name__ == '__main__':
  unittest.main()
