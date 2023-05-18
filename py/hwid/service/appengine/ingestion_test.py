#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for ingestion."""

import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import config as config_module
from cros.factory.hwid.service.appengine.data import config_data as config_data_module
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine.data import verification_payload_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import ingestion
from cros.factory.hwid.service.appengine.proto import ingestion_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.probe_info_service.app_engine import protorpc_utils


def _CreateMockConfig(fake_modules: test_utils.FakeModuleCollection):
  mock_config = mock.Mock(
      spec=config_module._Config,  # pylint: disable=protected-access
      wraps=config_module.CONFIG)
  mock_config.hwid_action_manager = fake_modules.fake_hwid_action_manager
  mock_config.vp_data_manager = mock.create_autospec(
      verification_payload_data.VerificationPayloadDataManager, instance=True)
  mock_config.hwid_db_data_manager = mock.create_autospec(
      hwid_db_data.HWIDDBDataManager, instance=True)
  mock_config.decoder_data_manager = fake_modules.fake_decoder_data_manager
  mock_config.hwid_repo_manager = mock.create_autospec(
      hwid_repo.HWIDRepoManager, instance=True)
  mock_config.goldeneye_filesystem = fake_modules.fake_goldeneye_memcache
  mock_config.hwid_data_cachers = [
      mock.create_autospec(hwid_action_manager.IHWIDDataCacher, instance=True),
  ]
  return mock_config


class IngestionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._config = _CreateMockConfig(self._modules)
    self.service = ingestion.ProtoRPCService.CreateInstance(
        self._config, config_data_module.CONFIG)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def testRefresh(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
        hwid_repo.HWIDDBMetadata('KBOARD.old', 'KBOARD', 2, 'KBOARD.old'),
        hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
        hwid_repo.HWIDDBMetadata('BETTERCBOARD', 'BETTERCBOARD', 3,
                                 'BETTERCBOARD'),
    ]
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest()
    response = self.service.IngestHwidDb(request)

    self.assertEqual(
        response, ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env'))
    self._config.hwid_db_data_manager.UpdateProjectsByRepo.assert_has_calls([
        mock.call(self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value, [
            hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
            hwid_repo.HWIDDBMetadata('KBOARD.old', 'KBOARD', 2, 'KBOARD.old'),
            hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
            hwid_repo.HWIDDBMetadata('BETTERCBOARD', 'BETTERCBOARD', 3,
                                     'BETTERCBOARD'),
        ], delete_missing=True)
    ])

  def testRefreshWithLimitedModels(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
        hwid_repo.HWIDDBMetadata('KBOARD.old', 'KBOARD', 2, 'KBOARD.old'),
        hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
        hwid_repo.HWIDDBMetadata('BETTERCBOARD', 'BETTERCBOARD', 3,
                                 'BETTERCBOARD'),
    ]
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest(
        limit_models=['KBOARD', 'SBOARD', 'COOLBOARD'])
    response = self.service.IngestHwidDb(request)

    self.assertEqual(
        response, ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env'))
    self._config.hwid_db_data_manager.UpdateProjectsByRepo.assert_has_calls([
        mock.call(self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value, [
            hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
            hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
        ], delete_missing=False)
    ])

  def testRefreshWithLimitedBoards(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KPROJ1', 'KBOARD', 3, 'KPROJ1'),
        hwid_repo.HWIDDBMetadata('KPROJ2', 'KBOARD', 3, 'KPROJ2'),
        hwid_repo.HWIDDBMetadata('KPROJ3', 'KBOARD', 3, 'KPROJ3'),
        hwid_repo.HWIDDBMetadata('SPROJ1', 'SBOARD', 3, 'SPROJ1'),
    ]
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest(limit_boards=['KBOARD'])
    response = self.service.IngestHwidDb(request)

    self.assertEqual(
        response, ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env'))
    self._config.hwid_db_data_manager.UpdateProjectsByRepo.assert_has_calls([
        mock.call(self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value, [
            hwid_repo.HWIDDBMetadata('KPROJ1', 'KBOARD', 3, 'KPROJ1'),
            hwid_repo.HWIDDBMetadata('KPROJ2', 'KBOARD', 3, 'KPROJ2'),
            hwid_repo.HWIDDBMetadata('KPROJ3', 'KBOARD', 3, 'KPROJ3'),
        ], delete_missing=False)
    ])

  def testRefreshWithInvalidLimitedBoards(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KPROJ1', 'KBOARD', 3, 'KPROJ1'),
        hwid_repo.HWIDDBMetadata('KPROJ2', 'KBOARD', 3, 'KPROJ2'),
        hwid_repo.HWIDDBMetadata('KPROJ3', 'KBOARD', 3, 'KPROJ3'),
        hwid_repo.HWIDDBMetadata('SPROJ1', 'SBOARD', 3, 'SPROJ1'),
    ]
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest(limit_boards=['ZBOARD'])
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.IngestHwidDb(request)
    self.assertEqual(ex.exception.detail, 'No model meets the limit.')

  def testRefreshWithLimitedBoardsAndModels(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KPROJ1', 'KBOARD', 3, 'KPROJ1'),
        hwid_repo.HWIDDBMetadata('KPROJ2', 'KBOARD', 3, 'KPROJ2'),
        hwid_repo.HWIDDBMetadata('KPROJ3', 'KBOARD', 3, 'KPROJ3'),
        hwid_repo.HWIDDBMetadata('SPROJ1', 'SBOARD', 3, 'SPROJ1'),
    ]
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest(
        limit_boards=['KBOARD'], limit_models=['KPROJ1', 'SPROJ1'])
    response = self.service.IngestHwidDb(request)

    self.assertEqual(
        response, ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env'))
    self._config.hwid_db_data_manager.UpdateProjectsByRepo.assert_has_calls([
        mock.call(self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value, [
            hwid_repo.HWIDDBMetadata('KPROJ1', 'KBOARD', 3, 'KPROJ1'),
        ], delete_missing=False)
    ])

  def testRefreshWithInvalidLimitedBoardsAndModels(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KPROJ1', 'KBOARD', 3, 'KPROJ1'),
        hwid_repo.HWIDDBMetadata('KPROJ2', 'KBOARD', 3, 'KPROJ2'),
        hwid_repo.HWIDDBMetadata('KPROJ3', 'KBOARD', 3, 'KPROJ3'),
        hwid_repo.HWIDDBMetadata('SPROJ1', 'SBOARD', 3, 'SPROJ1'),
    ]
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest(
        limit_boards=['SBOARD'], limit_models=['KPROJ1', 'KPROJ2'])
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.IngestHwidDb(request)
    self.assertEqual(ex.exception.detail, 'No model meets the limit.')

  def testRefreshWithoutBoardsInfo(self):
    live_hwid_repo = self._config.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.side_effect = hwid_repo.HWIDRepoError

    request = ingestion_pb2.IngestHwidDbRequest()
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.IngestHwidDb(request)
    self.assertEqual(ex.exception.detail, 'Got exception from HWID repo.')


class AVLNameTest(unittest.TestCase):

  class _FakeHWIDAction(hwid_action.HWIDAction):

    def __init__(self, comps):
      self.comps = comps

    def GetComponents(self, with_classes=None):
      return self.comps

  def setUp(self):
    super().setUp()
    self.fixtures = test_utils.FakeModuleCollection()
    self._config = _CreateMockConfig(self.fixtures)
    self.service = ingestion.ProtoRPCService.CreateInstance(
        self._config, config_data_module.CONFIG)
    self._hwid_data_cacher = self._config.hwid_data_cachers[0]

    self.init_mapping_data = {
        2: "name1",
        4: "name2",
        6: "name3",
    }
    self.update_mapping_data = {
        2: "name4",
        3: "name5",
        4: "name6",
    }

  def tearDown(self):
    super().tearDown()
    self.fixtures.ClearAll()

  @mock.patch(
      'cros.factory.hwid.service.appengine.api_connector.HWIDAPIConnector'
      '.GetAVLNameMapping')
  def testSyncNameMapping(self, get_avl_name_mapping):
    """Perform two round sync and check the consistency."""
    all_comps = {
        'cls1': ['cls1_1', 'cls1_2', 'cls1_3'],
        'cls2': ['cls2_4', 'notcls2_5', 'cls2_6']
    }
    fake_hwid_action = self._FakeHWIDAction(all_comps)
    self.fixtures.ConfigHWID('PROJ1', 3, 'unused_raw_db', fake_hwid_action)

    # Initialize mapping
    get_avl_name_mapping.return_value = self.init_mapping_data
    expected_mapping = {
        'cls1_1': 'cls1_1',
        'cls1_2': 'name1',
        'cls1_3': 'cls1_3',
        'cls2_4': 'name2',
        'notcls2_5': 'notcls2_5',
        'cls2_6': 'name3'
    }

    request = ingestion_pb2.SyncNameMappingRequest()
    response = self.service.SyncNameMapping(request)
    self.assertEqual(response, ingestion_pb2.SyncNameMappingResponse())

    mapping = {}
    for cls, comps in all_comps.items():
      for comp in comps:
        mapping[comp] = self.service.decoder_data_manager.GetAVLName(cls, comp)
    self.assertDictEqual(mapping, expected_mapping)

    # Update mapping
    get_avl_name_mapping.return_value = self.update_mapping_data
    expected_mapping = {
        'cls1_1': 'cls1_1',
        'cls1_2': 'name4',
        'cls1_3': 'name5',
        'cls2_4': 'name6',
        'notcls2_5': 'notcls2_5',
        'cls2_6': 'cls2_6'
    }

    request = ingestion_pb2.SyncNameMappingRequest()
    response = self.service.SyncNameMapping(request)
    self.assertEqual(response, ingestion_pb2.SyncNameMappingResponse())

    mapping = {}
    for cls, comps in all_comps.items():
      for comp in comps:
        mapping[comp] = self.service.decoder_data_manager.GetAVLName(cls, comp)
    self.assertDictEqual(mapping, expected_mapping)

  @mock.patch(
      'cros.factory.hwid.service.appengine.api_connector.HWIDAPIConnector'
      '.GetAVLNameMapping')
  def testSyncNameMapping_HWIDDataCacheInvalidate(self, get_avl_name_mapping):
    # Arrange.
    all_comps1 = {
        'cls1': ['cls1_1', 'cls1_3'],
    }
    all_comps2 = {
        'cls1': ['cls1_2', 'cls1_3']
    }
    fake_hwid_action1 = self._FakeHWIDAction(all_comps1)
    fake_hwid_action2 = self._FakeHWIDAction(all_comps2)
    self.fixtures.ConfigHWID('PROJ1', 3, 'unused_raw_db', fake_hwid_action1)
    self.fixtures.ConfigHWID('PROJ2', 3, 'unused_raw_db', fake_hwid_action2)
    get_avl_name_mapping.return_value = {
        1: 'name1',
        2: 'name2',
    }
    self.service.SyncNameMapping(ingestion_pb2.SyncNameMappingRequest())
    self._hwid_data_cacher.ClearCache.reset_mock()

    # Act: Change AVL name of CID:2.
    get_avl_name_mapping.return_value = {
        1: 'name1',
        2: 'name2-changed',
    }
    self.service.SyncNameMapping(ingestion_pb2.SyncNameMappingRequest())

    # Assert: HWID DB cacher of PROJ2 should trigger a cache invalidation.
    actual_calls = self._hwid_data_cacher.ClearCache.call_args_list
    # Only PROJ2 is affected.
    self.assertCountEqual([mock.call('PROJ2')], actual_calls)

    # Arrange: Reset mock.
    self._hwid_data_cacher.ClearCache.reset_mock()

    # Act: Remove AVL name of CID:1.
    get_avl_name_mapping.return_value = {
        2: 'name2-changed',
    }
    self.service.SyncNameMapping(ingestion_pb2.SyncNameMappingRequest())

    # Assert: HWID DB cacher of PROJ1 should trigger a cache invalidation.
    actual_calls = self._hwid_data_cacher.ClearCache.call_args_list
    # Only PROJ1 is affected.
    self.assertCountEqual([mock.call('PROJ1')], actual_calls)

    # Arrange: Reset mock.
    self._hwid_data_cacher.ClearCache.reset_mock()

    # Act: Add new AVL name of CID:3.
    get_avl_name_mapping.return_value = {
        2: 'name2-changed',
        3: 'name3',
    }
    self.service.SyncNameMapping(ingestion_pb2.SyncNameMappingRequest())

    # Assert: HWID DB cacher of both PROJ1 and PROJ2 should trigger cache
    # invalidations.
    actual_calls = self._hwid_data_cacher.ClearCache.call_args_list
    # Both PROJ1 and PROJ2 are affected.
    self.assertCountEqual(
        [mock.call('PROJ1'), mock.call('PROJ2')], actual_calls)


if __name__ == '__main__':
  unittest.main()
