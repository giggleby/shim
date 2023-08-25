# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


_ConvertedValueSpec = converter.ConvertedValueSpec


class PCIEEMMCStorageAssemblyAVLAttrs(converter.AVLAttrs):
  BRIDGE_PCIE_VENDOR = 'bridge_pcie_vendor'
  BRIDGE_PCIE_DEVICE = 'bridge_pcie_device'
  BRIDGE_PCIE_CLASS = 'bridge_pcie_class'
  MMC_MANFID = 'mmc_manfid'
  MMC_NAME = 'mmc_name'
  NVME_MODEL = 'nvme_model'


_STORAGE_ASSEMBLY_CONVERTERS: Sequence[converter.Converter] = [
    converter.FieldNameConverter.FromFieldMap(
        'mmc_storage_with_bridge', {
            PCIEEMMCStorageAssemblyAVLAttrs.BRIDGE_PCIE_VENDOR:
                _ConvertedValueSpec('pci_vendor_id'),
            PCIEEMMCStorageAssemblyAVLAttrs.BRIDGE_PCIE_DEVICE:
                _ConvertedValueSpec('pci_device_id'),
            PCIEEMMCStorageAssemblyAVLAttrs.BRIDGE_PCIE_CLASS:
                _ConvertedValueSpec('pci_class'),
            PCIEEMMCStorageAssemblyAVLAttrs.MMC_MANFID:
                _ConvertedValueSpec(
                    'mmc_manfid',
                    converter.MakeFixedWidthHexValueFactory(
                        width=6, source_has_prefix=True)),
            PCIEEMMCStorageAssemblyAVLAttrs.MMC_NAME:
                _ConvertedValueSpec(
                    'mmc_name',
                    converter.MakeHexEncodedStrValueFactory(
                        source_has_prefix=True, fixed_num_bytes=6)),
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('pcie_emmc_storage_assembly')
  for conv in _STORAGE_ASSEMBLY_CONVERTERS:
    collection.AddConverter(conv)
  return collection
