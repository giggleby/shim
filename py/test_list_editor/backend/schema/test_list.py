# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from typing import Dict, List

from pydantic import BaseModel
from pydantic import Extra

from cros.factory.test_list_editor.backend.schema import common


class TestItemListParams(BaseModel):
  test_list_id: str


class InsertTestItemParams(BaseModel):
  test_list_id: str


class UpdateTestItemParams(BaseModel):
  test_list_id: str


class TestItemParams(BaseModel):
  test_list_id: str
  test_item_id: str


class TestItemDisplay(BaseModel):
  """Display purpose test item container."""
  test_item_id: str
  display_name: str
  subtests: List[str] = []


class TestItem(TestItemDisplay):
  """Test item container."""
  # Fields for test list editor
  # TODO: Make sure to modify the field whenever there is a change.
  # last_modified: datetime.datetime = datetime.datetime.now().isoformat()

  # Other fields are from TestList.
  inherit: str = 'FactoryTest'

  # TODO: Merge the test list fields into this class so we can remove
  # the Extra.allow
  class Config:
    extra = Extra.allow


class UpdateTestItemBody(common.BaseRequest):
  data: TestItem


class ItemListResponse(common.BaseResponse):
  data: Dict[str, TestItemDisplay]


class TestItemsResponse(common.BaseResponse):
  data: TestItem
