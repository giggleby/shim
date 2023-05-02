#!/usr/bin/env python3
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to run all pre-submit checks."""

import json
import os
import subprocess
import sys


def FilterFiles(folder, files):
  return [file_path for file_path in files if file_path.startswith(
      '' if folder == '.' else folder)]


def CheckTestsPassedInDirectory(folder, files, instruction, checked_file):
  """Checks if all given files are older than previous execution of tests."""
  messages_mapping = {
      '.tests-passed': [
          'Tests have not passed.',
          'Files have changed since last time tests have passed:',
      ],
      '.lint-frontend-passed': [
          'Lints have not passed.',
          'Files have changed since last time lints have passed:',
      ]
  }
  messages = messages_mapping[checked_file]
  files_in_folder = FilterFiles(folder, files)
  if not files_in_folder:
    return True
  tests_file_path = os.path.join(folder, checked_file)
  if not os.path.exists(tests_file_path):
    print(f'{messages[0]}\n{instruction}')
    return False
  mtime = os.path.getmtime(tests_file_path)
  newer_files = [file_path for file_path in files_in_folder
                 if os.path.getmtime(file_path) > mtime]
  if newer_files:
    print('%s\n%s\n%s' % (messages[1], '\n'.join(
        '  ' + file for file in newer_files), instruction))
    return False
  return True


def CheckFactoryRepo(files):
  return CheckTestsPassedInDirectory(
      '.', files, 'Run "make test" in factory repo.', '.tests-passed')


def CheckUmpire(files):
  return CheckTestsPassedInDirectory(
      'py/umpire', files,
      'Please run "setup/cros_docker.sh umpire test" outside chroot.',
      '.tests-passed')


def CheckDome(files):
  return CheckTestsPassedInDirectory(
      'py/dome', files, 'Please run "make test" in py/dome outside chroot.',
      '.tests-passed')


def CheckDomeLint(files):
  return CheckTestsPassedInDirectory(
      'py/dome', files,
      'Please run "make lint-frontend" in py/dome outside chroot.',
      '.lint-frontend-passed')


def CheckEditor(files):
  return CheckTestsPassedInDirectory(
      'py/test_list_editor/backend', files,
      ('Please run "scripts/run-unittest.sh" in test_list_editor/backend'
       ' in editor venv outside chroot.'), '.tests-passed')


def CheckPytestDoc(files):
  all_pytests = json.loads(
      subprocess.check_output(['bin/list_pytests']))
  allow_list = {'py/test/pytests/' + pytest
                for pytest in all_pytests}
  pytests = [file_path for file_path in files if file_path in allow_list]

  # Check if pytest docs follow new template
  bad_files = []
  for test_file in pytests:
    templates = {
        'Description\n': 0,
        'Test Procedure\n': 0,
        'Dependency\n': 0,
        'Examples\n': 0,
    }
    with open(test_file, encoding='utf8') as f:
      for line in f:
        if line in templates:
          templates[line] += 1
    if set(templates.values()) != set([1]):
      bad_files.append(test_file)

  if bad_files:
    print('Python Factory Tests (pytests) must be properly documented:\n%s\n'
          'Please read py/test/pytests/README.md for more information.' %
          '\n'.join('  ' + test_file for test_file in bad_files))
    return False
  return True

def main():
  files = sys.argv[1:]
  all_passed = True
  all_passed &= CheckFactoryRepo(files)
  all_passed &= CheckPytestDoc(files)
  all_passed &= CheckUmpire(files)
  all_passed &= CheckDome(files)
  all_passed &= CheckDomeLint(files)
  all_passed &= CheckEditor(files)
  if all_passed:
    print('All presubmit test passed.')
  else:
    sys.exit(1)


if __name__ == '__main__':
  main()
