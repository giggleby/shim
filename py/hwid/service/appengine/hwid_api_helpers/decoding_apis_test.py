# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
from typing import Optional
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import feature_matching
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper_module
from cros.factory.hwid.service.appengine.hwid_api_helpers import decoding_apis
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper as sku_helper_module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import database


_FeatureEnablementStatus = feature_matching.FeatureEnablementStatus
_FeatureEnablementType = feature_matching.FeatureEnablementType
_FeatureEnablementStatusMsg = hwid_api_messages_pb2.FeatureEnablementStatus
_BOMAndConfigless = bc_helper_module.BOMAndConfigless
_BOMEntry = bc_helper_module.BOMEntry
ComponentMsg = hwid_api_messages_pb2.Component
StatusMsg = hwid_api_messages_pb2.Status
GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata',
    'v3-golden.yaml')

TEST_PROJECT = 'Foo'
TEST_HWID = 'Foo'

_FEATURE_DISABLED_STATUS_MSG = _FeatureEnablementStatusMsg(
    enablement_type=_FeatureEnablementStatusMsg.DISABLED,
    hw_compliance_version=0)


class GetDUTLabelShardTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._module_collection = test_utils.FakeModuleCollection()
    self._vpg_targets = {}
    self._bc_helper = mock.Mock(
        spec=bc_helper_module.BOMAndConfiglessHelper,
        wraps=bc_helper_module.BOMAndConfiglessHelper(
            self._module_collection.fake_decoder_data_manager,
            self._module_collection.fake_bom_data_cacher,
        ))
    self._sku_helper = mock.Mock(
        spec=sku_helper_module.SKUHelper, wraps=sku_helper_module.SKUHelper(
            self._module_collection.fake_decoder_data_manager))
    self.service = decoding_apis.GetDUTLabelShard(
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
      self,
      feature_enablement_status: Optional[_FeatureEnablementStatus] = None):
    if feature_enablement_status is None:
      feature_enablement_status = _FeatureEnablementStatus.FromHWIncompliance()
    instance = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    instance.GetFeatureEnablementStatus.return_value = feature_enablement_status
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
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper_module.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=[])
    self._SetupFakeHWIDActionForTestProject()
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None),
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self.service.GetDutLabels(req)

    self.assertCountEqual(
        msg.labels,
        [
            hwid_api_messages_pb2.DutLabel(name='feature_enablement_status',
                                           value='DISABLED:0'),
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
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper_module.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=['warning1', 'warning2'])
    self._SetupFakeHWIDActionForTestProject()
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None),
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self.service.GetDutLabels(req)

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
        TEST_HWID: _BOMAndConfigless(bom, configless, None),
    }
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper_module.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=[])

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self.service.GetDutLabels(req)

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
    msg = self.service.GetDutLabels(req)

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
        TEST_HWID: _BOMAndConfigless(bom, configless, None),
    }
    self._sku_helper.GetSKUFromBOM.return_value = sku_helper_module.SKU(
        sku_str='TestSku', project='', cpu=None, memory_str='', total_bytes=0,
        warnings=[])

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self.service.GetDutLabels(req)

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
    self._SetupFakeHWIDActionForTestProject()
    self._bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None),
    }

    req = hwid_api_messages_pb2.DutLabelsRequest(hwid=TEST_HWID)
    msg = self.service.GetDutLabels(req)

    self.assertEqual(
        hwid_api_messages_pb2.DutLabelsResponse(
            status=hwid_api_messages_pb2.Status.SUCCESS,
            labels=[
                # Only components with 'is_vp_related=True' will be reported as
                # hwid_component.
                hwid_api_messages_pb2.DutLabel(name='feature_enablement_status',
                                               value='DISABLED:0'),
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


class GetBOMShardTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._default_fake_bc_helper = bc_helper_module.BOMAndConfiglessHelper(
        self._modules.fake_decoder_data_manager,
        self._modules.fake_bom_data_cacher)
    self._mock_bc_helper = mock.Mock(
        spec=bc_helper_module.BOMAndConfiglessHelper,
        wrap=self._default_fake_bc_helper)
    self.service = decoding_apis.GetBOMShard(
        self._modules.fake_hwid_action_manager, self._mock_bc_helper)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def _SetupFakeHWIDAction(
      self, project_name: str,
      feature_enablement_status: Optional[_FeatureEnablementStatus] = None):
    if feature_enablement_status is None:
      feature_enablement_status = _FeatureEnablementStatus.FromHWIncompliance()
    instance = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    instance.GetFeatureEnablementStatus.return_value = feature_enablement_status
    self._modules.ConfigHWID(project_name, 3, 'unused raw HWID DB contents',
                             hwid_action=instance)
    return instance

  def testGetBom_InternalError(self):
    self._mock_bc_helper.BatchGetBOMEntry.return_value = {}

    req = hwid_api_messages_pb2.BomRequest(hwid=TEST_HWID)
    msg = self.service.GetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BomResponse(error='Internal error',
                                          status=StatusMsg.SERVER_ERROR), msg)

  def testGetBom_Success(self):
    self._SetupFakeHWIDAction(
        'proj1',
        _FeatureEnablementStatus(
            enablement_type=_FeatureEnablementType.HARD_BRANDED,
            hw_compliance_version=1,
        ))

    self._mock_bc_helper.BatchGetBOMEntry.return_value = {
        TEST_HWID:
            _BOMEntry([
                ComponentMsg(name='qux', component_class='baz'),
            ], '', '', StatusMsg.SUCCESS, 'proj1')
    }

    req = hwid_api_messages_pb2.BomRequest(hwid=TEST_HWID)
    msg = self.service.GetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BomResponse(
            status=StatusMsg.SUCCESS,
            components=[
                ComponentMsg(name='qux', component_class='baz'),
            ],
            feature_enablement_status=_FeatureEnablementStatusMsg(
                enablement_type=_FeatureEnablementStatusMsg.HARD_BRANDED,
                hw_compliance_version=1),
            feature_enablement_status_legacy='hard_branded:1',
        ), msg)

  def testGetBom_WithError(self):
    self._mock_bc_helper.BatchGetBOMEntry.return_value = {
        TEST_HWID: _BOMEntry([], '', 'bad hwid', StatusMsg.BAD_REQUEST, '')
    }

    req = hwid_api_messages_pb2.BomRequest(hwid=TEST_HWID)
    msg = self.service.GetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BomResponse(status=StatusMsg.BAD_REQUEST,
                                          error='bad hwid'), msg)

  def testBatchGetBom(self):
    hwid1 = 'TEST HWID 1'
    hwid2 = 'TEST HWID 2'
    self._mock_bc_helper.BatchGetBOMEntry.return_value = {
        hwid1:
            _BOMEntry([
                ComponentMsg(name='qux1', component_class='baz1'),
                ComponentMsg(name='rox1', component_class='baz1'),
            ], '', '', StatusMsg.SUCCESS, 'TEST'),
        hwid2:
            _BOMEntry([
                ComponentMsg(name='qux2', component_class='baz2'),
                ComponentMsg(name='rox2', component_class='baz2'),
            ], '', '', StatusMsg.SUCCESS, 'TEST'),
    }
    self._SetupFakeHWIDAction('TEST')

    req = hwid_api_messages_pb2.BatchGetBomRequest(hwid=[hwid1, hwid2])
    msg = self.service.BatchGetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BatchGetBomResponse(
            boms={
                hwid1:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SUCCESS,
                        components=[
                            ComponentMsg(name='qux1', component_class='baz1'),
                            ComponentMsg(name='rox1', component_class='baz1'),
                        ],
                        feature_enablement_status_legacy='not_branded:0',
                        feature_enablement_status=_FEATURE_DISABLED_STATUS_MSG,
                    ),
                hwid2:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SUCCESS,
                        components=[
                            ComponentMsg(name='qux2', component_class='baz2'),
                            ComponentMsg(name='rox2', component_class='baz2'),
                        ],
                        feature_enablement_status_legacy='not_branded:0',
                        feature_enablement_status=_FEATURE_DISABLED_STATUS_MSG,
                    ),
            }, status=StatusMsg.SUCCESS), msg)

  def testBatchGetBom_WithError(self):
    hwid1 = 'TEST HWID 1'
    hwid2 = 'TEST HWID 2'
    hwid3 = 'TEST HWID 3'
    hwid4 = 'TEST HWID 4'
    self._mock_bc_helper.BatchGetBOMEntry.return_value = {
        hwid1:
            _BOMEntry([], '', 'value error', StatusMsg.BAD_REQUEST, ''),
        hwid2:
            _BOMEntry([], '', "'Invalid key'", StatusMsg.NOT_FOUND, ''),
        hwid3:
            _BOMEntry([], '', 'index error', StatusMsg.SERVER_ERROR, ''),
        hwid4:
            _BOMEntry([
                ComponentMsg(name='qux', component_class='baz'),
                ComponentMsg(name='rox', component_class='baz'),
                ComponentMsg(name='bar', component_class='foo'),
            ], '', '', StatusMsg.SUCCESS, 'TEST'),
    }
    self._SetupFakeHWIDAction('TEST')

    req = hwid_api_messages_pb2.BatchGetBomRequest(hwid=[hwid1, hwid2])
    msg = self.service.BatchGetBom(req)

    self.assertEqual(
        hwid_api_messages_pb2.BatchGetBomResponse(
            boms={
                hwid1:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.BAD_REQUEST, error='value error'),
                hwid2:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.NOT_FOUND, error="'Invalid key'"),
                hwid3:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SERVER_ERROR, error='index error'),
                hwid4:
                    hwid_api_messages_pb2.BatchGetBomResponse.Bom(
                        status=StatusMsg.SUCCESS,
                        components=[
                            ComponentMsg(name='qux', component_class='baz'),
                            ComponentMsg(name='rox', component_class='baz'),
                            ComponentMsg(name='bar', component_class='foo'),
                        ],
                        feature_enablement_status_legacy='not_branded:0',
                        feature_enablement_status=_FEATURE_DISABLED_STATUS_MSG,
                    ),
            }, status=StatusMsg.BAD_REQUEST, error='value error'), msg)


class GetSKUShardTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._fake_default_bc_helper = bc_helper_module.BOMAndConfiglessHelper(
        self._modules.fake_decoder_data_manager,
        self._modules.fake_bom_data_cacher,
    )
    self._mock_bc_helper = mock.Mock(
        spec=bc_helper_module.BOMAndConfiglessHelper,
        wraps=self._fake_default_bc_helper)
    self._fake_sku_helper = sku_helper_module.SKUHelper(
        self._modules.fake_decoder_data_manager)

    self.service = decoding_apis.GetSKUShard(
        self._modules.fake_hwid_action_manager, self._mock_bc_helper,
        self._fake_sku_helper)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def _SetupFakeHWIDAction(
      self, project_name: str,
      feature_enablement_status: Optional[_FeatureEnablementStatus] = None):
    if feature_enablement_status is None:
      feature_enablement_status = _FeatureEnablementStatus.FromHWIncompliance()
    instance = mock.create_autospec(hwid_action.HWIDAction, instance=True)
    instance.GetFeatureEnablementStatus.return_value = feature_enablement_status
    self._modules.ConfigHWID(project_name, 3, 'unused raw HWID DB contents',
                             hwid_action=instance)
    return instance

  def testGetSku(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': ['bar1', 'bar2'],
        'dram': ['foo']
    })
    bom.project = 'foo'
    configless = None
    self._SetupFakeHWIDAction(bom.project)
    self._mock_bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None)
    }

    with mock.patch.object(self._fake_sku_helper,
                           'GetTotalRAMFromHWIDData') as mock_func:
      mock_func.return_value = ('1MB', 100000000, [])

      req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
      msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS,
            project='foo',
            cpu='bar1_bar2',
            memory='1MB',
            memory_in_bytes=100000000,
            sku='foo_bar1_bar2_1MB',
            feature_enablement_status_legacy='not_branded:0',
            feature_enablement_status=_FEATURE_DISABLED_STATUS_MSG,
        ), msg)

  def testGetSku_WithConfigless(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': ['bar1', 'bar2'],
        'dram': ['foo']
    })
    bom.project = 'foo'
    configless = {
        'memory': 4
    }
    self._SetupFakeHWIDAction(bom.project)
    self._mock_bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None)
    }

    with mock.patch.object(self._fake_sku_helper,
                           'GetTotalRAMFromHWIDData') as mock_func:
      mock_func.return_value = ('1MB', 100000000, [])

      req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
      msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS,
            project='foo',
            cpu='bar1_bar2',
            memory='4GB',
            memory_in_bytes=4294967296,
            sku='foo_bar1_bar2_4GB',
            feature_enablement_status_legacy='not_branded:0',
            feature_enablement_status=_FEATURE_DISABLED_STATUS_MSG,
        ), msg)

  def testGetSku_DramWithoutSize(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': 'bar',
        'dram': ['fail']
    })
    bom.project = 'foo'
    configless = None
    self._SetupFakeHWIDAction(bom.project)
    self._mock_bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None)
    }

    req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
    msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            project='foo',
            cpu='bar',
            memory_in_bytes=0,
            sku='foo_bar_0B',
            memory='0B',
            status=StatusMsg.SUCCESS,
            warnings=["'fail' does not contain size field"],
            feature_enablement_status_legacy='not_branded:0',
            feature_enablement_status=_FEATURE_DISABLED_STATUS_MSG,
        ), msg)

  def testGetSku_FeatureEnabled(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'cpu': ['bar1', 'bar2'],
        'dram': ['foo']
    })
    bom.project = 'foo'
    configless = None
    self._SetupFakeHWIDAction(
        bom.project,
        _FeatureEnablementStatus(
            enablement_type=_FeatureEnablementType.SOFT_BRANDED_LEGACY,
            hw_compliance_version=1))
    self._mock_bc_helper.BatchGetBOMAndConfigless.return_value = {
        TEST_HWID: _BOMAndConfigless(bom, configless, None)
    }

    with mock.patch.object(self._fake_sku_helper,
                           'GetTotalRAMFromHWIDData') as mock_func:
      mock_func.return_value = ('1MB', 100000000, [])

      req = hwid_api_messages_pb2.SkuRequest(hwid=TEST_HWID)
      msg = self.service.GetSku(req)

    self.assertEqual(
        hwid_api_messages_pb2.SkuResponse(
            status=StatusMsg.SUCCESS,
            project='foo',
            cpu='bar1_bar2',
            memory='1MB',
            memory_in_bytes=100000000,
            sku='foo_bar1_bar2_1MB',
            feature_enablement_status_legacy='soft_branded_legacy:1',
            feature_enablement_status=_FeatureEnablementStatusMsg(
                enablement_type=_FeatureEnablementStatusMsg.SOFT_BRANDED_LEGACY,
                hw_compliance_version=1,
            ),
        ), msg)


if __name__ == '__main__':
  unittest.main()
