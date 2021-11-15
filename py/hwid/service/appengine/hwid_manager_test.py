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
from cros.factory.hwid.service.appengine import hwid_manager
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.hwid.v3 import rule
from cros.factory.utils import file_utils


GOLDEN_HWIDV2_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v2-golden.yaml')
GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v3-golden.yaml')

GOLDEN_HWIDV2_DATA = file_utils.ReadFile(GOLDEN_HWIDV2_FILE, encoding=None)

TEST_V2_HWID = 'CHROMEBOOK BAKER A-A'
TEST_V2_HWID_NO_VAR = 'CHROMEBOOK BAKER'
TEST_V2_HWID_NO_VOL = 'CHROMEBOOK BAKER A'
TEST_V2_HWID_ONE_DASH = 'CHROMEBOOK BAKER-ALFA A-A'
TEST_V2_HWID_ONE_DASH_NO_VAR = 'CHROMEBOOK BAKER-ALFA'
TEST_V2_HWID_ONE_DASH_NO_VOL = 'CHROMEBOOK BAKER-ALFA A'
TEST_V2_HWID_TWO_DASH = 'CHROMEBOOK BAKER-ALFA-BETA A-A'
TEST_V2_HWID_TWO_DASH_NO_VAR = 'CHROMEBOOK BAKER-ALFA-BETA'
TEST_V2_HWID_TWO_DASH_NO_VOL = 'CHROMEBOOK BAKER-ALFA-BETA A'
TEST_V3_HWID_1 = 'CHROMEBOOK AA5A-Y6L'
TEST_V3_HWID_2 = 'CHROMEBOOK AA5B-YAI'
TEST_V3_HWID_WITH_CONFIGLESS = 'CHROMEBOOK-BRAND 0-8-74-180 AA5C-YNQ'


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
    """Test that an invalid HWID raises a InvalidHwidError."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '2',
        file_utils.ReadFile(GOLDEN_HWIDV2_FILE))

    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless(['CHROMEBOOK'])
    bom_configless = bc_dict['CHROMEBOOK']

    self.assertIsInstance(bom_configless.error, hwid_manager.InvalidHwidError)

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
    self.assertIsInstance(bc_dict[hwid].error, hwid_manager.HwidNotFoundError)

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
    expected_bom1 = hwid_manager.Bom()
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
    expected_bom2 = hwid_manager.Bom()
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

  def testGetBomWithVerboseFlag(self):
    """Test BatchGetBom with the detail fields returned."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '3',
        file_utils.ReadFile(GOLDEN_HWIDV3_FILE))

    manager = self._GetManager()
    bc_dict = manager.BatchGetBomAndConfigless([TEST_V3_HWID_1], verbose=True)
    bom_configless = bc_dict[TEST_V3_HWID_1]
    bom = bom_configless.bom

    self.assertIsNone(bom_configless.configless)

    dram = bom.GetComponents(cls='dram')
    self.assertSequenceEqual(dram, [
        hwid_manager.Component('dram', 'dram_0', fields={
            'part': 'part0',
            'size': '4G'
        })
    ])

    audio_codec = bom.GetComponents(cls='audio_codec')
    self.assertSequenceEqual(audio_codec, [
        hwid_manager.Component('audio_codec', 'codec_1',
                               fields={'compact_str': 'Codec 1'}),
        hwid_manager.Component('audio_codec', 'hdmi_1',
                               fields={'compact_str': 'HDMI 1'}),
    ])

    storage = bom.GetComponents(cls='storage')
    self.assertSequenceEqual(storage, [
        hwid_manager.Component(
            'storage', 'storage_0', fields={
                'model': 'model0',
                'sectors': '0',
                'vendor': 'vendor0',
                'serial': rule.Value(r'^#123\d+$', is_re=True)
            })
    ])

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
    self.assertIsNone(manager.GetProjectDataFromCache('CHROMEBOOK'))

    manager.ReloadMemcacheCacheFromFiles()

    self.assertIsNotNone(manager.GetProjectDataFromCache('CHROMEBOOK'))
    self.assertEqual(self.hwid_db_data_manager.LoadHWIDDB.call_count, 1)

  def testGetBomAndConfiglessWithVpgWaivedComponentCategory(self):
    """Test if GetBomAndConfigless follows the waived_comp_categories defined in
    vpg_targets."""
    self.hwid_db_data_manager.RegisterProjectForTest(
        'CHROMEBOOK', 'CHROMEBOOK', '3',
        file_utils.ReadFile(GOLDEN_HWIDV3_FILE))

    manager = self._GetManager()

    bc_dict = manager.BatchGetBomAndConfigless([TEST_V3_HWID_1],
                                               require_vp_info=True)
    bom = bc_dict[TEST_V3_HWID_1].bom

    for comp in bom.GetComponents(cls='battery'):
      self.assertFalse(comp.is_vp_related)

    for comp in bom.GetComponents(cls='storage'):
      self.assertTrue(comp.is_vp_related)


class HwidDataTest(unittest.TestCase):
  """Tests the _HwidData class."""

  def setUp(self):
    super(HwidDataTest, self).setUp()
    self.data = hwid_manager._HwidData()

  def testNoConfig(self):
    self.assertRaises(hwid_manager.ProjectUnavailableError, self.data._Seed)

  def testSeedWithFile(self):
    with mock.patch.object(self.data, '_SeedFromRawYaml') as _mock:
      self.data._Seed(hwid_file=GOLDEN_HWIDV2_FILE)
    _mock.assert_called_once_with(mock.ANY)

  def testSeedWithBadFile(self):
    self.assertRaises(hwid_manager.ProjectUnavailableError, self.data._Seed,
                      hwid_file='non/existent/file')

  def testSeedWithString(self):
    with mock.patch.object(self.data, '_SeedFromRawYaml') as _mock:
      self.data._Seed(raw_hwid_yaml='{}')
    _mock.assert_called_once_with('{}')

  def testSeedWithData(self):
    with mock.patch.object(self.data, '_SeedFromData') as _mock:
      self.data._Seed(hwid_data={'foo': 'bar'})
    _mock.assert_called_once_with({'foo': 'bar'})

  def testUnimplemented(self):
    self.assertRaises(NotImplementedError, self.data._SeedFromData, None)
    self.assertRaises(NotImplementedError, self.data.GetBomAndConfigless, None)
    self.assertRaises(NotImplementedError, self.data.GetHwids, None, None, None,
                      None, None)
    self.assertRaises(NotImplementedError, self.data.GetComponentClasses, None)
    self.assertRaises(NotImplementedError, self.data.GetComponents, None, None)


class HwidV2DataTest(unittest.TestCase):
  """Tests the HwidV2Data class."""

  def setUp(self):
    super(HwidV2DataTest, self).setUp()

    self.data = self._LoadFromGoldenFile()

  def _LoadFromGoldenFile(self):
    return hwid_manager._HwidV2Data('CHROMEBOOK', hwid_file=GOLDEN_HWIDV2_FILE)

  def testSplitHwid(self):
    """Tests HWIDv2 splitting."""

    # Test HWIDs with no dashes in the name
    self.assertEqual(('CHROMEBOOK', 'BAKER', None, None),
                     self.data._SplitHwid(TEST_V2_HWID_NO_VAR))
    self.assertEqual(('CHROMEBOOK', 'BAKER', 'A', None),
                     self.data._SplitHwid(TEST_V2_HWID_NO_VOL))
    self.assertEqual(('CHROMEBOOK', 'BAKER', 'A', 'A'),
                     self.data._SplitHwid(TEST_V2_HWID))

    self.assertRaises(hwid_manager.InvalidHwidError, self.data._SplitHwid, '')
    self.assertRaises(hwid_manager.InvalidHwidError, self.data._SplitHwid,
                      'FOO')

    # Test HWIDs with one dash in the name
    self.assertEqual(('CHROMEBOOK', 'BAKER-ALFA', None, None),
                     self.data._SplitHwid(TEST_V2_HWID_ONE_DASH_NO_VAR))
    self.assertEqual(('CHROMEBOOK', 'BAKER-ALFA', 'A', None),
                     self.data._SplitHwid(TEST_V2_HWID_ONE_DASH_NO_VOL))
    self.assertEqual(('CHROMEBOOK', 'BAKER-ALFA', 'A', 'A'),
                     self.data._SplitHwid(TEST_V2_HWID_ONE_DASH))

    # Test HWIDs with two dashes in the name
    self.assertEqual(('CHROMEBOOK', 'BAKER-ALFA-BETA', None, None),
                     self.data._SplitHwid(TEST_V2_HWID_TWO_DASH_NO_VAR))
    self.assertEqual(('CHROMEBOOK', 'BAKER-ALFA-BETA', 'A', None),
                     self.data._SplitHwid(TEST_V2_HWID_TWO_DASH_NO_VOL))
    self.assertEqual(('CHROMEBOOK', 'BAKER-ALFA-BETA', 'A', 'A'),
                     self.data._SplitHwid(TEST_V2_HWID_TWO_DASH))

  def testInvalidSeedData(self):
    """Tests that loading invalid data throws an error."""

    self.assertRaises(hwid_manager.ProjectUnavailableError,
                      hwid_manager._HwidV2Data, 'CHROMEBOOK',
                      raw_hwid_yaml='{}')

  def testGetBom(self):
    """Tests fetching a BOM."""
    bom, configless = self.data.GetBomAndConfigless(TEST_V2_HWID)

    self.assertTrue(bom.HasComponent(hwid_manager.Component('chipset', 'snow')))
    self.assertTrue(
        bom.HasComponent(hwid_manager.Component('keyboard', 'kbd_us')))
    self.assertTrue(
        bom.HasComponent(hwid_manager.Component('volatile_a', 'test_volatile')))

    bom, configless = self.data.GetBomAndConfigless(TEST_V2_HWID_NO_VAR)

    self.assertTrue(bom.HasComponent(hwid_manager.Component('chipset', 'snow')))
    self.assertEqual([], bom.GetComponents('keyboard'))
    self.assertNotIn([], bom.GetComponents('volatile_a'))
    self.assertEqual(None, configless)

    self.assertRaises(hwid_manager.ProjectMismatchError,
                      self.data.GetBomAndConfigless, 'NOTCHROMEBOOK HWID')

    self.assertRaises(hwid_manager.HwidNotFoundError,
                      self.data.GetBomAndConfigless,
                      TEST_V2_HWID_NO_VAR + ' FOO')
    self.assertRaises(hwid_manager.HwidNotFoundError,
                      self.data.GetBomAndConfigless,
                      TEST_V2_HWID_NO_VAR + ' A-FOO')

    self.assertEqual('CHROMEBOOK', bom.project)

  def testGetHwids(self):
    """Tests fetching all HWIDS for a project."""
    hwids = self.data.GetHwids('CHROMEBOOK', None, None, None, None)

    self.assertIsNotNone(hwids)
    self.assertEqual(4, len(hwids))
    self.assertIn('BAKER', hwids)
    self.assertIn('BRIDGE', hwids)

    self.assertRaises(hwid_manager.ProjectMismatchError, self.data.GetHwids,
                      'NOTCHROMEBOOK HWID', None, None, None, None)

    test_cases = [({'BAKER', 'BAXTER', 'BLANCA'}, {
        'with_classes': {'volatile_a'}
    }), ({'BLANCA', 'BRIDGE'}, {
        'with_classes': {'cellular'}
    }), ({'BRIDGE'}, {
        'without_classes': {'volatile_a'}
    }), ({'BAKER', 'BAXTER'}, {
        'without_classes': {'cellular'}
    }), ({'BAXTER', 'BRIDGE'}, {
        'with_components': {'winbond_w25q32dw'}
    }), ({'BAKER', 'BLANCA'}, {
        'without_components': {'winbond_w25q32dw'}
    }),
                  ({'BRIDGE'}, {
                      'with_classes': {'cellular'},
                      'with_components': {'winbond_w25q32dw'}
                  }),
                  ({'BAKER'}, {
                      'without_classes': {'cellular'},
                      'without_components': {'winbond_w25q32dw'}
                  }),
                  ({'BLANCA'}, {
                      'with_classes': {'cellular'},
                      'without_components': {'winbond_w25q32dw'}
                  }),
                  ({'BAXTER'}, {
                      'without_classes': {'cellular'},
                      'with_components': {'winbond_w25q32dw'}
                  }), (set(), {
                      'with_classes': {'FAKE_CLASS'}
                  }),
                  ({'BAKER', 'BAXTER', 'BLANCA', 'BRIDGE'}, {
                      'without_classes': {'FAKE_CLASS'}
                  }), (set(), {
                      'with_components': {'FAKE_COMPONENT'}
                  }),
                  ({'BAKER', 'BAXTER', 'BLANCA', 'BRIDGE'}, {
                      'without_components': {'FAKE_COMPONENT'}
                  }),
                  ({'BAKER', 'BAXTER'}, {
                      'with_components': {'exynos_snow0'}
                  }),
                  ({'BAKER', 'BLANCA'}, {
                      'with_components': {'exynos_snow1'}
                  }),
                  ({'BAKER'}, {
                      'with_components': {'exynos_snow0', 'exynos_snow1'}
                  })]

    for hwids, filters in test_cases:
      self.assertEqual(hwids, self.data.GetHwids('CHROMEBOOK', **filters))

  def testGetComponentClasses(self):
    """Tests fetching all component classes for a project."""
    classes = self.data.GetComponentClasses('CHROMEBOOK')

    self.assertIsNotNone(classes)
    self.assertEqual(17, len(classes))
    self.assertIn('audio_codec', classes)
    self.assertIn('cellular', classes)
    self.assertIn('keyboard', classes)
    self.assertIn('volatile_a', classes)

    self.assertRaises(hwid_manager.ProjectMismatchError,
                      self.data.GetComponentClasses, 'NOTCHROMEBOOK HWID')

  def testGetComponents(self):
    """Tests fetching all components for a project."""
    components = self.data.GetComponents('CHROMEBOOK')

    self.assertIn(('audio_codec', set(['max98095'])), list(components.items()))
    self.assertIn(('cellular', set(['novatel_e396_3g'])),
                  list(components.items()))
    self.assertIn(('keyboard', set(['kbd_us', 'kbd_gb'])),
                  list(components.items()))
    self.assertIn(('volatile_a', set(['test_volatile'])),
                  list(components.items()))
    self.assertIn(('ro_main_firmware_0', set(['mv2#volatile_hash#test_bios'])),
                  list(components.items()))

    self.assertRaises(hwid_manager.ProjectMismatchError,
                      self.data.GetComponentClasses, 'NOTCHROMEBOOK HWID')

    # Test with_classes filter
    components = {
        'flash_chip': {'gigadevice_gd25lq32', 'winbond_w25q32dw'}
    }
    self.assertEqual(
        components,
        self.data.GetComponents('CHROMEBOOK', with_classes={'flash_chip'}))
    components = {
        'flash_chip': {'gigadevice_gd25lq32', 'winbond_w25q32dw'},
        'keyboard': {'kbd_us', 'kbd_gb'}
    }
    self.assertEqual(
        components,
        self.data.GetComponents('CHROMEBOOK',
                                with_classes={'flash_chip', 'keyboard'}))

    # Test classes with multiple components
    components = {
        'usb_hosts': {
            'exynos_snow0', 'exynos_snow1', 'exynos_snow2', 'exynos_snow3'
        }
    }
    self.assertEqual(
        components,
        self.data.GetComponents('CHROMEBOOK', with_classes={'usb_hosts'}))


class HwidV3DataTest(unittest.TestCase):
  """Tests the HwidV3Data class."""

  def setUp(self):
    super(HwidV3DataTest, self).setUp()
    self.data = self._LoadFromGoldenFile()

  def _LoadFromGoldenFile(self):
    return hwid_manager._HwidV3Data('CHROMEBOOK', hwid_file=GOLDEN_HWIDV3_FILE)

  def testGetBom(self):
    """Tests fetching a BOM."""
    bom, configless = self.data.GetBomAndConfigless(TEST_V3_HWID_1)

    self.assertIn(
        hwid_manager.Component('chipset', 'chipset_0'),
        bom.GetComponents('chipset'))
    self.assertIn(
        hwid_manager.Component('keyboard', 'keyboard_us'),
        bom.GetComponents('keyboard'))
    self.assertIn(
        hwid_manager.Component('dram', 'dram_0'), bom.GetComponents('dram'))
    self.assertEqual('EVT', bom.phase)
    self.assertEqual('CHROMEBOOK', bom.project)
    self.assertEqual(None, configless)

    self.assertRaises(hwid_manager.HwidNotFoundError,
                      self.data.GetBomAndConfigless, 'NOTCHROMEBOOK HWID')

  def testGetBomWithConfigless(self):
    """Tests fetching a BOM."""
    bom, configless = self.data.GetBomAndConfigless(
        TEST_V3_HWID_WITH_CONFIGLESS)

    self.assertIn(
        hwid_manager.Component('chipset', 'chipset_0'),
        bom.GetComponents('chipset'))
    self.assertIn(
        hwid_manager.Component('keyboard', 'keyboard_us'),
        bom.GetComponents('keyboard'))
    self.assertIn(
        hwid_manager.Component('dram', 'dram_0'), bom.GetComponents('dram'))
    self.assertEqual('EVT', bom.phase)
    self.assertIn(
        hwid_manager.Component('storage', 'storage_2',
                               {"comp_group": "storage_0"}),
        bom.GetComponents('storage'))
    self.assertEqual('CHROMEBOOK', bom.project)
    self.assertEqual(
        {
            'version': 0,
            'memory': 8,
            'storage': 116,
            'feature_list': {
                'has_fingerprint': 0,
                'has_front_camera': 0,
                'has_rear_camera': 0,
                'has_stylus': 0,
                'has_touchpad': 0,
                'has_touchscreen': 1,
                'is_convertible': 0,
                'is_rma_device': 0
            }
        }, configless)

    self.assertRaises(hwid_manager.HwidNotFoundError,
                      self.data.GetBomAndConfigless, 'NOTCHROMEBOOK HWID')

  def testGetHwids(self):
    self.assertRaises(NotImplementedError, self.data.GetHwids,
                      'NOTCHROMEBOOK HWID', None, None, None, None)

  def testGetComponentClasses(self):
    self.assertRaises(NotImplementedError, self.data.GetComponentClasses,
                      'NOTCHROMEBOOK HWID')

  def testGetComponents(self):
    self.assertRaises(NotImplementedError, self.data.GetComponents,
                      'NOTCHROMEBOOK HWID', None)


class ComponentTest(unittest.TestCase):
  """Tests the Component class."""

  def testEquality(self):
    self.assertEqual(
        hwid_manager.Component('foo', 'bar'),
        hwid_manager.Component('foo', 'bar'))
    self.assertEqual(
        hwid_manager.Component(
            'foo', 'bar', fields={
                'f1': 'v1',
                'f2': 'v2',
                'f3': rule.Value(r'\d+$', is_re=True)
            }),
        hwid_manager.Component(
            'foo', 'bar', fields={
                'f1': 'v1',
                'f2': 'v2',
                'f3': rule.Value(r'\d+$', is_re=True)
            }))


class BomTest(unittest.TestCase):
  """Tests the Bom class."""

  def setUp(self):
    super(BomTest, self).setUp()
    self.bom = hwid_manager.Bom()

  def testComponentsAddNoneClass(self):
    self.bom.AddComponent(None, 'foo')
    self._AssertHasComponent(None, 'foo')

  def testComponentsAddNone(self):
    self.bom.AddComponent('foo', None)
    self.bom.AddComponent('foo', None)
    self.bom.AddComponent('foo', None)
    self._AssertHasComponent('foo', None)

  def testComponentsOverrideNone(self):
    self.bom.AddComponent('foo', None)
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('foo', None)

    self._AssertHasComponent('foo', 'bar')

  def testComponentsAppend(self):
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('foo', 'baz')

    self._AssertHasComponent('foo', 'bar')
    self._AssertHasComponent('foo', 'baz')

  def testMultipleComponents(self):
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('baz', 'qux')

    self._AssertHasComponent('foo', 'bar')
    self._AssertHasComponent('baz', 'qux')

  def testAddAllComponents(self):
    self.bom.AddAllComponents({
        'foo': 'bar',
        'baz': ['qux', 'rox']
    })

    self._AssertHasComponent('foo', 'bar')
    self._AssertHasComponent('baz', 'qux')
    self._AssertHasComponent('baz', 'rox')

  def testAddAllComponentsWithInfo(self):
    data = hwid_manager._HwidV3Data('CHROMEBOOK', hwid_file=GOLDEN_HWIDV3_FILE)
    self.bom.AddAllComponents({'storage': ['storage_2']}, data.database)
    comp = self.bom.GetComponents('storage')[0]
    self.assertEqual('storage_0', comp.information['comp_group'])

  def testAddAllComponentsWithFields(self):
    data = hwid_manager._HwidV3Data('CHROMEBOOK', hwid_file=GOLDEN_HWIDV3_FILE)
    self.bom.AddAllComponents({'storage': ['storage_1']}, data.database, True)
    comp, = self.bom.GetComponents('storage')
    self.assertEqual(
        {
            'model': 'model1',
            'sectors': '100',
            'vendor': 'vendor1',
            'serial': rule.Value(r'^#123\d+$', is_re=True)
        }, comp.fields)

  def testGetComponents(self):
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('baz', 'qux')
    self.bom.AddComponent('baz', 'rox')
    self.bom.AddComponent('zib', None)

    components = self.bom.GetComponents()

    self.assertEqual(4, len(components))
    self.assertIn(hwid_manager.Component('foo', 'bar'), components)
    self.assertIn(hwid_manager.Component('baz', 'qux'), components)
    self.assertIn(hwid_manager.Component('baz', 'rox'), components)
    self.assertIn(hwid_manager.Component('zib', None), components)

    self.assertEqual([hwid_manager.Component('foo', 'bar')],
                     self.bom.GetComponents('foo'))
    self.assertEqual([], self.bom.GetComponents('empty-class'))

  def _AssertHasComponent(self, cls, name):
    self.assertIn(cls, self.bom._components)
    if name:
      self.assertIn(name, (comp.name for comp in self.bom._components[cls]))
    else:
      self.assertEqual([], self.bom._components[cls])


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
