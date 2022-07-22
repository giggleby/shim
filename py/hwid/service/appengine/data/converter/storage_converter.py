# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter

# Shorter identifiers.
_ConvertedValueSpec = converter.ConvertedValueSpec


class StorageAVLAttrs(converter.AVLAttrs):
  PCI_VENDOR = 'pci_vendor'
  PCI_DEVICE = 'pci_device'
  PCI_CLASS = 'pci_class'
  MMC_MANFID = 'mmc_manfid'
  MMC_NAME = 'mmc_name'
  NVME_MODEL = 'nvme_model'


_STORAGE_CONVERTERS: Sequence[converter.FieldNameConverter] = [
    converter.FieldNameConverter.FromFieldMap(
        'pci_no_prefix', {
            StorageAVLAttrs.NVME_MODEL: _ConvertedValueSpec('nvme_model'),
            StorageAVLAttrs.PCI_CLASS: _ConvertedValueSpec('class'),
            StorageAVLAttrs.PCI_DEVICE: _ConvertedValueSpec('device'),
            StorageAVLAttrs.PCI_VENDOR: _ConvertedValueSpec('vendor'),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'pci_with_prefix', {
            StorageAVLAttrs.NVME_MODEL: _ConvertedValueSpec('nvme_model'),
            StorageAVLAttrs.PCI_CLASS: _ConvertedValueSpec('pci_class'),
            StorageAVLAttrs.PCI_DEVICE: _ConvertedValueSpec('pci_device'),
            StorageAVLAttrs.PCI_VENDOR: _ConvertedValueSpec('pci_vendor'),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'mmc_no_prefix', {
            StorageAVLAttrs.MMC_NAME:
                _ConvertedValueSpec(
                    'name',
                    converter.MakeHexEncodedStrValueFactory(
                        source_has_prefix=True, fixed_num_bytes=6)),
            StorageAVLAttrs.MMC_MANFID:
                _ConvertedValueSpec(
                    'manfid',
                    converter.MakeFixedWidthHexValueFactory(
                        width=6, source_has_prefix=True))
        }),
    converter.FieldNameConverter.FromFieldMap(
        'mmc_with_prefix', {
            StorageAVLAttrs.MMC_NAME:
                _ConvertedValueSpec(
                    'mmc_name',
                    converter.MakeHexEncodedStrValueFactory(
                        source_has_prefix=True, fixed_num_bytes=6)),
            StorageAVLAttrs.MMC_MANFID:
                _ConvertedValueSpec(
                    'mmc_manfid',
                    converter.MakeFixedWidthHexValueFactory(
                        width=6, source_has_prefix=True))
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('storage')
  for conv in _STORAGE_CONVERTERS:
    collection.AddConverter(conv)
  return collection
