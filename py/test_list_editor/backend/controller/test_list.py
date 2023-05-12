# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import cast

from cros.factory.test_list_editor.backend.models import files as file_model
from cros.factory.test_list_editor.backend.models import test_list as test_list_model
from cros.factory.test_list_editor.backend.schema import common as common_schema
from cros.factory.test_list_editor.backend.schema import test_list as test_list_schema


class TestListController:
  """The controller interacting with the models."""

  def __init__(self, factory: file_model.ITestListFileFactory) -> None:
    self._factory = factory

  def _LoadTestListFromFile(self, test_list_id: str,
                            test_list: test_list_model.TestList) -> None:
    """Loads `test_list_id` into test list model."""
    test_list_file = self._GetTestListFile(test_list_id)
    test_list_file.Load()
    test_list.LoadFromFile(test_list_file)

  def _GetTestListFile(self, test_list_id: str) -> file_model.TestListFile:
    test_list_file = self._factory.Get(filename=test_list_id)
    return cast(file_model.TestListFile, test_list_file)

  def GetTestListItemList(
      self, test_list_id: str, test_list: test_list_model.TestList
  ) -> test_list_schema.TestItemsResponse:
    self._LoadTestListFromFile(test_list_id, test_list)

    return test_list_schema.ItemListResponse(
        status=common_schema.StatusEnum.SUCCESS,
        data=test_list.GetTestDefinitions())

  def GetItem(self, test_list_id: str, test_list: test_list_model.ITestList,
              test_item_id: str) -> test_list_schema.TestItemsResponse:
    self._LoadTestListFromFile(test_list_id, test_list)

    return test_list_schema.TestItemsResponse(
        status=common_schema.StatusEnum.SUCCESS,
        data=test_list.GetTestItemConfig(test_item_id))

  def CreateItem(
      self, test_list_id: str, test_list: test_list_model.ITestList,
      test_item: test_list_schema.TestItem
  ) -> test_list_schema.TestItemsResponse:
    test_list_file = self._GetTestListFile(test_list_id)

    self._LoadTestListFromFile(test_list_id, test_list)
    test_list.UpdateTestItemConfig(test_item)
    test_list.ExportDiff(test_list_file)

    return test_list_schema.TestItemsResponse(
        status=common_schema.StatusEnum.SUCCESS, data=test_item)

  def UpdateItem(
      self, test_list_id: str, test_list: test_list_model.ITestList,
      test_item: test_list_schema.TestItem
  ) -> test_list_schema.TestItemsResponse:
    test_list_file = self._GetTestListFile(test_list_id)

    self._LoadTestListFromFile(test_list_id, test_list)
    test_list.UpdateTestItemConfig(test_item)
    test_list.ExportDiff(test_list_file)

    return test_list_schema.TestItemsResponse(
        status=common_schema.StatusEnum.SUCCESS, data=test_item)

  def GetTestSequence(
      self, test_list_id: str, test_list: test_list_model.TestList
  ) -> test_list_schema.TestSequenceResponse:
    self._LoadTestListFromFile(test_list_id, test_list)

    return test_list_schema.TestSequenceResponse(
        status=common_schema.StatusEnum.SUCCESS,
        data=test_list.GetTestSequence())

  def UpdateTestSequence(
      self, test_list_id: str, test_list: test_list_model.TestList,
      test_sequence: test_list_schema.UpdatedTestSequence
  ) -> test_list_schema.TestSequenceResponse:
    test_list_file = self._GetTestListFile(test_list_id)

    self._LoadTestListFromFile(test_list_id, test_list)
    test_list.UpdateTestSequence(test_sequence)
    test_list.ExportDiff(test_list_file)

    return test_list_schema.TestSequenceResponse(
        status=common_schema.StatusEnum.SUCCESS,
        data=test_list.GetTestSequence())
