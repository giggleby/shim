#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_v3_action
from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module
from cros.factory.hwid.v3 import rule as v3_rule
from cros.factory.utils import file_utils

GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v3-golden.yaml')
TEST_V3_HWID_1 = 'CHROMEBOOK AA5A-Y6L'
TEST_V3_HWID_WITH_CONFIGLESS = 'CHROMEBOOK-BRAND 0-8-74-180 AA5C-YNQ'


class HWIDV3ActionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    self.preproc_data = hwid_preproc_data.HWIDV3PreprocData(
        'CHROMEBOOK', file_utils.ReadFile(GOLDEN_HWIDV3_FILE), 'COMMIT-ID')
    self.action = hwid_v3_action.HWIDV3Action(self.preproc_data)

  def testGetBOM(self):
    """Tests fetching a BOM."""
    bom, configless = self.action.GetBOMAndConfigless(TEST_V3_HWID_1)

    self.assertIn(
        hwid_action.Component('chipset', 'chipset_0'),
        bom.GetComponents('chipset'))
    self.assertIn(
        hwid_action.Component('keyboard', 'keyboard_us'),
        bom.GetComponents('keyboard'))
    self.assertIn(
        hwid_action.Component('dram', 'dram_0'), bom.GetComponents('dram'))
    self.assertEqual('EVT', bom.phase)
    self.assertEqual('CHROMEBOOK', bom.project)
    self.assertEqual(None, configless)

    self.assertRaises(hwid_action.InvalidHWIDError,
                      self.action.GetBOMAndConfigless, 'NOTCHROMEBOOK HWID')

  def testGetBOMWithConfigless(self):
    """Tests fetching a BOM."""
    bom, configless = self.action.GetBOMAndConfigless(
        TEST_V3_HWID_WITH_CONFIGLESS)

    self.assertIn(
        hwid_action.Component('chipset', 'chipset_0'),
        bom.GetComponents('chipset'))
    self.assertIn(
        hwid_action.Component('keyboard', 'keyboard_us'),
        bom.GetComponents('keyboard'))
    self.assertIn(
        hwid_action.Component('dram', 'dram_0'), bom.GetComponents('dram'))
    self.assertEqual('EVT', bom.phase)
    self.assertIn(
        hwid_action.Component('storage', 'storage_2',
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
                'is_rma_device': 0,
            },
        }, configless)

    self.assertRaises(hwid_action.InvalidHWIDError,
                      self.action.GetBOMAndConfigless, 'NOTCHROMEBOOK HWID')

  def testGetBOMWithVerboseFlag(self):
    """Test BatchGetBom with the detail fields returned."""
    bom, configless = self.action.GetBOMAndConfigless(TEST_V3_HWID_1,
                                                      verbose=True)

    self.assertIsNone(configless)

    dram = bom.GetComponents(cls='dram')
    self.assertSequenceEqual(dram, [
        hwid_action.Component('dram', 'dram_0', fields={
            'part': 'part0',
            'size': '4G'
        })
    ])

    audio_codec = bom.GetComponents(cls='audio_codec')
    self.assertSequenceEqual(audio_codec, [
        hwid_action.Component('audio_codec', 'codec_1',
                              fields={'compact_str': 'Codec 1'}),
        hwid_action.Component('audio_codec', 'hdmi_1',
                              fields={'compact_str': 'HDMI 1'}),
    ])

    storage = bom.GetComponents(cls='storage')
    self.assertSequenceEqual(storage, [
        hwid_action.Component(
            'storage', 'storage_0', fields={
                'model': 'model0',
                'sectors': '0',
                'vendor': 'vendor0',
                'serial': v3_rule.Value(r'^#123\d+$', is_re=True)
            })
    ])

  def testGetBOMAndConfiglessWithVpgWaivedComponentCategory(self):
    vpg_config = vpg_config_module.VerificationPayloadGeneratorConfig.Create(
        waived_comp_categories=['battery'])
    bom, unused_configless = self.action.GetBOMAndConfigless(
        TEST_V3_HWID_1, require_vp_info=True, vpg_config=vpg_config)

    for comp in bom.GetComponents(cls='battery'):
      self.assertFalse(comp.is_vp_related)

    for comp in bom.GetComponents(cls='storage'):
      self.assertTrue(comp.is_vp_related)


if __name__ == '__main__':
  unittest.main()
