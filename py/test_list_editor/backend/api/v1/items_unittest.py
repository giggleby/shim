#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import unittest
from unittest import mock

from flask import Flask

from cros.factory.test_list_editor.backend.api.v1 import items
from cros.factory.test_list_editor.backend.controller import test_list
from cros.factory.test_list_editor.backend.schema import common as common_schema
from cros.factory.test_list_editor.backend.schema import test_list as test_list_schema


class TestItemsEndpoint(unittest.TestCase):

  def setUp(self) -> None:
    with mock.patch.object(
        items.test_list_controller, 'TestListController',
        spec=test_list.TestListController) as mock_tl_controller:
      self.mock_data = test_list_schema.TestItem(test_item_id='ABC',
                                                 display_name='A B C')
      mock_tl_controller.return_value.GetTestListItemList.return_value = (
          test_list_schema.ItemListResponse(
              status=common_schema.StatusEnum.SUCCESS,
              data={'ABC': self.mock_data}))
      mock_tl_controller.return_value.GetItem.return_value = (
          test_list_schema.TestItemsResponse(
              status=common_schema.StatusEnum.SUCCESS, data=self.mock_data))
      mock_tl_controller.return_value.CreateItem.return_value = (
          test_list_schema.TestItemsResponse(
              status=common_schema.StatusEnum.SUCCESS, data=self.mock_data))
      mock_tl_controller.return_value.UpdateItem.return_value = (
          test_list_schema.TestItemsResponse(
              status=common_schema.StatusEnum.SUCCESS, data=self.mock_data))

      flask_app = Flask(__name__)
      flask_app.register_blueprint(items.CreateBP())
      self.client = flask_app.test_client()

  def testGetItemList(self):
    response = self.client.get('/api/v1/items/fake.test_list')
    self.assertEqual(response.status_code, 200)

  def testGetItem(self):
    response = self.client.get('/api/v1/items/fake.test_list/ABC')
    self.assertEqual(response.status_code, 200)

  def testCreateItems(self):
    response = self.client.post('/api/v1/items/fake.test_list',
                                json={'data': self.mock_data.dict()})
    self.assertEqual(response.status_code, 200)

  def testUpdateItems(self):
    response = self.client.put('/api/v1/items/fake.test_list',
                               json={'data': self.mock_data.dict()})
    self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
  unittest.main()
