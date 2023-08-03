#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.log_extractor import soc_log_utils


class SocLogUtilsTest(unittest.TestCase):

  def testIntelParseBlutooth(self):
    TEST_STR = (
        'kernel: [    2.691456] Bluetooth: btintel_prepare_fw_download_tlv() '
        'hci0: Found device firmware: intel/ibt-0040-0041.sfi')
    parsed_info = soc_log_utils.IntelFWParser().Parse(TEST_STR)
    self.assertEqual('Bluetooth', parsed_info.component)
    self.assertEqual(1, len(parsed_info.info))
    self.assertEqual('intel/ibt-0040-0041.sfi', parsed_info.info['binary'])

  def testIntelParseGPU_GUC(self):
    TEST_STR = (
        'kernel: [    0.558193] i915 0000:00:02.0: [drm] GuC firmware i915'
        '/adlp_guc_62.0.3.bin version 62.0 submission:disabled')
    parsed_info = soc_log_utils.IntelFWParser().Parse(TEST_STR)
    self.assertEqual('GPU', parsed_info.component)
    self.assertEqual(3, len(parsed_info.info))
    self.assertEqual('GuC', parsed_info.info['name'])
    self.assertEqual('adlp_guc_62.0.3.bin', parsed_info.info['binary'])
    self.assertEqual('62.0', parsed_info.info['version'])

  def testIntelParseGPU_HUC(self):
    TEST_STR = (
        'kernel: [    0.558218] i915 0000:00:02.0: [drm] HuC firmware i915'
        '/tgl_huc_7.9.3.bin version 7.9 authenticated:yes')
    parsed_info = soc_log_utils.IntelFWParser().Parse(TEST_STR)
    self.assertEqual('GPU', parsed_info.component)
    self.assertEqual(3, len(parsed_info.info))
    self.assertEqual('HuC', parsed_info.info['name'])
    self.assertEqual('tgl_huc_7.9.3.bin', parsed_info.info['binary'])
    self.assertEqual('7.9', parsed_info.info['version'])

  def testIntelParseGPU_DMC(self):
    TEST_STR = (
        'kernel: [    1.977744] i915 0000:00:02.0: [drm] Finished loading '
        'DMC firmware i915/adlp_dmc_ver2_14.bin (v2.14)')
    parsed_info = soc_log_utils.IntelFWParser().Parse(TEST_STR)
    self.assertEqual('GPU', parsed_info.component)
    self.assertEqual(3, len(parsed_info.info))
    self.assertEqual('DMC', parsed_info.info['name'])
    self.assertEqual('adlp_dmc_ver2_14.bin', parsed_info.info['binary'])
    self.assertEqual('2.14', parsed_info.info['version'])

  def testIntelParseSof(self):
    TEST_STR = ('kernel: [    5.442116] sof-audio-pci-intel-tgl 0000:00:1f.3: '
                'Firmware info: version 2:0:0-1153b')
    parsed_info = soc_log_utils.IntelFWParser().Parse(TEST_STR)
    self.assertEqual('Sof', parsed_info.component)
    self.assertEqual(1, len(parsed_info.info))
    self.assertEqual('2:0:0-1153b', parsed_info.info['version'])

  def testIntelParseWifi(self):
    TEST_STR = (
        'kernel: [    5.001250] iwlwifi 0000:00:14.3: loaded firmware version '
        '73.35c0a2c6.0 so-a0-gf-a0-73.ucode op_mode iwlmvm')

    parsed_info = soc_log_utils.IntelFWParser().Parse(TEST_STR)
    self.assertEqual('Wifi', parsed_info.component)
    self.assertEqual(1, len(parsed_info.info))
    self.assertEqual('73.35c0a2c6.0', parsed_info.info['binary'])


if __name__ == '__main__':
  unittest.main()
