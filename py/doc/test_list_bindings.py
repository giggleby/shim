# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Sphinx extension for preprocessing including test list objects."""

from typing import Any, Dict, Tuple

from sphinx import application
from sphinx.directives import code
from sphinx import errors

from cros.factory.test.test_lists import manager
from cros.factory.utils import config_utils
from cros.factory.utils import json_utils


# We sort the displayed json according to the key created by this function.
# The weights come from cyueh's human neural network.
def _GetFieldComparableKey(value: Tuple[str, str]):
  return {
      'pytest_name': 0,
      'label': 1,
      'run_if': 2,
      'args': 999,
  }.get(value[0], 500)


class TestListDirectiveError(errors.SphinxError):
  category = 'Including test_list error'


class TestListDirective(code.CodeBlock):
  """A directive for including test list in pytest documents.

  An example usage:
  ```
  .. test_list::

    generic_main:FFT.CameraTests.FrontCameraLED

  ```

  The line breaks are required for CodeBlock to work.
  """
  has_content = True
  directive_name = 'test_list'
  error_messages_template = (
      '\n'
      '  The content of `.. {}` must be a valid test object name.\n'
      '  content={!r}.\n'
      '  Use `bin/factory test-list --list` to list available test lists.\n'
      '  Use '
      '`bin/test_list_insight show $test_list_id . | grep -E "^[^ {{}}]+$" to '
      'list available test objects in a test list.')

  def run(self):
    if len(self.content) != 1:
      raise TestListDirectiveError(
          f'The content of `.. {self.directive_name}` must be exact one line '
          f'which contains the test object name. content={self.content}.')

    test_object_name = self.content[0]
    test_list_id, test_object_path = test_object_name.split(':', 1)

    test_list_manager = manager.Manager()
    try:
      test_list = test_list_manager.GetTestListByID(test_list_id)
    except config_utils.ConfigNotFoundError as exc:
      raise TestListDirectiveError(
          f'Test list id {test_list_id!r} is not found. ' +
          self.error_messages_template.format(self.directive_name,
                                              test_object_name)) from exc

    factory_test_list = test_list.ToFactoryTestList()
    factory_test_object = factory_test_list.LookupPath(test_object_path)
    if factory_test_object is None:
      raise TestListDirectiveError(
          f'Test object path {test_object_path!r} is not found in '
          f'{test_list_id!r}. ' + self.error_messages_template.format(
              self.directive_name, test_object_name))

    dict_test_object: Dict[str, Any] = factory_test_object.ToStruct(
        remove_default=True)
    dict_test_object.pop('id', None)
    dict_test_object.pop('locals', None)

    # Resolve i18n label.
    label = dict_test_object.pop('label', None)
    if isinstance(label, dict) and 'en-US' in label:
      label = label['en-US']
    dict_test_object['label'] = label

    ordered_dict_test_object = dict(
        sorted(dict_test_object.items(), key=_GetFieldComparableKey))
    self.content = json_utils.DumpStr(ordered_dict_test_object, indent=2,
                                      separators=(',', ': ')).splitlines()
    return super().run()


def setup(app: application.Sphinx):
  app.add_directive(TestListDirective.directive_name, TestListDirective)

  return {
      'version': '0.1',
      'parallel_read_safe': True,
      'parallel_write_safe': True,
  }
