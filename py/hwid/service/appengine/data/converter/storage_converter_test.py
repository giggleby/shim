#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data.converter import converter_test_utils
from cros.factory.hwid.service.appengine.data.converter import storage_converter
from cros.factory.hwid.v3 import contents_analyzer


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class StorageConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._converter_collection = storage_converter.GetConverterCollection()

  def testMatchMMCNoPrefixWithSectorsAligned(self):
    comp_values = {
        'name': 'AAABBB',
        'manfid': '0x000015',
        'prv': '0x2',
        'sectors': '244277248',  # 128GB
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'mmc_name': '0x414141424242',
        'mmc_manfid': '0x15',
        'mmc_prv': '0x02',
        'size_in_gb': 128
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testMatchMMCNoPrefixWithSectorsNotAligned(self):
    comp_values = {
        'name': 'AAABBB',
        'manfid': '0x000015',
        'prv': '0x2',
        'sectors': '123000000',  # 64GB
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'mmc_name': '0x414141424242',
        'mmc_manfid': '0x15',
        'mmc_prv': '0x02',
        'size_in_gb': 256
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)

  def testMatchPCIWithPrefixWithSizeAligned(self):
    comp_values = {
        'pci_class': '0x010802',
        'pci_vendor': '0x1234',
        'pci_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
        'size': '256060514304',  # 256GB
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'pci_class': '0x010802',
        'pci_vendor': '0x1234',
        'pci_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
        'size_in_gb': 256
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testMatchPCIWithPrefixWithSizeNotAligned(self):
    comp_values = {
        'pci_class': '0x010802',
        'pci_vendor': '0x1234',
        'pci_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
        'size': '256060514304',  # 256GB
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'pci_class': '0x010802',
        'pci_vendor': '0x1234',
        'pci_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
        'size_in_gb': 512
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)

  def testMatchPCIEEMMCStorageAssembly(self):
    comp_values = {
        'pci_class': '0x010802',
        'pci_vendor': '0x1234',
        'pci_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'bridge_pcie_class': '0x010802',
        'bridge_pcie_vendor': '0x1234',
        'bridge_pcie_device': '0x5678',
        'nvme_model': 'MODEL ABCXYZ',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)
    self.assertEqual(result.converter_identifier,
                     'pcie_emmc_storage_assembly_as_nvme')


if __name__ == '__main__':
  unittest.main()
