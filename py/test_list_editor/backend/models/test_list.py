# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import abc
import copy
from datetime import datetime
import re
from typing import Any, Dict, List

from cros.factory.test.test_lists import manager
from cros.factory.test_list_editor.backend.models import files
from cros.factory.utils import config_utils


LABEL_KEY = 'label'
TEST_ITEM_DISPLAY_KEY = 'display_name'
TEST_ITEM_NAME_KEY = 'test_item_id'
LAST_MODIFIED_KEY = 'last_modified'
INHERIT_KEY = 'inherit'
SUBTEST_KEY = 'subtests'

TestItem = Dict[str, Any]
TestItemCollection = Dict[str, TestItem]


def _GenerateDisplayName(s: str) -> str:
  """Splits the input string by capital letters.

  This is just a temporary work for displaying test item names from their key.
  We should leverage the po files to display this properly.
  """
  return ' '.join(re.sub(r'([A-Z])', r' \1', s).split())


def _GetDisplayName(test_item: TestItem, item_name: str) -> str:
  """Gets the test item display (label) name.

  The current logic of deciding the display name follows the below order.
  1. If the item has `TEST_ITEM_DISPLAY_KEY`, then use the value of it.
  2. If the item has `LABEL_KEY`, then use the value of it.
  3. Split the item name by capital letters.
  """
  # TODO(louischiu) Consider i18n and/or better display format
  if TEST_ITEM_DISPLAY_KEY in test_item:
    return test_item[TEST_ITEM_DISPLAY_KEY]
  if LABEL_KEY in test_item:
    return test_item['label']
  # TODO(louischiu) Handle the display name properly. We would have
  # display names like "Read Device Data From V P D".
  return _GenerateDisplayName(item_name)


def _AddFields(test_items: TestItemCollection) -> TestItemCollection:
  """Adds the required fields for each of the test item."""
  updated_test_items = copy.deepcopy(test_items)
  for item_name, test_item in updated_test_items.items():
    # TODO(louischiu) Make the item name display better.
    # TODO(louischiu) Make sure the modifications are properly handled from
    # previous resolve process.
    test_item[TEST_ITEM_NAME_KEY] = item_name
    test_item[TEST_ITEM_DISPLAY_KEY] = _GetDisplayName(test_item, item_name)
    test_item[LAST_MODIFIED_KEY] = datetime.now().isoformat()
  return updated_test_items


def _RemoveFields(test_items: TestItemCollection):
  """Removes the test item definition to test list format."""
  result = copy.deepcopy(test_items)
  for test_item in result.values():
    test_item.pop(TEST_ITEM_NAME_KEY, None)
    test_item.pop(TEST_ITEM_DISPLAY_KEY, None)
    test_item.pop(LAST_MODIFIED_KEY, None)

  return result


def _TraverseInheritanceChain(test_item_id: str,
                              definitions: TestItemCollection) -> List[str]:
  """Returns a list of parent ids of a test item.

  The function starts from the given `test_item_id` and traverses the
  inheritance chain to collect the `test_item_id` of each ancestor test item.
  The resulting list also includes the `test_item_id` passed as an argument.

  The order from left to right would be `test_item_id`, `parent_1`, `parent_2`,
  ...

  Args:
    test_item_id (str): The ID of the test item to start the traversal.
    definitions (TestItemCollection): The collection of test item definitions.

  Returns:
    List[str]: A list of test_item_ids in the inheritance chain.
  """
  result = [test_item_id]
  while True:
    cur_id = result[-1]
    test_item = definitions[cur_id]
    if INHERIT_KEY not in test_item:
      break
    if test_item[INHERIT_KEY] == test_item[TEST_ITEM_NAME_KEY]:
      break
    result.append(test_item[INHERIT_KEY])
  return result


def _ResolveTestItem(override_list: List[str],
                     definitions: TestItemCollection) -> Dict:
  """Resolve the override process from left to right."""

  resolved_config = {}
  for parent_id in override_list:
    parent_config = definitions[parent_id]
    resolved_config.update(parent_config)

  return resolved_config


def _ResolveTestItemInheritance(test_item_id: str,
                                definitions: TestItemCollection) -> TestItem:
  """Returns a resolved test item from `test_item_id`.

  The function returns a test item that has resolved its parent inheritance.

  Args:
    test_item_id (str): The ID of the test item to start the traversal.
    definitions (TestItemCollection): The collection of test item definitions.

  Returns:
    TestItem (TestItem): The resolved test item.
  """

  inheritance_chain = _TraverseInheritanceChain(test_item_id, definitions)
  inheritance_chain.reverse()

  return _ResolveTestItem(inheritance_chain, definitions)


class IDiff(abc.ABC):
  """Interface of Diff container."""

  @abc.abstractmethod
  def Update(self, keys: List[str], value: Any):
    """Update the value."""

  @abc.abstractmethod
  def Combine(self, original_config: Dict):
    """Combine the config."""

  @abc.abstractmethod
  def Load(self, data: Dict):
    """Use the provided data as starting point."""

  @abc.abstractmethod
  def Export(self) -> Dict:
    """Export the current internal structure."""


class DiffUnit(IDiff):

  def __init__(self):
    self._changes = {}

  def Update(self, keys: List[str], value: Any):
    current_dict = self._changes

    for key in keys[:-1]:
      if key not in current_dict:
        current_dict[key] = {}
      current_dict = current_dict[key]

    current_dict[keys[-1]] = copy.deepcopy(value)

  def Combine(self, original_config: Dict):
    combined_config = copy.deepcopy(original_config)
    return config_utils.OverrideConfig(combined_config, self._changes)

  def Load(self, data: Dict):
    self._changes = copy.deepcopy(data)

  def Export(self) -> Dict:
    return copy.deepcopy(self._changes)


class ITestList(abc.ABC):
  """Interface of TestList."""

  @abc.abstractmethod
  def LoadFromFile(self, test_list_file: files.ITestListFile) -> None:
    """Loads the test list from existing `test_list_file`."""

  @abc.abstractmethod
  def GetTestDefinitions(self):
    """Gets the test item definitions"""

  @abc.abstractmethod
  def GetTestItemConfig(self, test_item_id: str) -> Dict:
    """Gets one test item's resolved  definitions"""

  @abc.abstractmethod
  def UpdateTestItemConfig(self, test_item: TestItem):
    """Update the test item's definition"""

  @abc.abstractmethod
  def ExportDiff(self, test_list_file: files.ITestListFile):
    """Exports the diffs to file."""


class TestList(ITestList):
  """The container for a test list.

  This will be the class responsible for interacting with the test list.

  This class will be storing the fields of a test list and a `DiffUnit`
  """

  def __init__(self) -> None:

    self._diff = DiffUnit()
    self._definitions = {}
    self.options = {}
    self.constants = {}
    self.label = {}
    self.tests = []
    self.override_args = {}
    self.inherit = []

  def LoadFromFile(self, test_list_file: files.ITestListFile):
    """Load from data"""
    self._diff.Load(test_list_file.diff_data)
    data = self._diff.Combine(test_list_file.data)

    self._definitions = data.get('definitions', {})
    self._definitions = manager.InlineTestItemFixer.FixInlineTestItems(
        self._definitions)
    self._definitions = _AddFields(self._definitions)

    self.options = data.get('options', {})
    self.constants = data.get('constants', {})
    self.label = data.get('label', {})
    self.tests = data.get('tests', [])
    self.override_args = data.get('override_args', {})
    self.inherit = data.get('inherit', [])

  def ExportDiff(self, test_list_file: files.ITestListFile):
    """Exports the diff made to the test list.

    We only export the diff because we want to preserve the underlying base
    test list. This way, we can make sure we always store the changes made to
    the current test items be in the main test list and not washed out from the
    aggregated results.
    """
    diff = self._diff.Export()
    diff['definitions'] = _RemoveFields(diff.get('definitions', {}))
    test_list_file.diff_data = diff
    test_list_file.SaveDiff()

  def GetTestDefinitions(self):
    return self._definitions

  def GetTestItemConfig(self, test_item_id: str) -> Dict:
    if test_item_id not in self._definitions:
      return {}

    resolved_test_item = _ResolveTestItemInheritance(test_item_id,
                                                     self._definitions)

    # TODO: Consider resolving "locals" field passed from top level tests

    return resolved_test_item

  def UpdateTestItemConfig(self, test_item: TestItem):
    # TODO: Modify this to support Redo/Undo procedures.
    self._diff.Update(['definitions', test_item.test_item_id], test_item.dict())
