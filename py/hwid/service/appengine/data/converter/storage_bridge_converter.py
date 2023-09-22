# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import pcie_emmc_storage_assembly_converter
from cros.factory.hwid.service.appengine.data.converter import pcie_emmc_storage_bridge_converter


_ConvertedValueSpec = converter.ConvertedValueSpec
_StorageAssemblyAVLAttrs = (
    pcie_emmc_storage_assembly_converter.PCIEEMMCStorageAssemblyAVLAttrs)
_StorageBridgeAVLAttrs = (
    pcie_emmc_storage_bridge_converter.PCIEEMMCStorageBridgeAVLAttrs)

_STORAGE_BRIDGE_CONVERTERS: Sequence[converter.Converter] = [
    converter.FieldNameConverter.FromFieldMap(
        'storage_assembly_as_nvme', {
            _StorageAssemblyAVLAttrs.BRIDGE_PCIE_VENDOR:
                _ConvertedValueSpec('pci_vendor'),
            _StorageAssemblyAVLAttrs.BRIDGE_PCIE_DEVICE:
                _ConvertedValueSpec('pci_device'),
            _StorageAssemblyAVLAttrs.NVME_MODEL:
                _ConvertedValueSpec('nvme_model'),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'storage_assembly_with_bridge', {
            _StorageAssemblyAVLAttrs.BRIDGE_PCIE_DEVICE:
                _ConvertedValueSpec('device'),
            _StorageAssemblyAVLAttrs.BRIDGE_PCIE_VENDOR:
                _ConvertedValueSpec('vendor'),
            _StorageAssemblyAVLAttrs.MMC_NAME:
                _ConvertedValueSpec(
                    'name',
                    converter.MakeHexEncodedStrValueFactory(
                        source_has_prefix=True, fixed_num_bytes=6)),
            _StorageAssemblyAVLAttrs.MMC_MANFID:
                _ConvertedValueSpec(
                    'manfid',
                    converter.MakeFixedWidthHexValueFactory(
                        width=6, source_has_prefix=True)),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'storage_bridge_only', {
            _StorageBridgeAVLAttrs.PCI_DEVICE: _ConvertedValueSpec('device'),
            _StorageBridgeAVLAttrs.PCI_VENDOR: _ConvertedValueSpec('vendor'),
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('storage_bridge')
  for conv in _STORAGE_BRIDGE_CONVERTERS:
    collection.AddConverter(conv)
  return collection
