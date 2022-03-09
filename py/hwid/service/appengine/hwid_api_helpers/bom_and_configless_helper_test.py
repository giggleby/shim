# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper_module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import database


GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata',
    'v3-golden.yaml')

TEST_MODEL = 'FOO'
TEST_HWID = 'Foo ABC'

ComponentMsg = hwid_api_messages_pb2.Component
FieldMsg = hwid_api_messages_pb2.Field
AvlInfoMsg = hwid_api_messages_pb2.AvlInfo
LabelMsg = hwid_api_messages_pb2.Label
Status = hwid_api_messages_pb2.Status
BOMAndConfigless = bc_helper_module.BOMAndConfigless


class BOMAndConfiglessHelperTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._module_collection = test_utils.FakeModuleCollection()
    self._vpg_targets = {}
    self._fake_hwid_action_manager = mock.Mock(
        spec=self._module_collection.fake_hwid_action_manager,
        wraps=self._module_collection.fake_hwid_action_manager)

    self._bc_helper = bc_helper_module.BOMAndConfiglessHelper(
        self._fake_hwid_action_manager, self._vpg_targets,
        self._module_collection.fake_decoder_data_manager)

  def tearDown(self):
    super().tearDown()
    self._module_collection.ClearAll()

  def testBatchGetBOMAndConfigless_PresentAllCases(self):
    """Test that each cases are presented in the result correctly."""
    # PROJ0 doesn't exist.
    # PROJ1 is not available.
    self._module_collection.ConfigHWID('PROJ1', 3, 'db data', hwid_action=None)
    # PROJ2 only accepts the HWID "PROJ2 A-VALID-HWID".
    bom = hwid_action.BOM()
    bom.AddAllComponents({'storage': ['storage1', 'storage2']})
    configless = {
        'has_touchscreen': True,
    }

    def _GetBOMAndConfiglessFakeImpl(hwid_string, *unused_args,
                                     **unused_kwargs):
      if hwid_string == 'PROJ2 A-VALID-HWID':
        return (bom, configless)
      raise hwid_action.InvalidHWIDError()

    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetBOMAndConfigless.side_effect = (
        _GetBOMAndConfiglessFakeImpl)
    self._module_collection.ConfigHWID('PROJ2', 3, 'db data',
                                       hwid_action=fake_hwid_action)

    ret = self._bc_helper.BatchGetBOMAndConfigless(
        ['PROJ0 ABC', 'PROJ1 ABC-DEF', 'PROJ2 ABC-DEF', 'PROJ2 A-VALID-HWID'])

    self.assertIsInstance(ret['PROJ0 ABC'].error,
                          hwid_action_manager.ProjectNotFoundError)
    self.assertIsInstance(ret['PROJ1 ABC-DEF'].error,
                          hwid_action_manager.ProjectUnavailableError)
    self.assertIsInstance(ret['PROJ2 ABC-DEF'].error,
                          hwid_action.InvalidHWIDError)
    self.assertEqual(ret['PROJ2 A-VALID-HWID'].bom, bom)
    self.assertEqual(ret['PROJ2 A-VALID-HWID'].configless, configless)

  def testBatchGetBOMAndConfigless_CacheHWIDActions(self):
    """Test that the local cache works."""
    bom = hwid_action.BOM()
    bom.AddAllComponents({'storage': ['storage1', 'storage2']})
    configless = {
        'has_touchscreen': True
    }
    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetBOMAndConfigless.return_value = (bom, configless)
    self._module_collection.ConfigHWID('PROJ', 3, 'db data',
                                       hwid_action=fake_hwid_action)

    self._bc_helper.BatchGetBOMAndConfigless(
        ['PROJ AAA', 'PROJ BBB', 'PROJ CCC'])

    self.assertEqual(self._fake_hwid_action_manager.GetHWIDAction.call_count, 1)

  def testBatchGetBOMEntry_WithVerboseFlag(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents(
        {
            'battery': 'battery_small',
            'cpu': ['cpu_0', 'cpu_1'],
            'camera': 'camera_0',
        }, comp_db=database.Database.LoadFile(
            GOLDEN_HWIDV3_FILE, verify_checksum=False), verbose=True)
    configless = None
    with self._PatchBatchGetBOMAndConfigless() as patch_method:
      patch_method.return_value = {
          TEST_HWID: BOMAndConfigless(bom, configless, None),
      }

      results = self._bc_helper.BatchGetBOMEntry([TEST_HWID], verbose=True)

    self.assertEqual(
        results, {
            TEST_HWID:
                bc_helper_module.BOMEntry([
                    ComponentMsg(
                        name='battery_small', component_class='battery',
                        fields=[
                            FieldMsg(name='manufacturer',
                                     value='manufacturer1'),
                            FieldMsg(name='model_name', value='model1'),
                            FieldMsg(name='technology', value='Battery Li-ion')
                        ]),
                    ComponentMsg(
                        name='camera_0', component_class='camera', fields=[
                            FieldMsg(name='idProduct', value='abcd'),
                            FieldMsg(name='idVendor', value='4567'),
                            FieldMsg(name='name', value='Camera')
                        ], avl_info=AvlInfoMsg(cid=0, avl_name=''),
                        has_avl=True),
                    ComponentMsg(
                        name='cpu_0', component_class='cpu', fields=[
                            FieldMsg(name='cores', value='4'),
                            FieldMsg(name='name', value='CPU @ 1.80GHz')
                        ], avl_info=AvlInfoMsg(cid=0, avl_name=''),
                        has_avl=True),
                    ComponentMsg(
                        name='cpu_1', component_class='cpu', fields=[
                            FieldMsg(name='cores', value='4'),
                            FieldMsg(name='name', value='CPU @ 2.00GHz')
                        ], avl_info=AvlInfoMsg(cid=1, avl_name=''),
                        has_avl=True)
                ], [], '', '', Status.SUCCESS),
        })

  def testBatchGetBOMEntry_WithLabels(self):
    bom = hwid_action.BOM()
    bom.AddAllLabels({
        'foo': {
            'bar': None,
        },
        'baz': {
            'qux': '1',
            'rox': '2',
        },
    })
    configless = None

    with self._PatchBatchGetBOMAndConfigless() as patch_method:
      patch_method.return_value = {
          TEST_HWID: BOMAndConfigless(bom, configless, None),
      }

      results = self._bc_helper.BatchGetBOMEntry([TEST_HWID])

    self.assertEqual(
        results, {
            TEST_HWID:
                bc_helper_module.BOMEntry([], [
                    LabelMsg(component_class='foo', name='bar'),
                    LabelMsg(component_class='baz', name='qux', value='1'),
                    LabelMsg(component_class='baz', name='rox', value='2'),
                ], '', '', Status.SUCCESS),
        })

  def testBatchGetBOMEntry_WithAvlInfo(self):
    bom = hwid_action.BOM()
    bom.AddAllComponents(
        {'dram': ['dram_1234_5678', 'dram_1234_5678#4', 'not_dram_1234_5678']},
        comp_db=database.Database.LoadFile(GOLDEN_HWIDV3_FILE,
                                           verify_checksum=False), verbose=True)
    configless = None
    self._module_collection.AddAVLNameMapping(1234, 'avl_name_1')
    with self._PatchBatchGetBOMAndConfigless() as patch_method:
      patch_method.return_value = {
          TEST_HWID: BOMAndConfigless(bom, configless, None),
      }

      results = self._bc_helper.BatchGetBOMEntry([TEST_HWID], verbose=True)

    self.assertEqual(
        results, {
            TEST_HWID:
                bc_helper_module.BOMEntry([
                    ComponentMsg(
                        name='dram_1234_5678', component_class='dram', fields=[
                            FieldMsg(name='part', value='part2'),
                            FieldMsg(name='size', value='4G'),
                        ], avl_info=AvlInfoMsg(cid=1234, qid=5678,
                                               avl_name='avl_name_1'),
                        has_avl=True),
                    ComponentMsg(
                        name='dram_1234_5678#4', component_class='dram',
                        fields=[
                            FieldMsg(name='part', value='part2'),
                            FieldMsg(name='size', value='4G'),
                            FieldMsg(name='slot', value='3'),
                        ], avl_info=AvlInfoMsg(cid=1234, qid=5678,
                                               avl_name='avl_name_1'),
                        has_avl=True),
                    ComponentMsg(
                        name='not_dram_1234_5678', component_class='dram',
                        fields=[
                            FieldMsg(name='part', value='part3'),
                            FieldMsg(name='size', value='4G'),
                        ]),
                ], [], '', '', Status.SUCCESS)
        })

  def testBatchGetBOMEntry_BOMIsNone(self):
    with self._PatchBatchGetBOMAndConfigless() as patch_method:
      patch_method.return_value = {
          TEST_HWID: BOMAndConfigless(None, None, None),
      }

      results = self._bc_helper.BatchGetBOMEntry([TEST_HWID])

    self.assertEqual(
        results, {
            TEST_HWID:
                self._CreateBOMEntryWithError(Status.NOT_FOUND,
                                              'HWID not found.'),
        })

  def testBatchGetBOMEntry_FastFailKnownBad(self):
    bad_hwid = 'FOO TEST'

    results = self._bc_helper.BatchGetBOMEntry([bad_hwid])

    self.assertEqual(
        results, {
            bad_hwid:
                self._CreateBOMEntryWithError(
                    Status.KNOWN_BAD_HWID,
                    'No metadata present for the requested project: FOO TEST'),
        })

  def testBatchGetBOMEntry_WithError(self):
    hwid1 = 'TEST HWID 1'
    hwid2 = 'TEST HWID 2'
    hwid3 = 'TEST HWID 3'
    hwid4 = 'TEST HWID 4'
    bom = hwid_action.BOM()
    bom.AddAllComponents({
        'foo': 'bar',
        'baz': ['qux', 'rox'],
    })
    with self._PatchBatchGetBOMAndConfigless() as patch_method:
      patch_method.return_value = {
          hwid1: BOMAndConfigless(None, None, ValueError('value error')),
          hwid2: BOMAndConfigless(None, None, KeyError('Invalid key')),
          hwid3: BOMAndConfigless(None, None, IndexError('index error')),
          hwid4: BOMAndConfigless(bom, None, None),
      }

      results = self._bc_helper.BatchGetBOMEntry([hwid1, hwid2, hwid3, hwid4])

    self.assertEqual(
        results, {
            hwid1:
                self._CreateBOMEntryWithError(Status.BAD_REQUEST,
                                              'value error'),
            hwid2:
                self._CreateBOMEntryWithError(Status.NOT_FOUND,
                                              "'Invalid key'"),
            hwid3:
                self._CreateBOMEntryWithError(Status.SERVER_ERROR,
                                              'index error'),
            hwid4:
                bc_helper_module.BOMEntry([
                    ComponentMsg(name='qux', component_class='baz'),
                    ComponentMsg(name='rox', component_class='baz'),
                    ComponentMsg(name='bar', component_class='foo'),
                ], [], '', '', Status.SUCCESS),
        })

  def _PatchBatchGetBOMAndConfigless(self):
    return mock.patch.object(self._bc_helper, 'BatchGetBOMAndConfigless')

  def _CreateBOMEntryWithError(self, error_code, msg):
    return bc_helper_module.BOMEntry(None, None, '', msg, error_code)


if __name__ == '__main__':
  unittest.main()
