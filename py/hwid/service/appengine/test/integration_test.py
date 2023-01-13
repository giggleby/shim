#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for AppEngine Integration."""

import argparse
import logging
import os
import re
import sys

from cros.factory.utils import file_utils
from cros.factory.utils import process_utils

HOST_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_APPENGINE_DIR = os.path.dirname(HOST_TEST_DIR)
APPENGINE_MODULE_PREFIX = 'cros.factory.hwid.service.appengine.'
HOST_FACTORY_DIR = os.path.abspath(
    os.path.join(HOST_APPENGINE_DIR, '../../../../../..'))
HOST_DEPLOY_DIR = os.path.join(HOST_FACTORY_DIR, 'deploy')
GUEST_FACTORY_DIR = '/usr/src/cros/factory'
DEPLOY_SCRIPT = os.path.join(HOST_DEPLOY_DIR, 'cros_hwid_service.sh')
DEFAULT_DOCKER_IMAGE_NAME = 'hwid_service:latest'


def _PrepareTests(test_names):
  """Lists test paths.

  Args:
    test_names: A list of test names to run. None for returning all tests.

  Returns:
    A list of test paths in docker image.
  """

  def _CanonicalizeTestName(test_name):
    fullpath = os.path.join(HOST_APPENGINE_DIR, test_name)
    if not os.path.isfile(fullpath):
      raise ValueError(f'Test {test_name} not exists (path: {fullpath})')
    return APPENGINE_MODULE_PREFIX + test_name.rstrip('.py').replace('/', '.')

  def _ListAllTests():
    all_files = []
    for base_path, unused_dir_names, file_names in os.walk(HOST_APPENGINE_DIR):
      if base_path == HOST_APPENGINE_DIR:
        rel_base_path = ''
      else:
        rel_base_path = os.path.relpath(base_path, HOST_APPENGINE_DIR)
      if rel_base_path == 'test':
        continue
      all_files.extend([
          os.path.join(rel_base_path, fn)
          for fn in file_names
          if fn.endswith('_test.py')
      ])
    return [_CanonicalizeTestName(tn) for tn in all_files]

  if test_names:
    return [_CanonicalizeTestName(tn) for tn in test_names]
  return _ListAllTests()


def _BuildDockerImage():
  """Builds docker image and returns the image tag."""
  out = process_utils.CheckOutput([DEPLOY_SCRIPT, 'build'], log=True,
                                  cwd=HOST_FACTORY_DIR)
  return re.search(r'^Successfully tagged (\w+:\w+)', out,
                   re.MULTILINE).group(1)


def RunTest(image, test_names):
  """Runs the given tests.

  Args:
    image: A string for docker image name.
    test_names: A list of test names to run.
  Returns:
    True if all tests pass.
  """
  container_id = process_utils.CheckOutput(
      ['docker', 'run', '-d', '-it', '--rm', image], log=True).strip()

  p = process_utils.Spawn(
      ['docker', 'exec', container_id, '/usr/src/check_datastore_status.sh'],
      read_stderr=True, log=True)

  if p.returncode != 0:
    logging.error('Failed to start server. code=%d. stderr: %s', p.returncode,
                  p.stderr_data)
    return False

  failed_tests = []
  for tn in test_names:
    p = process_utils.Spawn(
        ['docker', 'exec', container_id, 'python', '-m', tn], read_stdout=True,
        read_stderr=True, log=True)
    if p.returncode != 0:
      temp_path = file_utils.CreateTemporaryFile()
      file_utils.WriteFile(
          temp_path,
          'stdout:\n' + p.stdout_data + '\nstderr:\n' + p.stderr_data)
      failed_tests.append((tn, temp_path))

  logging.info('[%s/%s] Passed',
               len(test_names) - len(failed_tests), len(test_names))

  for t in failed_tests:
    logging.error('FAILED: %s', t)

  process_utils.LogAndCheckCall(['docker', 'stop', container_id])

  return not failed_tests


def main():
  logging.getLogger().setLevel(int(os.environ.get('LOG_LEVEL') or logging.INFO))
  parser = argparse.ArgumentParser(description='AppEngine Interation Test')
  parser.add_argument(
      '--no-build', action='store_true',
      help='Not building latest docker image, use default image.')
  parser.add_argument(
      'test_names', nargs='*', default=[],
      help=("Path names, relative to the HWID Server's appengine source code "
            'folder, of tests to run.'))
  args = parser.parse_args()

  image = DEFAULT_DOCKER_IMAGE_NAME if args.no_build else _BuildDockerImage()
  tests_to_run = _PrepareTests(args.test_names)
  if not RunTest(image, tests_to_run):
    sys.exit(1)


if __name__ == '__main__':
  main()
