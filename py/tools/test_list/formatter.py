# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import argparse
import json
import os

from cros.factory.test.test_lists import manager
from cros.factory.test.test_lists import test_list_common


DESCRIPTION = """Fixes the in-line defined test items in the given test list id

  This tool formats the given test list's definition section to make sure each
  test item does not contain inline defined tests in the subtests section.
"""

EPILOG = """Examples:

  To fix "generic_common.test_list":

  py/tools/test_list/formatter.py generic_common.test_list
"""

JSON_FILE_EXTENSION = 'json'


def ParseArguments():
  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG)
  parser.add_argument('test_list_id', type=str, help='The id of the test list')

  return parser.parse_args()


def main():
  args = ParseArguments()

  flattened_filename = f'flattened_{args.test_list_id}.json'

  output_file = os.path.join(test_list_common.TEST_LISTS_PATH,
                             flattened_filename)

  test_list_manager = manager.InlineTestItemFixer(args.test_list_id)
  test_list_manager.Fix()

  with open(output_file, 'w', encoding='UTF8') as f:
    json.dump(test_list_manager.test_list_config, f, indent=2, sort_keys=True)


if __name__ == "__main__":
  main()
