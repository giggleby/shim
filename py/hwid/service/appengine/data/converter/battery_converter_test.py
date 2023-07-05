#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data.converter import battery_converter
from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import converter_test_utils
from cros.factory.hwid.v3 import contents_analyzer


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class BatteryConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._converter_collection = battery_converter.GetConverterCollection()

  def testFullLengthMatch(self):
    comp_values = {
        'manufacturer': 'manufacturer',
        'model_name': 'model_name',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'manufacturer',
        'model_name': 'model_name',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testFullLengthNotMatch(self):
    comp_values = {
        'manufacturer': 'manufacturer',
        'model_name': 'model_name',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'not-manufacturer',
        'model_name': 'model_name',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)

  def testPrefixMatch_Length7(self):
    comp_values = {
        'manufacturer': 'ABCDEFG',
        'model_name': '1234567',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'ABCDEFGHIJKLMN',
        'model_name': '12345678901234',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        result,
        converter.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED,
            converter_identifier='prefix_match_length_7'))

  def testPrefixMatch_Length11(self):
    comp_values = {
        'manufacturer': 'ABCDEFGHIJK',
        'model_name': '12345678901',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        'model_name': '12345678901234567890123456',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        result,
        converter.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED,
            converter_identifier='prefix_match_length_11'))

  def testPrefixMatch_Length7WithStrip(self):
    comp_values = {
        'manufacturer': 'ABCDE',
        'model_name': '1234',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'ABCDE  HIJ',
        'model_name': '1234   890',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        result,
        converter.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED,
            converter_identifier='prefix_match_length_7'))

  def testPrefixMatch_PreferLongerLength(self):
    comp_values = {
        'manufacturer': 'ABCDEFG',
        'model_name': '1234567',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'ABCDEFG    LM',
        'model_name': '1234567    23',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        result,
        converter.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED,
            converter_identifier='prefix_match_length_11'))

  def testPrefixMatch_WithTrailingSpace(self):
    comp_values = {
        'manufacturer': 'ABCDEF ',
        'model_name': '123456 ',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'manufacturer': 'ABCDEF GHIJ',
        'model_name': '123456 7890',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(
        result,
        converter.CollectionMatchResult(
            _PVAlignmentStatus.ALIGNED,
            converter_identifier='prefix_match_length_7'))


if __name__ == '__main__':
  unittest.main()
