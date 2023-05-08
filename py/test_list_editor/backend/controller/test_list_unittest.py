# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test_list_editor.backend.controller import test_list as test_list_controller
from cros.factory.test_list_editor.backend.models import test_list as test_list_model
from cros.factory.test_list_editor.backend.schema import common as common_schema
from cros.factory.test_list_editor.backend.schema import test_list as test_list_schema


class TestItemsController(unittest.TestCase):

  def setUp(self) -> None:
    self.fake_factory = mock.Mock()
    self.fake_loaded_data = mock.Mock()
    self.fake_test_list = mock.Mock(spec=test_list_model.TestList)
    self.fake_test_list.GetTestDefinitions.return_value = {}
    self.fake_test_list.GetTestItemConfig.return_value = {
        'test_item_id': '',
        'display_name': ''
    }
    self.fake_diff = mock.Mock(spec=test_list_model.DiffUnit)

  def testGetItemList(self):
    self.fake_factory.Get.return_value = self.fake_loaded_data
    controller = test_list_controller.TestListController(self.fake_factory)
    response = controller.GetTestListItemList('', self.fake_test_list)
    self.assertEqual(response.status, common_schema.StatusEnum.SUCCESS)
    self.assertEqual(response.data, {})

  def testGetItem(self):
    self.fake_loaded_data.data = {}
    self.fake_factory.Get.return_value = self.fake_loaded_data
    controller = test_list_controller.TestListController(self.fake_factory)

    response = controller.GetItem('fake_list_id', self.fake_test_list,
                                  'fake_item_id')
    self.assertEqual(response.status, common_schema.StatusEnum.SUCCESS)
    self.assertEqual(
        response.data, {
            'test_item_id': '',
            'display_name': '',
            'subtests': [],
            'inherit': 'FactoryTest'
        })

  def testCreateItem(self):
    self.fake_loaded_data.diff_data = {
        'diff_data': True
    }
    self.fake_loaded_data.data = {}
    self.fake_factory.Get.return_value = self.fake_loaded_data

    fake_item = test_list_schema.TestItem(
        test_item_id='test123', display_name='test123', subtests=['a', 'b'],
        inherit='test321')

    controller = test_list_controller.TestListController(self.fake_factory)

    response = controller.CreateItem('', mock.Mock(), fake_item)
    self.assertEqual(response.status, common_schema.StatusEnum.SUCCESS)
    self.assertEqual(
        response.data, {
            'test_item_id': 'test123',
            'display_name': 'test123',
            'subtests': ['a', 'b'],
            'inherit': 'test321'
        })

  def testUpdateItem(self):
    self.fake_loaded_data.diff_data = {
        'diff_data': True
    }
    self.fake_loaded_data.data = {}
    self.fake_factory.Get.return_value = self.fake_loaded_data

    fake_item = test_list_schema.TestItem(
        test_item_id='test123', display_name='test123', subtests=['a', 'b'],
        inherit='test321')

    controller = test_list_controller.TestListController(self.fake_factory)

    response = controller.UpdateItem('', mock.Mock(), fake_item)
    self.assertEqual(response.status, common_schema.StatusEnum.SUCCESS)
    self.assertEqual(
        response.data, {
            'test_item_id': 'test123',
            'display_name': 'test123',
            'subtests': ['a', 'b'],
            'inherit': 'test321'
        })
