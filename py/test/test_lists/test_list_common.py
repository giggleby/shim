# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import json
import logging
import os
from typing import Any, Dict

import jsonschema

from cros.factory.test.env import paths
from cros.factory.utils import config_utils
from cros.factory.utils import file_utils


# Directory for test lists.
TEST_LISTS_RELPATH = os.path.join('py', 'test', 'test_lists')
TEST_LISTS_PATH = os.path.join(paths.FACTORY_DIR, TEST_LISTS_RELPATH)

# All test lists must have name: <id>.test_list.json.
TEST_LIST_CONFIG_SUFFIX = '.test_list'

# Test list schema.
TEST_LIST_SCHEMA_NAME = 'test_list'

# File identifying the active test list.
ACTIVE_TEST_LIST_CONFIG_NAME = 'active_test_list'
ACTIVE_TEST_LIST_CONFIG_ID_KEY = 'id'

# The active test list ID is the most important factory data that we
# can't afford it to disappear unexpectedly.  Therefore, instead of
# saving it as a runtime configuration, we would rather saving it as
# a buildtime configuration manually.
ACTIVE_TEST_LIST_CONFIG_RELPATH = os.path.join(
    TEST_LISTS_RELPATH,
    ACTIVE_TEST_LIST_CONFIG_NAME + config_utils.CONFIG_FILE_EXT)
ACTIVE_TEST_LIST_CONFIG_PATH = os.path.join(
    paths.FACTORY_DIR, ACTIVE_TEST_LIST_CONFIG_RELPATH)

# Test list constants config.
TEST_LIST_CONSTANTS_CONFIG_NAME = 'test_list_constants'


def GetTestListConfigName(test_list_id):
  """Returns the test list config name corresponding to `test_list_id`."""
  return test_list_id + TEST_LIST_CONFIG_SUFFIX


def GetTestListConfigFile(test_list_id):
  """Returns the test list config file corresponding to `test_list_id`."""
  return test_list_id + TEST_LIST_CONFIG_SUFFIX + config_utils.CONFIG_FILE_EXT


def GenerateActiveTestListConfig(active_test_list):
  """Returns a dictionary for active test list."""
  return {
      ACTIVE_TEST_LIST_CONFIG_ID_KEY: active_test_list
  }


def ValidateTestListFileSchema(test_list: Dict[str, Any],
                               schema_dir: str = TEST_LISTS_PATH) -> None:
  """Validates the schema of a test list file.

  Args:
    test_list: A dictionary of test items.
    schema_dir: The directory containing the schema file.
      Defaults to `TEST_LISTS_PATH`.

  Raises:
    jsonschema.ValidationError: If the test list is invalid under the current
      schema.
  """
  file_path = os.path.join(schema_dir, 'test_list.schema.json')
  schema = json.loads(file_utils.ReadFile(file_path))
  jsonschema.validate(test_list, schema)


def LoadTestList(
    test_list_id: str,
    config_dirs: str = TEST_LISTS_PATH) -> config_utils.ResolvedConfig:
  """Loads a test list by id.

  Loads the `test_list_id` from disk and returns the dictionary format of it.
  The dictionary returned has the file level "inheritance" resolved.

  Returns:
    ResolvedConfig: The resolved test list.

  Raises:
    ConfigNotFoundError: If no available config is found.
    ConfigFileInvalidError: If the config files are found, but it fails to
      load one of them.
    SchemaFileInvalidError: If the schema file is invalid.
    ConfigInvalidError: If the resolved config is invalid.
  """
  try:
    return config_utils.LoadConfig(
        config_name=test_list_id, schema_name=TEST_LIST_SCHEMA_NAME,
        validate_schema=True, default_config_dirs=config_dirs,
        allow_inherit=True)
  except Exception:
    logging.exception('Test List %s cannot be loaded', test_list_id)
    raise


def SaveTestList(test_list: Dict[str, Any], test_list_name: str,
                 config_dir: str = TEST_LISTS_PATH) -> None:
  """Saves `test_list` on disk with name `test_list_name`.

  The `test_list` will first be validated before storing on disk. The
  `test_list_name` does not need to include ".test_list" or ".json". It will
  be processed inside this function.

  Args:
    test_list: A dictionary of test items.
    test_list_name: The name of the test list.
    config_dir: The directory in which to store the test list.
      Defaults to `TEST_LISTS_PATH`.

  Raises:
    jsonschema.ValidationError: Raised when the test list cannot pass the
      schema validation.
  """
  ValidateTestListFileSchema(test_list)

  test_list_name = GetTestListConfigFile(test_list_name)
  filename = os.path.join(config_dir, test_list_name)

  test_list_string = json.dumps(test_list, indent=2)
  file_utils.WriteFile(filename, test_list_string)
