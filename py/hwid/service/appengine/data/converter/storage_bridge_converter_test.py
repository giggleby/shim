#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data.converter import converter as converter_module
from cros.factory.hwid.service.appengine.data.converter import converter_test_utils
from cros.factory.hwid.service.appengine.data.converter import storage_bridge_converter
from cros.factory.hwid.v3 import contents_analyzer


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class StorageConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._converter_collection = (
        storage_bridge_converter.GetConverterCollection())

  def testMatchStorageAssemblyAsNVMeAligned(self):
    comp_values = {
        'nvme_model': 'MODEL ABCXYZ',
        'pci_class': '0x010802',
        'pci_vendor': '0x1234',
        'pci_device': '0x5678',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'bridge_pcie_class': '0x010802',
        'bridge_pcie_vendor': '0x1234',
        'bridge_pcie_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        converter_module.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED, 'storage_assembly_as_nvme'), result)

  def testMatchStorageAssemblyWithBridgeAligned(self):
    comp_values = {
        'device': '0x1234',
        'vendor': '0x5678',
        'name': 'AAABBB',
        'manfid': '0x000015',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'mmc_name': '0x414141424242',
        'mmc_manfid': '0x15',
        'bridge_pcie_device': '0x1234',
        'bridge_pcie_vendor': '0x5678',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        converter_module.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED, 'storage_assembly_with_bridge'), result)

  def testMatchStorageAssemblyBridgeOnlyAligned(self):
    comp_values = {
        'vendor': '0x1234',
        'device': '0x5678',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'pci_vendor_id': '0x1234',
        'pci_device_id': '0x5678',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        converter_module.CollectionMatchResult(_PVAlignmentStatus.ALIGNED,
                                               'storage_bridge_only'), result)


if __name__ == '__main__':
  unittest.main()
