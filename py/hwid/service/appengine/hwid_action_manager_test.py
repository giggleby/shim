#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Optional
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import test_utils


class HWIDPreprocDataForTest(hwid_preproc_data.HWIDPreprocData):
  CACHE_VERSION = '1'

  def __init__(self, project, raw_db, raw_db_internal, hwid_action_inst):
    super().__init__(project)
    self.raw_db = raw_db
    self.raw_db_internal = raw_db_internal
    self.hwid_action = hwid_action_inst

  @classmethod
  def FlipCacheVersion(cls):
    cls.CACHE_VERSION = '2' if cls.CACHE_VERSION == '1' else '1'


class HWIDActionForTest(hwid_action.HWIDAction):

  def __init__(self, uid):
    self._uid = uid

  def __eq__(self, rhs):
    return isinstance(rhs, HWIDActionForTest) and self._uid == rhs._uid  # pylint: disable=protected-access

  def __ne__(self, rhs):
    return not self.__eq__(rhs)


class InstanceFactoryForTest(hwid_action_manager.InstanceFactory):

  def __init__(self):
    self._known_project_to_hwid_action = {}

  def SetHWIDPreprocDataNotSupported(self, project):
    self._known_project_to_hwid_action.pop(project, None)

  def SetHWIDPreprocDataWithAction(
      self, project, hwid_action_inst: Optional[HWIDActionForTest] = None):
    self._known_project_to_hwid_action[project] = hwid_action_inst

  def CreateHWIDPreprocData(self, metadata, raw_db,
                            raw_db_internal: Optional[str] = None):
    try:
      hwid_action_inst = self._known_project_to_hwid_action[metadata.project]
    except KeyError:
      raise hwid_action_manager.ProjectNotSupportedError
    return HWIDPreprocDataForTest(metadata.project, raw_db, raw_db_internal,
                                  hwid_action_inst)

  def CreateHWIDAction(self, hwid_data):
    hwid_action_inst = (
        hwid_data.hwid_action
        if isinstance(hwid_data, HWIDPreprocDataForTest) else None)
    if hwid_action_inst is None:
      raise hwid_action_manager.ProjectUnavailableError
    return hwid_action_inst


class HWIDActionManagerTest(unittest.TestCase):
  """Tests the HwidManager class."""

  def setUp(self):
    super().setUp()

    instance_factory = InstanceFactoryForTest()
    self._instance_factory = mock.Mock(spec=instance_factory,
                                       wraps=instance_factory)

    self._modules = test_utils.FakeModuleCollection()
    self._hwid_db_data_manager = mock.Mock(
        self._modules.fake_hwid_db_data_manager,
        wraps=self._modules.fake_hwid_db_data_manager)

    memcache = test_utils.FakeMemcacheAdapter()

    self._hwid_action_manager = hwid_action_manager.HWIDActionManager(
        self._hwid_db_data_manager, memcache,
        instance_factory=self._instance_factory)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def testGetHWIDAction_ProjectNotFound(self):
    # By default there are no projects in the datastore.

    with self.assertRaises(hwid_action_manager.ProjectNotFoundError):
      self._hwid_action_manager.GetHWIDAction('PROJ')

  def testGetHWIDAction_ProjectLoadError(self):
    self._hwid_db_data_manager.RegisterProjectForTest('PROJ', 'PROJ', '3',
                                                      'db data')
    self._instance_factory.SetHWIDPreprocDataNotSupported('PROJ')

    with self.assertRaises(hwid_action_manager.ProjectNotSupportedError):
      self._hwid_action_manager.GetHWIDAction('PROJ')

  def testGetHWIDAction_ProjectCreateActionError(self):
    self._RegisterProjectWithAction('PROJ', None)

    with self.assertRaises(hwid_action_manager.ProjectUnavailableError):
      self._hwid_action_manager.GetHWIDAction('PROJ')

  def testGetHWIDAction_SuccessWithCacheMiss(self):
    # The default memcache is empty.
    expected_hwid_action = self._RegisterProjectWithAction('PROJ', 'theuid')

    actual_hwid_action = self._hwid_action_manager.GetHWIDAction('PROJ')

    self.assertEqual(actual_hwid_action, expected_hwid_action)

  def testGetHWIDAction_SuccessWithCacheHit(self):
    expected_hwid_action = self._RegisterProjectWithAction('PROJ', 'theuid')
    self._hwid_action_manager.GetHWIDAction('PROJ')

    actual_hwid_action = self._hwid_action_manager.GetHWIDAction('PROJ')

    self.assertEqual(actual_hwid_action, expected_hwid_action)
    self.assertEqual(self._instance_factory.CreateHWIDPreprocData.call_count, 1)
    self.assertEqual(self._hwid_db_data_manager.LoadHWIDDB.call_count, 2)

  def testGetHWIDAction_SuccessWithCacheHitLegacyData(self):
    self._RegisterProjectWithAction('PROJ', 'theuid')
    self._hwid_action_manager.ReloadMemcacheCacheFromFiles()
    HWIDPreprocDataForTest.FlipCacheVersion()
    expected_hwid_action = HWIDActionForTest('theuid2')
    self._instance_factory.SetHWIDPreprocDataWithAction('PROJ',
                                                        expected_hwid_action)

    actual_hwid_action = self._hwid_action_manager.GetHWIDAction('PROJ')

    self.assertEqual(actual_hwid_action, expected_hwid_action)

  def testListsProjects(self):
    self._RegisterProjectWithAction('PROJ1', 'theuid1')
    self._RegisterProjectWithAction('PROJ2', 'theuid2')
    self._RegisterProjectWithAction('PROJ3', 'theuid3')
    self.assertEqual(self._hwid_action_manager.ListProjects(),
                     {'PROJ1', 'PROJ2', 'PROJ3'})

  def testReloadMemcacheCacheFromFiles(self):
    self._RegisterProjectWithAction('PROJ1', 'theuid1')
    self._RegisterProjectWithAction('PROJ2', 'theuid2')
    self._RegisterProjectWithAction('PROJ3', 'theuid3')

    self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
        limit_models=['PROJ1', 'PROJ2'])

    # If `ReloadMemcacheCacheFromFiles()` works, `GetHWIDAction()` should
    # hit the cache for PROJ1 and PROJ2.
    self._hwid_db_data_manager.LoadHWIDDB.reset_mock()
    self._hwid_action_manager.GetHWIDAction('PROJ1')
    self._hwid_action_manager.GetHWIDAction('PROJ2')
    self.assertEqual(self._hwid_db_data_manager.LoadHWIDDB.call_count, 0)
    # Then since we set `limit_models` to PROJ1 and PROJ2 only, `GetHWIDAction`
    # should load the HWID DB data from the datastore for PROJ3.
    self._hwid_action_manager.GetHWIDAction('PROJ3')
    self.assertEqual(self._hwid_db_data_manager.LoadHWIDDB.call_count, 2)

  def testReloadMemcacheFromFiles_LegacySkipInternal(self):
    self._RegisterProjectWithAction('PROJ_V2', 'uid_v2', '2')
    self._RegisterProjectWithAction('PROJ_V3', 'uid_v3', '3')

    self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
        limit_models=['PROJ_V2', 'PROJ_V3'])
    metadata_v2 = self._hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        'PROJ_V2')
    metadata_v3 = self._hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        'PROJ_V3')

    with self._modules.ndb_connector.CreateClientContextWithGlobalCache():
      self.assertCountEqual([
          mock.call(metadata_v2),
          mock.call(metadata_v3),
          mock.call(metadata_v3, internal=True),
      ], self._hwid_db_data_manager.LoadHWIDDB.call_args_list)

  def _RegisterProjectWithAction(
      self, project, action_uid: Optional[str] = None, version: str = '3'):
    self._hwid_db_data_manager.RegisterProjectForTest(project, project, version,
                                                      'db data')
    opt_hwid_action_inst = HWIDActionForTest(
        action_uid) if action_uid is not None else None
    self._instance_factory.SetHWIDPreprocDataWithAction(project,
                                                        opt_hwid_action_inst)
    return opt_hwid_action_inst


if __name__ == '__main__':
  unittest.main()
