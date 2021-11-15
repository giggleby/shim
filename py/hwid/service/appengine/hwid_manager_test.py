#!/usr/bin/env python3
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for HwidManager and related classes."""

import os
import tempfile
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_manager
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import file_utils


GOLDEN_HWIDV2_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v2-golden.yaml')
GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v3-golden.yaml')

TEST_V2_HWID = 'CHROMEBOOK BAKER A-A'
TEST_V3_HWID_1 = 'CHROMEBOOK AA5A-Y6L'
TEST_V3_HWID_2 = 'CHROMEBOOK AA5B-YAI'


class FakeMemcacheAdapter:

  def __init__(self):
    self._cached_data = {}

  def ClearAll(self):
    self._cached_data.clear()

  def Put(self, key, value):
    self._cached_data[key] = value

  def Get(self, key):
    return self._cached_data.get(key)


# pylint: disable=protected-access
class HwidManagerTest(unittest.TestCase):
  """Tests the HwidManager class."""

  def setUp(self):
    super().setUp()

    self.ndb_connector = ndbc_module.NDBConnector()
    self.fs_adapter = filesystem_adapter.LocalFileSystemAdapter(
        tempfile.mkdtemp())
    self.memcache_adapter = mock.Mock(memcache_adapter.MemcacheAdapter,
                                      wraps=FakeMemcacheAdapter())
    self.hwid_db_data_manager = mock.Mock(
        hwid_db_data.HWIDDBDataManager, wraps=hwid_db_data.HWIDDBDataManager(
            self.ndb_connector, self.fs_adapter))

  def tearDown(self):
    super().tearDown()
    self.hwid_db_data_manager.CleanAllForTest()

  def _GetManager(self):
    """Returns a HwidManager object, optionally loading mock data."""
    vpg_target_info = mock.Mock()
    vpg_target_info.waived_comp_categories = ['battery']
    manager = hwid_manager.HwidManager({'CHROMEBOOK': vpg_target_info},
                                       self.hwid_db_data_manager,
                                       mem_adapter=self.memcache_adapter)
    return manager

  def testGetProjects(self):
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()
    projects = manager.GetProjects()

    self.assertCountEqual(['CHROMEBOOK'], projects)

  def testGetBomInvalidFormat(self):
    """Test that an invalid HWID raises a InvalidHWIDError."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless(['CHROMEBOOK'])
    bom_configless = bc_dict['CHROMEBOOK']

    self.assertIsInstance(bom_configless.error, hwid_manager.InvalidHWIDError)

  def testGetBomNonexistentProject(self):
    """Test that a non-existent project raises a HwidNotFoundError."""
    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless(['CHROMEBOOK FOO A-A'])
    bom_configless = bc_dict['CHROMEBOOK FOO A-A']

    self.assertIsInstance(bom_configless.error,
                          hwid_manager.ProjectNotFoundError)

  def testGetBomMissingHWIDFile(self):
    """Test that when the hwid file is missing we get a
    ProjectUnavailableError."""
    self.hwid_db_data_manager.RegisterProjectForTest('CHROMEBOOK', 'CHROMEBOOK',
                                                     '2', None)

    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless(['CHROMEBOOK FOO A-A'])
    bom_configless = bc_dict['CHROMEBOOK FOO A-A']

    self.assertIsInstance(bom_configless.error,
                          hwid_manager.ProjectUnavailableError)

  def testGetBomInvalidBOM(self):
    """Test that an invalid BOM name raises a HwidNotFoundError."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()

    hwid = 'CHROMEBOOK FOO A-A'
    bc_dict = manager.BatchGetBomAndConfigless([hwid])
    self.assertIsInstance(bc_dict[hwid].error, hwid_manager.HWIDDecodeError)

  def testGetBomExistingProject(self):
    """Test that a valid HWID returns a result."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))
    manager = self._GetManager()

    bc_dict = manager.BatchGetBomAndConfigless([TEST_V2_HWID])
    bom = bc_dict[TEST_V2_HWID].bom

    self.assertIsNotNone(bom)

  def testBatchGetBomCache(self):
    """Test BatchGetBom method and check if the local hwid_data cache works."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '3',
        file_utils.ReadFile(GOLDEN_HWIDV3_FILE))

    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless([
        TEST_V3_HWID_1,
        TEST_V3_HWID_2,
    ])

    # The memcache is called once since the projects of the HWID are both
    # "CHROMEBOOK".
    # TODO(yhong): Insteading of checking if it gets the data from the cache,
    #     we should verify if `hwid_manager._HwidData` constructs only once.
    self.assertEqual(self.memcache_adapter.Get.call_count, 1)
    self.assertCountEqual([TEST_V3_HWID_1, TEST_V3_HWID_2], bc_dict)

  def testBatchGetBomData(self):
    """Test BatchGetBom and check the correctness of the data returned."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '3',
        file_utils.ReadFile(GOLDEN_HWIDV3_FILE))

    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless([
        TEST_V3_HWID_1,
        TEST_V3_HWID_2,
    ])

    bom_configless_1 = bc_dict[TEST_V3_HWID_1]
    bom1 = bom_configless_1.bom
    expected_bom1 = hwid_action.BOM()
    expected_bom1.AddAllComponents({
        'audio_codec': ['codec_1', 'hdmi_1'],
        'battery': 'battery_huge',
        'bluetooth': 'bluetooth_0',
        'camera': 'camera_0',
        'chipset': 'chipset_0',
        'cpu': 'cpu_5',
        'display_panel': 'display_panel_0',
        'dram': 'dram_0',
        'hash_gbb': 'hash_gbb_0',
        'keyboard': 'keyboard_us',
        'key_recovery': 'key_recovery_0',
        'key_root': 'key_root_0',
        'ro_ec_firmware': 'ro_ec_firmware_0',
        'ro_main_firmware': 'ro_main_firmware_0',
        'storage': 'storage_0',
    })
    self.assertIsNone(bom_configless_1.configless)
    self.assertIsNone(bom_configless_1.error)
    self.assertCountEqual(bom1.GetComponents(), expected_bom1.GetComponents())

    bom_configless_2 = bc_dict[TEST_V3_HWID_2]
    bom2 = bom_configless_2.bom
    expected_bom2 = hwid_action.BOM()
    expected_bom2.AddAllComponents({
        'audio_codec': ['codec_1', 'hdmi_1'],
        'battery': 'battery_huge',
        'bluetooth': 'bluetooth_0',
        'camera': 'camera_0',
        'chipset': 'chipset_0',
        'cpu': 'cpu_5',
        'display_panel': 'display_panel_0',
        'dram': 'dram_0',
        'hash_gbb': 'hash_gbb_0',
        'keyboard': 'keyboard_us',
        'key_recovery': 'key_recovery_0',
        'key_root': 'key_root_0',
        'ro_ec_firmware': 'ro_ec_firmware_0',
        'ro_main_firmware': 'ro_main_firmware_0',
        'storage': 'storage_1',
    })
    self.assertIsNone(bom_configless_2.configless)
    self.assertIsNone(bom_configless_2.error)
    self.assertCountEqual(bom2.GetComponents(), expected_bom2.GetComponents())

  def testGetHwidsNonExistentProject(self):
    """Test that a non-existent project raises a ProjectNotFoundError."""
    manager = self._GetManager()

    self.assertRaises(hwid_manager.ProjectNotFoundError, manager.GetHwids,
                      'CHROMEBOOK', None, None, None, None)

  def testGetHwidsExistingProject(self):
    """Test that a valid project returns a result."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()
    actual_hwids = manager.GetHwids('CHROMEBOOK', None, None, None, None)

    expected_hwids = ['BAKER', 'BAXTER', 'BLANCA', 'BRIDGE']
    self.assertCountEqual(expected_hwids, actual_hwids)

  def testGetComponentClassesNonExistentProject(self):
    """Test that a non-existent project raises a ProjectNotFoundError."""
    manager = self._GetManager()

    self.assertRaises(hwid_manager.ProjectNotFoundError,
                      manager.GetComponentClasses, 'CHROMEBOOK')

  def testGetComponentClassesExistingProject(self):
    """Test that a valid project returns a result."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()

    self.assertIn('audio_codec', manager.GetComponentClasses('CHROMEBOOK'))
    self.assertIn('cellular', manager.GetComponentClasses('CHROMEBOOK'))
    self.assertIn('keyboard', manager.GetComponentClasses('CHROMEBOOK'))
    self.assertIn('volatile_a', manager.GetComponentClasses('CHROMEBOOK'))

  def testGetComponentsNonExistentProject(self):
    """Test that a non-existent project raises a ProjectNotFoundError."""
    manager = self._GetManager()

    self.assertRaises(hwid_manager.ProjectNotFoundError, manager.GetComponents,
                      'CHROMEBOOK', None)

  def testGetComponentsExistingProject(self):
    """Test that a valid project returns a result."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()

    self.assertIn(('audio_codec', {'max98095'}),
                  list(manager.GetComponents('CHROMEBOOK', None).items()))
    self.assertIn(('cellular', {'novatel_e396_3g'}),
                  list(manager.GetComponents('CHROMEBOOK', None).items()))
    self.assertIn(('keyboard', {'kbd_us', 'kbd_gb'}),
                  list(manager.GetComponents('CHROMEBOOK', None).items()))
    self.assertIn(('volatile_a', {'test_volatile'}),
                  list(manager.GetComponents('CHROMEBOOK', None).items()))
    self.assertIn(('ro_main_firmware_0', set(['mv2#volatile_hash#test_bios'])),
                  list(manager.GetComponents('CHROMEBOOK', None).items()))

  def testCache(self):
    """Test that caching limits the number of files read to one."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()
    self.assertIsNotNone(
        manager.BatchGetBomAndConfigless([TEST_V2_HWID])[TEST_V2_HWID].bom)
    self.assertIsNotNone(
        manager.BatchGetBomAndConfigless([TEST_V2_HWID])[TEST_V2_HWID].bom)
    self.assertIsNotNone(
        manager.BatchGetBomAndConfigless([TEST_V2_HWID])[TEST_V2_HWID].bom)

    self.assertEqual(self.hwid_db_data_manager.LoadHWIDDB.call_count, 1)

  def testInvalidVersion(self):
    self.hwid_db_data_manager.RegisterProjectForTest('CHROMEBOOK', 'CHROMEBOOK',
                                                     '10', 'junk data')

    manager = self._GetManager()

    bc_dict = manager.BatchGetBomAndConfigless(['CHROMEBOOK FOOBAR'])
    bom_configless = bc_dict['CHROMEBOOK FOOBAR']

    self.assertIsInstance(bom_configless.error,
                          hwid_manager.ProjectNotSupportedError)

  def testReloadCache(self):
    """Test that reloading re-reads the data."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))
    manager = self._GetManager()
    self.assertIsNone(manager.GetHWIDPreprocDataFromCache('CHROMEBOOK'))

    manager.ReloadMemcacheCacheFromFiles()

    self.assertIsNotNone(manager.GetHWIDPreprocDataFromCache('CHROMEBOOK'))
    self.assertEqual(self.hwid_db_data_manager.LoadHWIDDB.call_count, 1)


class NormalizationTest(unittest.TestCase):
  """Tests the _NormalizeString function."""

  def testNormalization(self):
    self.assertEqual('ALPHA', hwid_manager._NormalizeString('alpha'))
    self.assertEqual('ALPHA', hwid_manager._NormalizeString('aLpHa'))
    self.assertEqual('ALPHA', hwid_manager._NormalizeString('ALPHA'))
    self.assertEqual('ALPHA', hwid_manager._NormalizeString('  alpha  '))
    self.assertEqual('BETA', hwid_manager._NormalizeString('beta'))


if __name__ == '__main__':
  unittest.main()
