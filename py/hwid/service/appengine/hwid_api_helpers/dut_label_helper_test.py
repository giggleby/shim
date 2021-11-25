# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock
import os.path

from cros.factory.hwid.v3 import database
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers \
    import dut_label_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine import test_utils
# pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2
# pylint: enable=import-error, no-name-in-module

GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata',
    'v3-golden.yaml')

TEST_HWID = 'Foo'


class DUTLabelHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._module_collection = test_utils.FakeModuleCollection()
    self._vpg_targets = {}
    self._bc_helper = mock.Mock(
        spec=bc_helper.BOMAndConfiglessHelper,
        wraps=bc_helper.BOMAndConfiglessHelper(
            self._module_collection.fake_hwid_action_manager, self._vpg_targets,
            self._module_collection.fake_decoder_data_manager))
    self._sku_helper = mock.Mock(
        spec=sku_helper.SKUHelper, wraps=sku_helper.SKUHelper(
            self._module_collection.fake_decoder_data_manager))
    self._dl_helper = dut_label_helper.DUTLabelHelper(
        self._module_collection.fake_decoder_data_manager,
        self._module_collection.fake_goldeneye_memcache, self._bc_helper,
        self._sku_helper)

    self._module_collection.fake_goldeneye_memcache.Put(
        'regexp_to_device', [('r1.*', 'b1', []), ('^Fo.*', 'found_device', [])])

  def tearDown(self):
    super().tearDown()
    self._module_collection.ClearAll()

  def testGetDUTLabels_Success(self):
    bom = hwid_action.BOM()
    bom.AddComponent('touchscreen', name='testscreen', is_vp_related=True)
    bom.project = 'foo'
    bom.phase = 'bar'
    configless = None
    self._sku_helper.GetSKUFromBOM.return_value = {
        'sku': 'TestSku',
        'project': None,
        'cpu': None,
        'memory_str': None,
        'total_bytes': None,
    }
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertTrue(self.CheckForLabelValue(msg, 'phase', 'bar'))
    self.assertTrue(self.CheckForLabelValue(msg, 'variant', 'found_device'))
    self.assertTrue(self.CheckForLabelValue(msg, 'sku', 'TestSku'))
    self.assertTrue(self.CheckForLabelValue(msg, 'touchscreen'))
    self.assertTrue(self.CheckForLabelValue(msg, 'hwid_component'))
    self.assertEqual(5, len(msg.labels))

  def testGetDUTLabels_MissingRegexpList(self):
    self._module_collection.fake_goldeneye_memcache.ClearAll()
    bom = hwid_action.BOM()
    bom.AddComponent('touchscreen', name='testscreen', is_vp_related=True)
    bom.project = 'foo'
    bom.phase = 'bar'
    configless = None
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }
    self._sku_helper.GetSKUFromBOM.return_value = {
        'sku': 'TestSku',
        'project': None,
        'cpu': None,
        'memory_str': None,
        'total_bytes': None,
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertEqual(
        hwid_api_messages_pb2.DutLabelsResponse(
            status=hwid_api_messages_pb2.Status.SERVER_ERROR,
            error='Missing Regexp List', possible_labels=[
                'hwid_component',
                'phase',
                'sku',
                'stylus',
                'touchpad',
                'touchscreen',
                'variant',
            ]), msg)

  def testGetPossibleDUTLabels(self):
    req = hwid_api_messages_pb2.DutLabelsRequest(hwid='')
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertEqual(
        hwid_api_messages_pb2.DutLabelsResponse(
            status=hwid_api_messages_pb2.Status.SUCCESS, possible_labels=[
                'hwid_component',
                'phase',
                'sku',
                'stylus',
                'touchpad',
                'touchscreen',
                'variant',
            ]), msg)

  def testGetDUTLabels_WithConfigless(self):
    bom = hwid_action.BOM()
    bom.project = 'foo'
    bom.phase = 'bar'
    configless = {
        'feature_list': {
            'has_touchscreen': 1,
        },
    }
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }
    self._sku_helper.GetSKUFromBOM.return_value = {
        'sku': 'TestSku',
        'project': None,
        'cpu': None,
        'memory_str': None,
        'total_bytes': None,
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertTrue(self.CheckForLabelValue(msg, 'phase', 'bar'))
    self.assertTrue(self.CheckForLabelValue(msg, 'variant', 'found_device'))
    self.assertTrue(self.CheckForLabelValue(msg, 'sku', 'TestSku'))
    self.assertTrue(self.CheckForLabelValue(msg, 'touchscreen'))
    self.assertEqual(4, len(msg.labels))

  def testGetDUTLabels_CheckIsVPRelated(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents(
        {
            'battery': 'battery_small',
            'camera': 'camera_0',
            'cpu': ['cpu_0', 'cpu_1'],
        }, comp_db=database.Database.LoadFile(
            GOLDEN_HWIDV3_FILE, verify_checksum=False), require_vp_info=True)
    bom.project = 'foo'
    bom.phase = 'bar'
    configless = None
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertEqual(
        hwid_api_messages_pb2.DutLabelsResponse(
            status=hwid_api_messages_pb2.Status.SUCCESS,
            labels=[
                # Only components with 'is_vp_related=True' will be reported as
                # hwid_component.
                hwid_api_messages_pb2.DutLabel(name='hwid_component',
                                               value='battery/battery_small'),
                hwid_api_messages_pb2.DutLabel(name='hwid_component',
                                               value='camera/camera_0'),
                hwid_api_messages_pb2.DutLabel(name='phase', value='bar'),
                hwid_api_messages_pb2.DutLabel(name='sku',
                                               value='foo_cpu_0_cpu_1_0B'),
                hwid_api_messages_pb2.DutLabel(name='variant',
                                               value='found_device'),
            ],
            possible_labels=[
                'hwid_component',
                'phase',
                'sku',
                'stylus',
                'touchpad',
                'touchscreen',
                'variant',
            ]),
        msg)

  def CheckForLabelValue(self, response, label_to_check_for,
                         value_to_check_for=None):
    for label in response.labels:
      if label.name == label_to_check_for:
        if value_to_check_for and label.value != value_to_check_for:
          return False
        return True
    return False


if __name__ == '__main__':
  unittest.main()
