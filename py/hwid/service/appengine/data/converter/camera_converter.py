# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Sequence

from cros.factory.hwid.service.appengine.data.converter import converter

# Shorter identifiers.
_ConvertedValueSpec = converter.ConvertedValueSpec


class _USBCameraAVLAttrs(converter.AVLAttrs):
  BCD_DEVICE = 'usb_bcd_device'
  PRODUCT_ID = 'usb_product_id'
  VENDOR_ID = 'usb_vendor_id'


_USB_CAMERA_CONVERTERS: Sequence[converter.FieldNameConverter] = [
    converter.FieldNameConverter.FromFieldMap(
        'usb_no_prefix', {
            _USBCameraAVLAttrs.BCD_DEVICE: _ConvertedValueSpec('bcdDevice'),
            _USBCameraAVLAttrs.PRODUCT_ID: _ConvertedValueSpec('idProduct'),
            _USBCameraAVLAttrs.VENDOR_ID: _ConvertedValueSpec('idVendor'),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'usb_with_prefix', {
            _USBCameraAVLAttrs.BCD_DEVICE:
                _ConvertedValueSpec('usb_bcd_device'),
            _USBCameraAVLAttrs.PRODUCT_ID:
                _ConvertedValueSpec('usb_product_id'),
            _USBCameraAVLAttrs.VENDOR_ID:
                _ConvertedValueSpec('usb_vendor_id'),
        }),
]


def GetConverterCollection(category='camera'):
  collection = converter.ConverterCollection(category)
  for conv in _USB_CAMERA_CONVERTERS:
    collection.AddConverter(conv)
  return collection
