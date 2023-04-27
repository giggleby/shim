# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

import math
from typing import Any, Sequence

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import converter_types


_ConvertedValueSpec = converter.ConvertedValueSpec


class StorageAVLAttrs(converter.AVLAttrs):
  PCI_VENDOR = 'pci_vendor'
  PCI_DEVICE = 'pci_device'
  PCI_CLASS = 'pci_class'
  MMC_MANFID = 'mmc_manfid'
  MMC_NAME = 'mmc_name'
  MMC_PRV = 'mmc_prv'
  NVME_MODEL = 'nvme_model'
  UFS_MODEL = 'ufs_model'
  UFS_VENDOR = 'ufs_vendor'
  SIZE_IN_GB = 'size_in_gb'


class _StorageByteSizeValueType(int, converter_types.ConvertedValueType):

  def __eq__(self, other: Any):
    if isinstance(other, str):
      try:
        other = int(other)
      except ValueError:
        return False

    elif not isinstance(other, int):
      return False

    if super().__le__(0) or other <= 0:
      return False

    return math.ceil(math.log2(self * 1024**3)) == math.ceil(math.log2(other))

  def __ne__(self, other: Any):
    return not self.__eq__(other)


class _StorageSectorSizeValueType(int, converter_types.ConvertedValueType):

  def __eq__(self, other: Any):
    if isinstance(other, str):
      try:
        other = int(other)
      except ValueError:
        return False

    elif not isinstance(other, int):
      return False

    if super().__le__(0) or other <= 0:
      return False

    return math.ceil(math.log2(self * 1024**3)) == math.ceil(
        math.log2(other * 512))

  def __ne__(self, other: Any):
    return not self.__eq__(other)


_STORAGE_CONVERTERS: Sequence[converter.Converter] = [
    converter.FieldNameConverter.FromFieldMap(
        'pci_no_prefix', {
            StorageAVLAttrs.NVME_MODEL:
                _ConvertedValueSpec('nvme_model'),
            StorageAVLAttrs.PCI_CLASS:
                _ConvertedValueSpec('class'),
            StorageAVLAttrs.PCI_DEVICE:
                _ConvertedValueSpec('device'),
            StorageAVLAttrs.PCI_VENDOR:
                _ConvertedValueSpec('vendor'),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('size', _StorageByteSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'pci_no_prefix_with_sectors', {
            StorageAVLAttrs.NVME_MODEL:
                _ConvertedValueSpec('nvme_model'),
            StorageAVLAttrs.PCI_CLASS:
                _ConvertedValueSpec('class'),
            StorageAVLAttrs.PCI_DEVICE:
                _ConvertedValueSpec('device'),
            StorageAVLAttrs.PCI_VENDOR:
                _ConvertedValueSpec('vendor'),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('sectors', _StorageSectorSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'pci_with_prefix', {
            StorageAVLAttrs.NVME_MODEL:
                _ConvertedValueSpec('nvme_model'),
            StorageAVLAttrs.PCI_CLASS:
                _ConvertedValueSpec('pci_class'),
            StorageAVLAttrs.PCI_DEVICE:
                _ConvertedValueSpec('pci_device'),
            StorageAVLAttrs.PCI_VENDOR:
                _ConvertedValueSpec('pci_vendor'),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('size', _StorageByteSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'pci_with_prefix_with_sectors', {
            StorageAVLAttrs.NVME_MODEL:
                _ConvertedValueSpec('nvme_model'),
            StorageAVLAttrs.PCI_CLASS:
                _ConvertedValueSpec('pci_class'),
            StorageAVLAttrs.PCI_DEVICE:
                _ConvertedValueSpec('pci_device'),
            StorageAVLAttrs.PCI_VENDOR:
                _ConvertedValueSpec('pci_vendor'),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('sectors', _StorageSectorSizeValueType),
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
                        width=6, source_has_prefix=True)),
            StorageAVLAttrs.MMC_PRV:
                _ConvertedValueSpec(
                    'prv',
                    converter.MakeBothNormalizedFillWidthHexValueFactory(
                        fill_width=2, source_has_prefix=True)),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('size', _StorageByteSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'mmc_no_prefix_with_sectors', {
            StorageAVLAttrs.MMC_NAME:
                _ConvertedValueSpec(
                    'name',
                    converter.MakeHexEncodedStrValueFactory(
                        source_has_prefix=True, fixed_num_bytes=6)),
            StorageAVLAttrs.MMC_MANFID:
                _ConvertedValueSpec(
                    'manfid',
                    converter.MakeFixedWidthHexValueFactory(
                        width=6, source_has_prefix=True)),
            StorageAVLAttrs.MMC_PRV:
                _ConvertedValueSpec(
                    'prv',
                    converter.MakeBothNormalizedFillWidthHexValueFactory(
                        fill_width=2, source_has_prefix=True)),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('sectors', _StorageSectorSizeValueType),
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
                        width=6, source_has_prefix=True)),
            StorageAVLAttrs.MMC_PRV:
                _ConvertedValueSpec(
                    'mmc_prv',
                    converter.MakeBothNormalizedFillWidthHexValueFactory(
                        fill_width=2, source_has_prefix=True)),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('size', _StorageByteSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'mmc_with_prefix_with_sectors', {
            StorageAVLAttrs.MMC_NAME:
                _ConvertedValueSpec(
                    'mmc_name',
                    converter.MakeHexEncodedStrValueFactory(
                        source_has_prefix=True, fixed_num_bytes=6)),
            StorageAVLAttrs.MMC_MANFID:
                _ConvertedValueSpec(
                    'mmc_manfid',
                    converter.MakeFixedWidthHexValueFactory(
                        width=6, source_has_prefix=True)),
            StorageAVLAttrs.MMC_PRV:
                _ConvertedValueSpec(
                    'mmc_prv',
                    converter.MakeBothNormalizedFillWidthHexValueFactory(
                        fill_width=2, source_has_prefix=True)),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('sectors', _StorageSectorSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'ufs_full_match', {
            StorageAVLAttrs.UFS_MODEL:
                _ConvertedValueSpec('ufs_model'),
            StorageAVLAttrs.UFS_VENDOR:
                _ConvertedValueSpec('ufs_vendor'),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('size', _StorageByteSizeValueType),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'ufs_full_match_with_sectors', {
            StorageAVLAttrs.UFS_MODEL:
                _ConvertedValueSpec('ufs_model'),
            StorageAVLAttrs.UFS_VENDOR:
                _ConvertedValueSpec('ufs_vendor'),
            StorageAVLAttrs.SIZE_IN_GB:
                _ConvertedValueSpec('sectors', _StorageSectorSizeValueType),
        }),
]


def GetConverterCollection():
  collection = converter.ConverterCollection('storage')
  for conv in _STORAGE_CONVERTERS:
    collection.AddConverter(conv)
  return collection
