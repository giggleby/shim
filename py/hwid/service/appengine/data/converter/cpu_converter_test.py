#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds field name mappings from AVL to HWID."""

import unittest

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import cpu_converter
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class CPUConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    self._converter_collection = cpu_converter.GetConverterCollection()

  def testMatchX86_AllMatched(self):
    comp_values = {
        'cores': '4',
        'model': 'this is the model string',
    }
    probe_info = stubby_pb2.ProbeInfo(probe_function_name='cpu.generic_cpu')
    probe_info.probe_parameters.add(name='identifier',
                                    string_value='this is the model string')

    actual = self._converter_collection.Match(comp_values, probe_info)

    expect = converter.CollectionMatchResult(_PVAlignmentStatus.ALIGNED,
                                             'model_as_identifier')
    self.assertEqual(actual, expect)

  def testMatchX86_ValueUnamtched(self):
    comp_values = {
        'cores': '4',
        'model': 'this is the incorrect model string',
    }
    probe_info = stubby_pb2.ProbeInfo(probe_function_name='cpu.generic_cpu')
    probe_info.probe_parameters.add(name='identifier',
                                    string_value='this is the model string')

    actual = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(actual.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)

  def testMatchARM_AllMatched(self):
    comp_values = {
        'cores': '4',
        'model': 'this is the dummy model string',
        'chip_id': '0x12345'
    }
    probe_info = stubby_pb2.ProbeInfo(probe_function_name='cpu.generic_cpu')
    probe_info.probe_parameters.add(name='identifier', string_value='0x12345')

    actual = self._converter_collection.Match(comp_values, probe_info)

    expect = converter.CollectionMatchResult(_PVAlignmentStatus.ALIGNED,
                                             'chip_id_as_identifier')
    self.assertEqual(actual, expect)

  def testMatchARM_ValueUnamtched(self):
    comp_values = {
        'cores': '4',
        'model': 'this is the dummy model string',
        'chip_id': 'this value is incorrect'
    }
    probe_info = stubby_pb2.ProbeInfo(probe_function_name='cpu.generic_cpu')
    probe_info.probe_parameters.add(name='identifier', string_value='0x12345')

    actual = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(actual.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)


if __name__ == '__main__':
  unittest.main()
