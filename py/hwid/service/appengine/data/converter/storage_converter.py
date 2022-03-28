# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter


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
            StorageAVLAttrs.NVME_MODEL: 'nvme_model',
            StorageAVLAttrs.PCI_CLASS: 'class',
            StorageAVLAttrs.PCI_DEVICE: 'device',
            StorageAVLAttrs.PCI_VENDOR: 'vendor',
        }),
    converter.FieldNameConverter.FromFieldMap(
        'pci_with_prefix', {
            StorageAVLAttrs.NVME_MODEL: 'nvme_model',
            StorageAVLAttrs.PCI_CLASS: 'pci_class',
            StorageAVLAttrs.PCI_DEVICE: 'pci_device',
            StorageAVLAttrs.PCI_VENDOR: 'pci_vendor',
        }),
    converter.FieldNameConverter.FromFieldMap('mmc_no_prefix', {
        StorageAVLAttrs.MMC_NAME: 'name',
        StorageAVLAttrs.MMC_MANFID: 'manfid',
    }),
    converter.FieldNameConverter.FromFieldMap(
        'mmc_with_prefix', {
            StorageAVLAttrs.MMC_NAME: 'mmc_name',
            StorageAVLAttrs.MMC_MANFID: 'mmc_manfid',
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('storage')
  for conv in _STORAGE_CONVERTERS:
    collection.AddConverter(conv)
  return collection
