#!/usr/bin/env python3
# Copyright 2017 The Chromium OS Authors. All rights reserved.
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


def CheckTestsPassedInDirectory(folder, files, instruction):
  """Checks if all given files are older than previous execution of tests."""
  files_in_folder = FilterFiles(folder, files)
  if not files_in_folder:
    return
  tests_file_path = os.path.join(folder, '.tests-passed')
  if not os.path.exists(tests_file_path):
    sys.exit('Tests have not passed.\n%s' % instruction)
  mtime = os.path.getmtime(tests_file_path)
  newer_files = [file_path for file_path in files_in_folder
                 if os.path.getmtime(file_path) > mtime]
  if newer_files:
    sys.exit('Files have changed since last time tests have passed:\n%s\n%s' %
             ('\n'.join('  ' + file for file in newer_files), instruction))


def CheckFactoryRepo(files):
  return CheckTestsPassedInDirectory(
      '.', files, 'Please run "make test" in factory repo inside chroot.')


def CheckUmpire(files):
  return CheckTestsPassedInDirectory(
      'py/umpire', files,
      'Please run "setup/cros_docker.sh umpire test" outside chroot.')


def CheckDome(files):
  return CheckTestsPassedInDirectory(
      'py/dome', files,
      'Please run "make test" in py/dome outside chroot.')


def CheckPytestDoc(files):
  all_pytests = json.loads(
      subprocess.check_output(['bin/list_pytests']))
  allow_list = ['py/test/pytests/' + pytest for pytest in all_pytests]
  pytests = [file_path for file_path in files if file_path in allow_list]
  if not pytests:
    return

  # Check if pytest docs follow new template
  bad_files = []
  for test_file in pytests:
    templates = {
        'Description\n': 0,
        'Test Procedure\n': 0,
        'Dependency\n': 0,
        'Examples\n': 0,
    }
    with open(test_file) as f:
      for line in f:
        if line in templates:
          templates[line] += 1
    if set(templates.values()) != set([1]):
      bad_files.append(test_file)

  if bad_files:
    sys.exit('Python Factory Tests (pytests) must be properly documented:\n%s\n'
             'Please read py/test/pytests/README.md for more information.' %
             '\n'.join('  ' + test_file for test_file in bad_files))


def CheckPyImport(files):

  def ParseFileName(err_msg):
    # ERROR: {file name} Imports are incorrectly sorted and/or formatted.
    return err_msg.split()[1]

  pyFiles = [file for file in files if file.endswith('.py')]
  if not pyFiles:
    return
  ret = subprocess.run(
      ['isort', '--check', '--diff', '--sp', 'devtools/vscode/.isort.cfg'] +
      pyFiles, check=False, stderr=subprocess.PIPE, encoding='utf-8')
  bad_files = [
      ParseFileName(line) for line in ret.stderr.split('\n') if line.strip()
  ]
  if bad_files:
    print('Please sort the imports before submitting for review.')
    print('Please run (in chroot): `isort --sp devtools/vscode/.isort.cfg ' +
          ' '.join(bad_files) + '`')
    sys.exit(1)
  ret.check_returncode()


def main():
  files = sys.argv[1:]
  CheckPyImport(files)
  CheckFactoryRepo(files)
  CheckPytestDoc(files)
  CheckUmpire(files)
  CheckDome(files)
  print('All presubmit test passed.')


if __name__ == '__main__':
  main()
