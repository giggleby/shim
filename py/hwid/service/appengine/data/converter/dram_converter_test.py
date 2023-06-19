#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data.converter import converter_test_utils
from cros.factory.hwid.service.appengine.data.converter import dram_converter
from cros.factory.hwid.v3 import contents_analyzer


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class DramConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._converter_collection = dram_converter.GetConverterCollection()

  def testFullLengthMatch(self):
    comp_values = {
        'part': 'part-number',
        'size': '12345',
        'slot': '3',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'part': 'part-number',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.ALIGNED)

  def testFullLengthNotMatch(self):
    comp_values = {
        'part': 'not-part-number',
        'size': '12345',
        'slot': '3',
    }
    probe_info = converter_test_utils.ProbeInfoFromMapping({
        'part': 'part-number',
    })

    result = self._converter_collection.Match(comp_values, probe_info)

    self.assertEqual(result.alignment_status, _PVAlignmentStatus.NOT_ALIGNED)


if __name__ == '__main__':
  unittest.main()
