#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data.converter import converter_test_utils
from cros.factory.hwid.service.appengine.data.converter import pcie_emmc_storage_bridge_converter
from cros.factory.hwid.v3 import contents_analyzer


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class PCIEMMCStorageBridgeConverterTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._converter_collection = (
        pcie_emmc_storage_bridge_converter.GetConverterCollection())

  def testMatchStorageBridgeAligned(self):
    comp_values = {
        'pci_vendor_id': '0x1234',
        'pci_device_id': '0x5678',
        'pci_class': '0x010802',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'pci_vendor_id': '0x1234',
        'pci_device_id': '0x5678',
        'pci_class': '0x010802',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)


if __name__ == '__main__':
  unittest.main()
