#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Optional
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine import test_utils


class HWIDPreprocDataForTest(hwid_preproc_data.HWIDPreprocData):
  CACHE_VERSION = '1'

  def __init__(self, project, raw_db, hwid_action_inst):
    super().__init__(project)
    self.raw_db = raw_db
    self.hwid_action = hwid_action_inst

  @classmethod
  def FlipCacheVersion(cls):
    cls.CACHE_VERSION = '2' if cls.CACHE_VERSION == '1' else '1'


class HWIDActionForTest(hwid_action.HWIDAction):

  def __init__(self, uid):
    self._uid = uid

  def __eq__(self, rhs):
    return isinstance(rhs, HWIDActionForTest) and self._uid == rhs._uid

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

  def CreateHWIDPreprocData(self, metadata, raw_db):
    try:
      hwid_action_inst = self._known_project_to_hwid_action[metadata.project]
    except KeyError:
      raise hwid_action_manager.ProjectNotSupportedError
    return HWIDPreprocDataForTest(metadata.project, raw_db, hwid_action_inst)

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
      self._hwid_action_manager.GetHWIDAction('proj')

  def testGetHWIDAction_ProjectLoadError(self):
    self._hwid_db_data_manager.RegisterProjectForTest('PROJ', 'PROJ', '3',
                                                      'db data')
    self._instance_factory.SetHWIDPreprocDataNotSupported('PROJ')

    with self.assertRaises(hwid_action_manager.ProjectNotSupportedError):
      self._hwid_action_manager.GetHWIDAction('proj')

  def testGetHWIDAction_ProjectCreateActionError(self):
    self._RegisterProjectWithAction('PROJ', None)

    with self.assertRaises(hwid_action_manager.ProjectUnavailableError):
      self._hwid_action_manager.GetHWIDAction('proj')

  def testGetHWIDAction_SuccessWithCacheMiss(self):
    # The default memcache is empty.
    expected_hwid_action = self._RegisterProjectWithAction('PROJ', 'theuid')

    actual_hwid_action = self._hwid_action_manager.GetHWIDAction('proj')

    self.assertEqual(actual_hwid_action, expected_hwid_action)

  def testGetHWIDAction_SuccessWithCatchHit(self):
    expected_hwid_action = self._RegisterProjectWithAction('PROJ', 'theuid')
    self._hwid_action_manager.GetHWIDAction('proj')

    actual_hwid_action = self._hwid_action_manager.GetHWIDAction('proj')

    self.assertEqual(actual_hwid_action, expected_hwid_action)
    self.assertEqual(self._instance_factory.CreateHWIDPreprocData.call_count, 1)
    self.assertEqual(self._hwid_db_data_manager.LoadHWIDDB.call_count, 1)

  def testGetHWIDAction_SuccessWithCatchHitLegacyData(self):
    self._RegisterProjectWithAction('PROJ', 'theuid')
    self._hwid_action_manager.ReloadMemcacheCacheFromFiles()
    HWIDPreprocDataForTest.FlipCacheVersion()
    expected_hwid_action = HWIDActionForTest('theuid2')
    self._instance_factory.SetHWIDPreprocDataWithAction('PROJ',
                                                        expected_hwid_action)

    actual_hwid_action = self._hwid_action_manager.GetHWIDAction('proj')

    self.assertEqual(actual_hwid_action, expected_hwid_action)

  def testReloadMemcacheCacheFromFiles(self):
    self._RegisterProjectWithAction('PROJ1', 'theuid1')
    self._RegisterProjectWithAction('PROJ2', 'theuid2')
    self._RegisterProjectWithAction('PROJ3', 'theuid3')

    self._hwid_action_manager.ReloadMemcacheCacheFromFiles(
        limit_models=['PROJ1', 'PROJ2'])
    load_db_base_call_cnt = self._hwid_db_data_manager.LoadHWIDDB.call_count

    # If `ReloadMemcacheCacheFromFiles()` works, `GetHWIDAction()` should
    # hit the cache for PROJ1 and PROJ2.
    self._hwid_action_manager.GetHWIDAction('proj1')
    self._hwid_action_manager.GetHWIDAction('proj2')
    self.assertEqual(self._hwid_db_data_manager.LoadHWIDDB.call_count,
                     load_db_base_call_cnt)
    # Then since we set `limit_models` to PROJ1 and PROJ2 only, `GetHWIDAction`
    # should load the HWID DB data from the datastore for PROJ3.
    self._hwid_action_manager.GetHWIDAction('proj3')
    self.assertEqual(self._hwid_db_data_manager.LoadHWIDDB.call_count,
                     load_db_base_call_cnt + 1)

  def _RegisterProjectWithAction(self, project, action_uid: Optional[str]):
    self._hwid_db_data_manager.RegisterProjectForTest(project, project, '3',
                                                      'db data')
    opt_hwid_action_inst = HWIDActionForTest(
        action_uid) if action_uid is not None else None
    self._instance_factory.SetHWIDPreprocDataWithAction(project,
                                                        opt_hwid_action_inst)
    return opt_hwid_action_inst


if __name__ == '__main__':
  unittest.main()