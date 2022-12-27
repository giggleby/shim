#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import collections
import copy
import json
from pathlib import Path

from cros.factory.test.rules import phase as phase_module
from cros.factory.tools.format_json_test_list import Format


DESCRIPTION = """Migrates specified test list jsons from old format to new ones.

Currently, the migration includes:

1. Migrate |skipped_tests| and |waived_tests| to |conditional_patch|.
"""

EXAMPLES = """Examples:
1. Migrating one single test list:
    ./migrate_test_list.py --test_list ../test/test_lists/\
generic_main.test_list.json

2. Migrating multiple test lists at the same time:
    ./migrate_test_list.py --test_list ../test/test_lists/\
generic_main.test_list.json ../test/test_lists/generic_rma.test_list.json

3. Migrating all the test lists under specific folder:
    ./migrate_test_list.py --folder ../test/test_lists
"""

PHASE_NAMES = phase_module.PHASE_NAMES


class MigrateOptionException(Exception):
  pass


def ParseArgs():
  parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)

  arg_group = parser.add_mutually_exclusive_group(required=True)
  arg_group.add_argument('--test_list', dest='test_list', nargs='+',
                         help=('The test lists json to be migrated.'))
  arg_group.add_argument(
      '--folder', dest='folder',
      help=('The folder contains all the test list to be '
            'migrated.'))

  return parser.parse_args()


def MigrateTestListOption(test_list, folder):
  if test_list:
    for test_path in test_list:
      if not test_path.endswith('.test_list.json'):
        raise MigrateOptionException(
            f'Invalid extension of test list path detected: {test_path}.')
    test_lists = test_list
  else:
    folder_path = Path(folder)

    if not folder_path.is_dir():
      raise MigrateOptionException('The given path is not a directory.')

    test_lists = list(folder_path.glob('**/*.test_list.json'))

  for path in test_lists:
    MigrateSingleTestList(path)


def MigrateSingleTestList(path):
  print(f'Migrating {path}... ', end='')

  with open(path, 'r', encoding='utf8') as fp:
    test_list = json.load(fp, object_pairs_hook=collections.OrderedDict)

  options = test_list.get('options')
  if options:
    new_options = MigrateSkipAndWaiveTests(options)
    test_list.update(options=new_options)

  new_test_list = Format(test_list)

  with open(path, 'w', encoding='utf8') as fp:
    json.dump(new_test_list, fp, indent=2, separators=(',', ': '),
              ensure_ascii=True)
    fp.write('\n')

  print('Done')


def MigrateSkipAndWaiveTests(old_options):
  new_options = copy.deepcopy(old_options)
  conditional_patches = []

  action_key_mapping = {
      'skipped_tests': 'skip',
      'waived_tests': 'waive',
  }

  for action_key, action_type in action_key_mapping.items():
    if action_key in old_options:
      for key in old_options[action_key]:
        patterns = old_options[action_key][key]
        if key in PHASE_NAMES:
          patch = MakeConditionalPatch(action_type, phase=key,
                                       patterns=patterns)
        else:  # run_if expression
          patch = MakeConditionalPatch(action_type, run_if=key,
                                       patterns=patterns)
        conditional_patches.append(patch)

      del new_options[action_key]

  if conditional_patches:
    new_options['conditional_patches'] = conditional_patches

  return new_options


def MakeConditionalPatch(action, run_if=None, phase=None, patterns=None):
  template = {
      'action': action,
      'conditions': {
          'patterns': patterns or []
      }
  }

  if run_if:
    template['conditions']['run_if'] = run_if

  if phase:
    template['conditions']['phases'] = phase

  return template


def main():
  args = ParseArgs()

  MigrateTestListOption(args.test_list, args.folder)


if __name__ == '__main__':
  main()
