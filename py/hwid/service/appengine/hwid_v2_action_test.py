#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_v2_action
from cros.factory.utils import file_utils


GOLDEN_HWIDV2_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v2-golden.yaml')

TEST_V2_HWID = 'CHROMEBOOK BAKER A-A'
TEST_V2_HWID_NO_VAR = 'CHROMEBOOK BAKER'


class HWIDV2ActionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    self.preproc_data = hwid_preproc_data.HWIDV2PreprocData(
        'CHROMEBOOK', file_utils.ReadFile(GOLDEN_HWIDV2_FILE))
    self.action = hwid_v2_action.HWIDV2Action(self.preproc_data)

  def testGetBOMAndConfigless(self):
    """Tests fetching a BOM."""
    bom, configless = self.action.GetBOMAndConfigless(TEST_V2_HWID)

    self.assertTrue(bom.HasComponent(hwid_action.Component('chipset', 'snow')))
    self.assertTrue(
        bom.HasComponent(hwid_action.Component('keyboard', 'kbd_us')))
    self.assertTrue(
        bom.HasComponent(hwid_action.Component('volatile_a', 'test_volatile')))

    bom, configless = self.action.GetBOMAndConfigless(TEST_V2_HWID_NO_VAR)

    self.assertTrue(bom.HasComponent(hwid_action.Component('chipset', 'snow')))
    self.assertEqual([], bom.GetComponents('keyboard'))
    self.assertNotIn([], bom.GetComponents('volatile_a'))
    self.assertEqual(None, configless)

    self.assertRaises(hwid_action.InvalidHWIDError,
                      self.action.GetBOMAndConfigless, 'NOTCHROMEBOOK HWID')

    self.assertRaises(hwid_action.HWIDDecodeError,
                      self.action.GetBOMAndConfigless,
                      TEST_V2_HWID_NO_VAR + ' FOO')
    self.assertRaises(hwid_action.HWIDDecodeError,
                      self.action.GetBOMAndConfigless,
                      TEST_V2_HWID_NO_VAR + ' A-FOO')

    self.assertEqual('CHROMEBOOK', bom.project)

  def testEnumerateHWIDs(self):
    """Tests fetching all HWIDS for a project."""
    hwids = self.action.EnumerateHWIDs(None, None, None, None)

    self.assertIsNotNone(hwids)
    self.assertEqual(4, len(hwids))
    self.assertIn('BAKER', hwids)
    self.assertIn('BRIDGE', hwids)

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
      self.assertEqual(hwids, self.action.EnumerateHWIDs(**filters))

  def testGetComponentClasses(self):
    """Tests fetching all component classes for a project."""
    classes = self.action.GetComponentClasses()

    self.assertIsNotNone(classes)
    self.assertEqual(17, len(classes))
    self.assertIn('audio_codec', classes)
    self.assertIn('cellular', classes)
    self.assertIn('keyboard', classes)
    self.assertIn('volatile_a', classes)

  def testGetComponents(self):
    """Tests fetching all components for a project."""
    components = self.action.GetComponents()

    self.assertIn(('audio_codec', set(['max98095'])), list(components.items()))
    self.assertIn(('cellular', set(['novatel_e396_3g'])),
                  list(components.items()))
    self.assertIn(('keyboard', set(['kbd_us', 'kbd_gb'])),
                  list(components.items()))
    self.assertIn(('volatile_a', set(['test_volatile'])),
                  list(components.items()))
    self.assertIn(('ro_main_firmware_0', set(['mv2#volatile_hash#test_bios'])),
                  list(components.items()))

    # Test with_classes filter
    components = {
        'flash_chip': {'gigadevice_gd25lq32', 'winbond_w25q32dw'}
    }
    self.assertEqual(components,
                     self.action.GetComponents(with_classes={'flash_chip'}))
    components = {
        'flash_chip': {'gigadevice_gd25lq32', 'winbond_w25q32dw'},
        'keyboard': {'kbd_us', 'kbd_gb'}
    }
    self.assertEqual(
        components,
        self.action.GetComponents(with_classes={'flash_chip', 'keyboard'}))

    # Test classes with multiple components
    components = {
        'usb_hosts': {
            'exynos_snow0', 'exynos_snow1', 'exynos_snow2', 'exynos_snow3'
        }
    }
    self.assertEqual(components,
                     self.action.GetComponents(with_classes={'usb_hosts'}))


if __name__ == '__main__':
  unittest.main()
