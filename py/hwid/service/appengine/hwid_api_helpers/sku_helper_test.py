#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import unittest

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import database


EXAMPLE_MEMORY_STR = ['hynix_2gb_dimm0', 'hynix_0gb_dimm1']
SKU_TEST_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata', 'v3-sku.yaml')

EXAMPLE_MEMORY_COMPONENT1 = hwid_action.Component(
    cls_='dram', name='dram_micron_1g_dimm2', fields={'size': '1024'})
EXAMPLE_MEMORY_COMPONENT2 = hwid_action.Component(
    cls_='dram', name='hynix_2gb_dimm0', fields={'size': '2048'})
EXAMPLE_MEMORY_COMPONENT3 = hwid_action.Component(
    cls_='dram', name='dram_hynix_512m_dimm2', fields={'size': '512'})

EXAMPLE_MEMORY_COMPONENTS = [
    EXAMPLE_MEMORY_COMPONENT1, EXAMPLE_MEMORY_COMPONENT2,
    EXAMPLE_MEMORY_COMPONENT3
]

EXAMPLE_MEMORY_COMPONENT_WITH_SIZE = hwid_action.Component(
    cls_='dram', name='simple_tag', fields={'size': '1024'})
INVALID_MEMORY_COMPONENT = hwid_action.Component(
    cls_='dram', name='no_size_in_fields_is_invalid_2GB')


class SKUHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    self._modules = test_utils.FakeModuleCollection()

    self._sku_helper = sku_helper.SKUHelper(
        self._modules.fake_decoder_data_manager)
    self._comp_db = database.Database.LoadFile(SKU_TEST_FILE,
                                               verify_checksum=False)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def testGetSKUFromBOM(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents(
        {
            'dram': EXAMPLE_MEMORY_STR,
            'cpu': 'longstringwithcpu'
        }, comp_db=self._comp_db, verbose=True)
    bom.project = 'testprojectname'

    sku = self._sku_helper.GetSKUFromBOM(bom)

    self.assertEqual('testprojectname_longstringwithcpu_4GB', sku['sku'])
    self.assertEqual('testprojectname', sku['project'])
    self.assertEqual('longstringwithcpu', sku['cpu'])
    self.assertEqual('4GB', sku['memory_str'])
    self.assertEqual(4294967296, sku['total_bytes'])

  def testGetSKUFromBOM_WithConfigless(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents(
        {
            'dram': EXAMPLE_MEMORY_STR,
            'cpu': 'longstringwithcpu'
        }, comp_db=self._comp_db, verbose=True)
    bom.project = 'testprojectname'

    configless = {
        'memory': 8
    }
    sku = self._sku_helper.GetSKUFromBOM(bom, configless)

    self.assertEqual('testprojectname_longstringwithcpu_8GB', sku['sku'])
    self.assertEqual('testprojectname', sku['project'])
    self.assertEqual('longstringwithcpu', sku['cpu'])
    self.assertEqual('8GB', sku['memory_str'])
    self.assertEqual(8589934592, sku['total_bytes'])

  def testGetSKUFromBOM_MissingCPU(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({'dram': ['some_memory_chip', 'other_memory_chip']})
    bom.project = 'foo'
    configless = {
        'memory': 8
    }

    sku = self._sku_helper.GetSKUFromBOM(bom, configless)

    self.assertEqual(None, sku['cpu'])

  def testGetComponentValueFromBOM(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'bar': 'baz',
        'null': []
    })

    value = self._sku_helper.GetComponentValueFromBOM(bom, 'bar')
    self.assertEqual(['baz'], value)

    value = self._sku_helper.GetComponentValueFromBOM(bom, 'null')
    self.assertEqual(None, value)

    value = self._sku_helper.GetComponentValueFromBOM(bom, 'not_there')
    self.assertEqual(None, value)

  def testGetTotalRAMFromHWIDData_AllMemoryTypes(self):
    result_str, total_bytes = self._sku_helper.GetTotalRAMFromHWIDData(
        EXAMPLE_MEMORY_COMPONENTS)
    self.assertEqual('3584MB', result_str)
    self.assertEqual(3758096384, total_bytes)

  def testGetTotalRAMFromHWIDData_MemoryType1(self):
    result_str, total_bytes = self._sku_helper.GetTotalRAMFromHWIDData(
        [EXAMPLE_MEMORY_COMPONENT1])
    self.assertEqual('1GB', result_str)
    self.assertEqual(1073741824, total_bytes)

  def testGetTotalRAMFromHWIDData_MemoryType2(self):
    result_str, total_bytes = self._sku_helper.GetTotalRAMFromHWIDData(
        [EXAMPLE_MEMORY_COMPONENT2])
    self.assertEqual('2GB', result_str)
    self.assertEqual(2147483648, total_bytes)

  def testGetTotalRAMFromHWIDData_EmptyList(self):
    result_str, total_bytes = self._sku_helper.GetTotalRAMFromHWIDData([])
    self.assertEqual('0B', result_str)
    self.assertEqual(0, total_bytes)

  def testGetTotalRAMFromHWIDData_MemoryFromSizeField(self):
    result_str, total_bytes = self._sku_helper.GetTotalRAMFromHWIDData(
        [EXAMPLE_MEMORY_COMPONENT_WITH_SIZE])
    self.assertEqual('1GB', result_str)
    self.assertEqual(1073741824, total_bytes)

  def testMemoryOnlySizeInName(self):
    self.assertRaises(sku_helper.SKUDeductionError,
                      self._sku_helper.GetTotalRAMFromHWIDData,
                      [INVALID_MEMORY_COMPONENT])


if __name__ == '__main__':
  unittest.main()
