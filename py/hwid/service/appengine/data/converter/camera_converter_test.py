#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data.converter import camera_converter
from cros.factory.hwid.service.appengine.data.converter import converter_test_utils
from cros.factory.hwid.v3 import contents_analyzer


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class CameraConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._converter_collection = camera_converter.GetConverterCollection()

  def testUsbWithPrefixFullLengthMatch(self):
    comp_values = {
        'usb_bcd_device': '00a1',
        'usb_product_id': '12ab',
        'usb_vendor_id': '34cd',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'usb_bcd_device': '00A1',
        'usb_product_id': '12AB',
        'usb_vendor_id': '34CD',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testUsbNoPrefixFullLengthMatch(self):
    comp_values = {
        'bcdDevice': '00a1',
        'idProduct': '12ab',
        'idVendor': '34cd',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'usb_bcd_device': '00A1',
        'usb_product_id': '12AB',
        'usb_vendor_id': '34CD',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testMipiWithPrefixFullLengthMatch(self):
    comp_values = {
        'mipi_module_id': 'TC12ab',
        'mipi_sensor_id': 'OV34cd',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'module_vid': 'TC',
        'module_pid': '0x12AB',
        'sensor_vid': 'OV',
        'sensor_pid': '0x34CD',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testMipiNoPrefixFullLengthMatch(self):
    comp_values = {
        'module_id': 'TC12ab',
        'sensor_id': 'OV34cd',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'module_vid': 'TC',
        'module_pid': '0x12AB',
        'sensor_vid': 'OV',
        'sensor_pid': '0x34CD',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testMipiFullLengthNotMatch(self):
    comp_values = {
        'mipi_module_id': 'TC1234',
        'mipi_sensor_id': 'OVabcd',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'module_vid': 'TC',
        'module_pid': '0x1235',
        'sensor_vid': 'OV',
        'sensor_pid': '0xabcd',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)

  def testUsbMatchWithoutBCD(self):
    comp_values = {
        'usb_bcd_device': '00a1',
        'usb_product_id': '12ab',
        'usb_vendor_id': '34cd',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'usb_product_id': '12AB',
        'usb_vendor_id': '34CD',
    })

    result = self._converter_collection.Match(comp_values, probe_info,
                                              is_qual_probe_info=False)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)


if __name__ == '__main__':
  unittest.main()
