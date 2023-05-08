# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from flask import Blueprint

from cros.factory.test_list_editor.backend.controller import test_list as test_list_controller
from cros.factory.test_list_editor.backend.middleware import validation
from cros.factory.test_list_editor.backend.models import files as files_model
from cros.factory.test_list_editor.backend.models import test_list as test_list_model
from cros.factory.test_list_editor.backend.schema import test_list as test_list_schema


def CreateBP():
  bp = Blueprint('items', __name__, url_prefix='/api/v1/items')

  factory = files_model.GetFactoryInstance()
  controller = test_list_controller.TestListController(factory)

  @bp.route('/<test_list_id>')
  @validation.Validate
  def GetTestItemList(
      params: test_list_schema.TestItemListParams
  ) -> test_list_schema.ItemListResponse:
    """Returns a list of test items from the given test_list_id."""
    return controller.GetTestListItemList(params.test_list_id,
                                          test_list_model.TestList())

  @bp.route('/<test_list_id>/<test_item_id>')
  @validation.Validate
  def GetItem(
      params: test_list_schema.TestItemParams
  ) -> test_list_schema.TestItemsResponse:
    """Returns the test item test_list_id."""
    return controller.GetItem(params.test_list_id, test_list_model.TestList(),
                              params.test_item_id)

  @bp.route('/<test_list_id>', methods=['POST'])
  @validation.Validate
  def CreateItem(
      params: test_list_schema.InsertTestItemParams,
      request_body: test_list_schema.UpdateTestItemBody
  ) -> test_list_schema.TestItemsResponse:
    """Creates a test item from test_list_id."""
    return controller.CreateItem(params.test_list_id,
                                 test_list_model.TestList(), request_body.data)

  @bp.route('/<test_list_id>', methods=['PUT'])
  @validation.Validate
  def UpdateItem(
      params: test_list_schema.UpdateTestItemParams,
      request_body: test_list_schema.UpdateTestItemBody
  ) -> test_list_schema.TestItemsResponse:
    """Updates a test item from test_list_id."""
    return controller.UpdateItem(params.test_list_id,
                                 test_list_model.TestList(), request_body.data)

  return bp
