#!/usr/bin/env python3
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for ingestion."""

import collections
import unittest
from unittest import mock

# pylint: disable=import-error, wrong-import-order, no-name-in-module
from google.cloud import ndb
import yaml
# pylint: enable=import-error, wrong-import-order, no-name-in-module

from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import ingestion
# pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine.proto import ingestion_pb2
# pylint: enable=import-error, no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils


class IngestionTest(unittest.TestCase):

  def setUp(self):
    patcher = mock.patch('__main__.ingestion.CONFIG.hwid_filesystem')
    self.patch_hwid_filesystem = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.ingestion.CONFIG.hwid_manager')
    self.patch_hwid_manager = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.ingestion.CONFIG.hwid_db_data_manager')
    self.patch_hwid_db_data_manager = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.ingestion.CONFIG.hwid_repo_manager',
                         autospec=True)
    self.hwid_repo_manager = patcher.start()
    self.addCleanup(patcher.stop)

    self.service = ingestion.ProtoRPCService()

  def testRefresh(self):
    hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
        hwid_repo.HWIDDBMetadata('KBOARD.old', 'KBOARD', 2, 'KBOARD.old'),
        hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
        hwid_repo.HWIDDBMetadata('BETTERCBOARD', 'BETTERCBOARD', 3,
                                 'BETTERCBOARD'),
    ]
    live_hwid_repo = self.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest()
    response = self.service.IngestHwidDb(request)

    self.assertEqual(
        response, ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env'))
    self.patch_hwid_db_data_manager.UpdateProjects.assert_has_calls([
        mock.call(self.hwid_repo_manager.GetLiveHWIDRepo.return_value, [
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
    live_hwid_repo = self.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.return_value = hwid_db_metadata_list

    request = ingestion_pb2.IngestHwidDbRequest(
        limit_models=['KBOARD', 'SBOARD', 'COOLBOARD'])
    response = self.service.IngestHwidDb(request)

    self.assertEqual(
        response, ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env'))
    self.patch_hwid_db_data_manager.UpdateProjects.assert_has_calls([
        mock.call(self.hwid_repo_manager.GetLiveHWIDRepo.return_value, [
            hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
            hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
        ], delete_missing=False)
    ])

  def testRefreshWithoutBoardsInfo(self):
    live_hwid_repo = self.hwid_repo_manager.GetLiveHWIDRepo.return_value
    live_hwid_repo.ListHWIDDBMetadata.side_effect = hwid_repo.HWIDRepoError

    request = ingestion_pb2.IngestHwidDbRequest()
    with self.assertRaises(protorpc_utils.ProtoRPCException) as ex:
      self.service.IngestHwidDb(request)
    self.assertEqual(ex.exception.detail, 'Got exception from HWID repo.')


class AVLNameTest(unittest.TestCase):

  NAME_MAPPING_FOLDER = 'avl_name_mapping'

  def setUp(self):
    patcher = mock.patch('__main__.ingestion.CONFIG.hwid_filesystem')
    self.patch_hwid_filesystem = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('__main__.ingestion.CONFIG.hwid_repo_manager',
                         autospec=True)
    self.hwid_repo_manager = patcher.start()
    self.addCleanup(patcher.stop)

    self.service = ingestion.ProtoRPCService()

    self.init_mapping_data = {
        'category1': {
            2: "name1",
            4: "name2",
            6: "name3",
        },
        'category2': {
            1: "name3",
            2: "name4",
            3: "name5",
        }
    }
    self.update_mapping_data = {
        'category2': {
            2: "name4",
            3: "name6",
            4: "name8",
        },
        'category3': {
            5: "name5",
            7: "name7",
            9: "name9",
        }
    }

    self.mock_init_mapping = {
        category + '.yaml': yaml.dump(mapping, default_flow_style=False)
        for category, mapping in self.init_mapping_data.items()
    }

    self.mock_update_mapping = {
        category + '.yaml': yaml.dump(mapping, default_flow_style=False)
        for category, mapping in self.update_mapping_data.items()
    }

  def testSyncNameMapping(self):
    """Perform two round sync and check the consistency."""
    live_hwid_repo = self.hwid_repo_manager.GetLiveHWIDRepo.return_value

    # Init mapping
    # pylint: disable=dict-items-not-iterating
    live_hwid_repo.IterAVLNameMappings.return_value = (
        self.mock_init_mapping.items())
    # pylint: enable=dict-items-not-iterating

    request = ingestion_pb2.SyncNameMappingRequest()
    response = self.service.SyncNameMapping(request)
    self.assertEqual(response, ingestion_pb2.SyncNameMappingResponse())

    mapping_in_datastore = collections.defaultdict(dict)
    with ndb.Client().context():
      for entry in decoder_data.AVLNameMapping.query():
        self.assertIn(entry.category, self.init_mapping_data)
        mapping_in_datastore[entry.category][entry.component_id] = entry.name
    self.assertDictEqual(mapping_in_datastore, self.init_mapping_data)

    # Update mapping
    # pylint: disable=dict-items-not-iterating
    live_hwid_repo.IterAVLNameMappings.return_value = (
        self.mock_update_mapping.items())
    # pylint: enable=dict-items-not-iterating

    request = ingestion_pb2.SyncNameMappingRequest()
    response = self.service.SyncNameMapping(request)
    self.assertEqual(response, ingestion_pb2.SyncNameMappingResponse())

    mapping_in_datastore = collections.defaultdict(dict)
    with ndb.Client().context():
      for entry in decoder_data.AVLNameMapping.query():
        self.assertIn(entry.category, self.update_mapping_data)
        mapping_in_datastore[entry.category][entry.component_id] = entry.name
    self.assertDictEqual(mapping_in_datastore, self.update_mapping_data)


if __name__ == '__main__':
  unittest.main()
