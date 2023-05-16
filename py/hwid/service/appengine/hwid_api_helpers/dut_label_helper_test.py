# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import dut_label_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import database


GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata',
    'v3-golden.yaml')

TEST_PROJECT = 'Foo'
TEST_HWID = 'Foo'


class DUTLabelHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._module_collection = test_utils.FakeModuleCollection()
    self._vpg_targets = {}
    self._bc_helper = mock.Mock(
        spec=bc_helper.BOMAndConfiglessHelper,
        wraps=bc_helper.BOMAndConfiglessHelper(
            self._module_collection.fake_decoder_data_manager))
    self._sku_helper = mock.Mock(
        spec=sku_helper.SKUHelper, wraps=sku_helper.SKUHelper(
            self._module_collection.fake_decoder_data_manager))
    self._dl_helper = dut_label_helper.DUTLabelHelper(
        self._module_collection.fake_decoder_data_manager,
        self._module_collection.fake_goldeneye_memcache, self._bc_helper,
        self._sku_helper, self._module_collection.fake_hwid_action_manager)

    self._module_collection.fake_goldeneye_memcache.Put('regexp_to_device', [
        ('r1.*', 'b1', []),
        ('^Fo.*', 'found_device', []),
        ('^F.*', 'found_device', []),
    ])

  def tearDown(self):
    super().tearDown()
    self._module_collection.ClearAll()

  def _SetupFakeHWIDActionForTestProject(
      self, feature_enablement_label: str = 'just_a_random_default_value'):
    instance = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    instance.GetFeatureEnablementLabel.return_value = feature_enablement_label
    self._module_collection.ConfigHWID(
        TEST_PROJECT, 3, 'unused raw HWID DB contents', hwid_action=instance)
    return instance

  def testGetDUTLabels_Success(self):
    self._module_collection.AddAVLNameMapping(10, 'AVL_CELLULAR')
    bom = hwid_action.BOM()
    bom.AddComponent('touchscreen', name='testscreen', is_vp_related=True)
    bom.AddComponent('wireless', name='wireless_11_21', is_vp_related=True)
    bom.AddComponent('cellular', name='cellular_10_20', is_vp_related=True)
    bom.project = TEST_PROJECT
    bom.phase = 'bar'
    configless = None
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=[])
    self._SetupFakeHWIDActionForTestProject('feature_enablement_value')
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertCountEqual(
        msg.labels,
        [
            hwid_api_messages_pb2.DutLabel(name='feature_enablement_status',
                                           value='feature_enablement_value'),
            hwid_api_messages_pb2.DutLabel(name='hwid_component',
                                           value='cellular/cellular_10_20'),
            hwid_api_messages_pb2.DutLabel(name='hwid_component',
                                           value='wireless/wireless_11_21'),
            hwid_api_messages_pb2.DutLabel(name='hwid_component',
                                           value='touchscreen/testscreen'),
            hwid_api_messages_pb2.DutLabel(name='cellular',
                                           value='AVL_CELLULAR'),
            hwid_api_messages_pb2.DutLabel(name='phase', value='bar'),
            hwid_api_messages_pb2.DutLabel(name='sku', value='TestSku'),
            hwid_api_messages_pb2.DutLabel(name='touchscreen'),
            hwid_api_messages_pb2.DutLabel(name='variant',
                                           value='found_device'),
            # Fallback due to no AVL name existed.
            hwid_api_messages_pb2.DutLabel(name='wireless',
                                           value='wireless_11_21'),
        ])

  def testGetDUTLabels_WithWarnings(self):
    bom = hwid_action.BOM()
    bom.AddComponent('touchscreen', name='testscreen', is_vp_related=True)
    bom.project = TEST_PROJECT
    bom.phase = 'bar'
    configless = None
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=['warning1', 'warning2'])
    self._SetupFakeHWIDActionForTestProject()
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
    self.assertCountEqual(['warning1', 'warning2'], msg.warnings)

  def testGetDUTLabels_MissingRegexpList(self):
    self._module_collection.fake_goldeneye_memcache.ClearAll()
    bom = hwid_action.BOM()
    bom.AddComponent('touchscreen', name='testscreen', is_vp_related=True)
    bom.project = TEST_PROJECT
    bom.phase = 'bar'
    configless = None
    self._SetupFakeHWIDActionForTestProject()
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=[])

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
                'wireless',
                'cellular',
                'feature_enablement_status',
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
                'wireless',
                'cellular',
                'feature_enablement_status',
            ]), msg)

  def testGetDUTLabels_WithConfigless(self):
    bom = hwid_action.BOM()
    bom.project = TEST_PROJECT
    bom.phase = 'bar'
    configless = {
        'feature_list': {
            'has_touchscreen': 1,
        },
    }
    self._SetupFakeHWIDActionForTestProject()
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: bc_helper.BOMAndConfigless(bom, configless, None),
    }
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=[])

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self._dl_helper.GetDUTLabels(req)

    self.assertTrue(self.CheckForLabelValue(msg, 'phase', 'bar'))
    self.assertTrue(self.CheckForLabelValue(msg, 'variant', 'found_device'))
    self.assertTrue(self.CheckForLabelValue(msg, 'sku', 'TestSku'))
    self.assertTrue(self.CheckForLabelValue(msg, 'touchscreen'))
    self.assertFalse(msg.warnings)

  def testGetDUTLabels_CheckIsVPRelated(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents(
        {
            'battery': 'battery_small',
            'camera': 'camera_0',
            'cpu': ['cpu_0', 'cpu_1'],
        }, comp_db=database.Database.LoadFile(
            GOLDEN_HWIDV3_FILE, verify_checksum=False), require_vp_info=True)
    bom.project = TEST_PROJECT
    bom.phase = 'bar'
    configless = None
    self._SetupFakeHWIDActionForTestProject('feature_value')
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
                hwid_api_messages_pb2.DutLabel(name='feature_enablement_status',
                                               value='feature_value'),
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
                'wireless',
                'cellular',
                'feature_enablement_status',
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
