#!/usr/bin/env python3
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Verifies that new commits do not alter existing encoding patterns.

This test may be invoked in multiple ways:
  1. Execute manually. In this case all the v3 projects listed in projects.yaml
     are checked. The test loads and compares new and old databases from HEAD
     and HEAD~1, respectively, in each corresponding branch of each project.
  2. As a pre-submit check in platform/chromeos-hwid repo. In this case only the
     changed HWID databases in each commit are tested.
  3. VerifyParsedDatabasePattern may be called directly by the HWID Server.
"""

import argparse
import logging
import multiprocessing
import os
import subprocess
import sys
import traceback
import unittest

from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import process_utils


class ValidationError(Exception):
  pass


def _TestDatabase(targs):
  db_path, projects_info, commit, hwid_dir = targs
  project_name = os.path.basename(db_path)
  if project_name not in projects_info:
    logging.info('Removing %s in this commit, skipped', project_name)
    return None
  db_path_in_proj_info = projects_info[project_name]['path']
  if db_path != db_path_in_proj_info:
    logging.info('File path %r mismatch DB path in project info %r, skipped',
                 db_path, db_path_in_proj_info)
    return None
  try:
    title = f'{project_name} {commit}:{db_path}'
    logging.info('Checking %s', title)
    if projects_info[project_name]['branch'] != 'main':
      raise Exception(
          f"Project {projects_info[project_name]['branch']!r} is not on main")
    HWIDDBsPatternTest.VerifyDatabasePattern(hwid_dir, commit, db_path)
    return None
  except Exception:
    return (title, traceback.format_exception(*sys.exc_info()))


class HWIDDBsPatternTest(unittest.TestCase):
  """Unit test for HWID database."""

  def __init__(self, project=None, commit=None):
    super().__init__()
    self.project = project
    self.commit = commit

  def runTest(self):
    hwid_dir = hwid_utils.GetHWIDRepoPath()
    if not os.path.exists(hwid_dir):
      logging.info(
          'ValidHWIDDBsTest: ignored, no %s in source tree.', hwid_dir)
      return

    # Always read projects.yaml from ToT as all projects are required to have an
    # entry in it.
    target_commit = (
        self.commit or os.environ.get('PRESUBMIT_COMMIT') or
        'cros-internal/main')
    projects_info = yaml.safe_load(
        process_utils.CheckOutput(
            ['git', 'show', f'{target_commit}:projects.yaml'], cwd=hwid_dir))


    if self.project:
      if self.project not in projects_info:
        self.fail(f'Invalid project {self.project!r}')
      test_args = [(f'v3/{self.project}', projects_info, target_commit,
                    hwid_dir)]
    else:
      files = os.environ.get('PRESUBMIT_FILES')
      if files:
        test_args = [(os.path.relpath(
            f, hwid_dir), projects_info, target_commit, hwid_dir)
                     for f in files.splitlines()]
      else:
        # If PRESUBMIT_FILES is not found, defaults to test all v3 projects in
        # projects.yaml.
        test_args = [(b['path'], projects_info, target_commit, hwid_dir) for b
                     in projects_info.values() if b['version'] == 3]

    with multiprocessing.Pool() as pool:
      exception_list = pool.map(_TestDatabase, test_args)
    exception_list = list(filter(None, exception_list))

    if exception_list:
      error_msg = []
      for title, err_msg_lines in exception_list:
        error_msg.append(f'Error occurs in {title}\n' +
                         ''.join('  ' + l for l in err_msg_lines))
      raise Exception('\n'.join(error_msg))

  @staticmethod
  def GetOldNewDB(hwid_dir, commit, db_path):
    """Get old and new DB.

    Get the DB in commit and the previous version (None not applicable).

    Args:
      hwid_dir: Path of the base directory of HWID databases.
      commit: The commit hash value of the newest version of HWID database.
      db_path: Path of the HWID database to be verified.
    Returns:
      tuple (old_db, new_db), old_db could be None if the commit is the init
      commit for the project.
    """
    # A compatible version of HWID database can be loaded successfully.
    new_db = process_utils.CheckOutput(['git', 'show', f'{commit}:{db_path}'],
                                       cwd=hwid_dir, ignore_stderr=True)

    try:
      old_db = process_utils.CheckOutput(
          ['git', 'show', f'{commit}~1:{db_path}'], cwd=hwid_dir,
          ignore_stderr=True)
    except subprocess.CalledProcessError as e:
      if e.returncode != 128:
        raise e
      logging.info('Adding new HWID database %s; skip pattern check',
                   os.path.basename(db_path))
      return None, new_db

    return old_db, new_db

  @staticmethod
  def VerifyDatabasePattern(hwid_dir, commit, db_path):
    """Verify the specific HWID database.

    This method obtains the old_db and new_db, creates a context about
    filesystem used in name_pattern_adapter.NamePatternAdapter, and passes to
    ValidateChange static method.

    Args:
      hwid_dir: Path of the base directory of HWID databases.
      commit: The commit hash value of the newest version of HWID database.
      db_path: Path of the HWID database to be verified.
    """
    old_db, new_db = HWIDDBsPatternTest.GetOldNewDB(hwid_dir, commit, db_path)
    analyzer = contents_analyzer.ContentsAnalyzer(new_db, None, old_db)
    report = analyzer.ValidateChange(ignore_invalid_old_db=True)
    if report.errors:
      raise ValidationError(str(report.errors))


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--commit', help='the commit to test')
  parser.add_argument('--project', type=str, default=None,
                      help='name of the project to test')
  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO)

  runner = unittest.TextTestRunner()
  test = HWIDDBsPatternTest(project=args.project, commit=args.commit)
  result = runner.run(test)
  sys.exit(0 if result.wasSuccessful() else 1)
