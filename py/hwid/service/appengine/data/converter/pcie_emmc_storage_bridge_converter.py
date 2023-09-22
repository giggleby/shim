# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


_ConvertedValueSpec = converter.ConvertedValueSpec


class PCIEEMMCStorageBridgeAVLAttrs(converter.AVLAttrs):
  PCI_VENDOR = 'pci_vendor_id'
  PCI_DEVICE = 'pci_device_id'
  PCI_CLASS = 'pci_class'


_STORAGE_BRIDGE_CONVERTERS: Sequence[converter.Converter] = [
    converter.FieldNameConverter.FromFieldMap(
        'pcie_emmc_storage_bridge', {
            PCIEEMMCStorageBridgeAVLAttrs.PCI_DEVICE:
                _ConvertedValueSpec('pci_device_id'),
            PCIEEMMCStorageBridgeAVLAttrs.PCI_VENDOR:
                _ConvertedValueSpec('pci_vendor_id'),
            PCIEEMMCStorageBridgeAVLAttrs.PCI_CLASS:
                _ConvertedValueSpec('pci_class'),
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('pcie_emmc_storage_bridge')
  for conv in _STORAGE_BRIDGE_CONVERTERS:
    collection.AddConverter(conv)
  return collection
