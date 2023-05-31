# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

from typing import Callable, Sequence

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import converter_types

# Shorter identifiers.
_ConvertedValueSpec = converter.ConvertedValueSpec


class _USBCameraAVLAttrs(converter.AVLAttrs):
  BCD_DEVICE = 'usb_bcd_device'
  PRODUCT_ID = 'usb_product_id'
  VENDOR_ID = 'usb_vendor_id'


class _MIPICameraAVLAttrs(converter.AVLAttrs):
  MODULE_VID = 'module_vid'
  MODULE_PID = 'module_pid'
  SENSOR_VID = 'sensor_vid'
  SENSOR_PID = 'sensor_pid'


class _MipiVIDStrFormatter(converter_types.StrFormatter):

  def __call__(self, value: str, *unused_args, **unused_kwargs):
    if len(value) != 6:
      raise converter_types.StrFormatterError(
          f'Expect a string of length 6, got {value!r}.')
    return value[:2]


class _MipiPIDStrFormatter(converter_types.StrFormatter):

  def __init__(self, has_prefix=False):
    self._has_prefix = has_prefix

  def __call__(self, value: str, *unused_args, **unused_kwargs):
    if len(value) != 6:
      raise converter_types.StrFormatterError(
          f'Expect a string of length 6, got {value!r}.')
    if self._has_prefix and not value.startswith('0x'):
      raise converter_types.StrFormatterError(
          f'Expect a hex string starts with 0x, got {value!r}.')
    return value[2:].lower()


def MakeMipiVIDMatchFactory(
) -> Callable[..., converter_types.FormattedStrType]:
  return converter_types.FormattedStrType.CreateInstanceFactory(
      formatter_other=_MipiVIDStrFormatter())


def MakeMipiPIDMatchFactory(
) -> Callable[..., converter_types.FormattedStrType]:
  return converter_types.FormattedStrType.CreateInstanceFactory(
      formatter_self=_MipiPIDStrFormatter(has_prefix=True),
      formatter_other=_MipiPIDStrFormatter(has_prefix=False))


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
    converter.FieldNameConverter.FromFieldMap(
        'mipi_no_prefix', {
            _MIPICameraAVLAttrs.MODULE_VID:
                _ConvertedValueSpec('module_id', MakeMipiVIDMatchFactory()),
            _MIPICameraAVLAttrs.MODULE_PID:
                _ConvertedValueSpec('module_id', MakeMipiPIDMatchFactory()),
            _MIPICameraAVLAttrs.SENSOR_VID:
                _ConvertedValueSpec('sensor_id', MakeMipiVIDMatchFactory()),
            _MIPICameraAVLAttrs.SENSOR_PID:
                _ConvertedValueSpec('sensor_id', MakeMipiPIDMatchFactory()),
        }),
    converter.FieldNameConverter.FromFieldMap(
        'mipi_with_prefix', {
            _MIPICameraAVLAttrs.MODULE_VID:
                _ConvertedValueSpec('mipi_module_id',
                                    MakeMipiVIDMatchFactory()),
            _MIPICameraAVLAttrs.MODULE_PID:
                _ConvertedValueSpec('mipi_module_id',
                                    MakeMipiPIDMatchFactory()),
            _MIPICameraAVLAttrs.SENSOR_VID:
                _ConvertedValueSpec('mipi_sensor_id',
                                    MakeMipiVIDMatchFactory()),
            _MIPICameraAVLAttrs.SENSOR_PID:
                _ConvertedValueSpec('mipi_sensor_id',
                                    MakeMipiPIDMatchFactory()),
        }),
]


def GetConverterCollection(category='camera'):
  collection = converter.ConverterCollection(category)
  for conv in _USB_CAMERA_CONVERTERS:
    collection.AddConverter(conv)
  return collection
