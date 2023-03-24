#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Verify HWID service configuration."""

import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
from typing import Mapping, Optional

import jsonschema
import yaml


APPENGINE_DIR = pathlib.Path(__file__).resolve().parent
FACTORY_DIR = APPENGINE_DIR.parent.parent.parent.parent
FACTORY_PRIVATE_DIR = FACTORY_DIR.parent / 'factory-private'
CHROMEOS_HWID_DIR = FACTORY_DIR.parent / 'chromeos-hwid'
CONFIG_SCHEMA_PATH = (
    FACTORY_DIR / 'py/hwid/service/appengine/config.schema.json')
CONFIGURATIONS_YAML_PATH = (
    FACTORY_PRIVATE_DIR / 'config/hwid/service/appengine/configurations.yaml')
PROJECTS_YAML_PATH = CHROMEOS_HWID_DIR / 'projects.yaml'


class ReadGitFileError(Exception):
  """Raised if reading file fails."""


class VerifyError(Exception):
  """Raised if verifying fails."""


def ReadGitFile(path_: pathlib.Path, commit: Optional[str] = None) -> str:
  """Read a file from a specific commit in a Git repository at the specified
     path.

  """

  path = path_.resolve()
  if not commit:
    try:
      return path.read_text()
    except OSError as e:
      raise ReadGitFileError(
          f'Failed to read local file {path_!s}: {e!r}') from e
  try:
    return subprocess.check_output(
        ['git', '-C', path.parent, 'show', f'{commit}:./{path.name}'],
        encoding='utf-8')
  except subprocess.CalledProcessError as e:
    raise ReadGitFileError(
        f'Failed to read file {path_!s} from the commit {commit}: '
        f'{e!r}.') from e


def IsChanged(path: pathlib.Path, repo_path: pathlib.Path) -> bool:
  """Return whether a file is in the PRESUBMIT_FILES list."""

  presubmit_files = os.getenv('PRESUBMIT_FILES', '')
  relpath = path.relative_to(repo_path)
  return str(relpath) in presubmit_files.splitlines()


def LoadConfigSchema(hwid_commit: Optional[str] = None) -> Mapping:
  """Load the JSON schema for HWID service config."""

  schema = json.loads(ReadGitFile(CONFIG_SCHEMA_PATH))
  hwid_db_metadata = yaml.safe_load(
      ReadGitFile(PROJECTS_YAML_PATH, hwid_commit))
  # Limit vpg_targets with model names.
  schema['definitions']['models']['enum'] = sorted(hwid_db_metadata)
  return schema


def VerifyConfig(commit: Optional[str] = None,
                 hwid_commit: Optional[str] = None) -> bool:
  """Verify the HWID service config."""

  if not IsChanged(CONFIGURATIONS_YAML_PATH, FACTORY_PRIVATE_DIR):
    logging.info('VerifyConfig: skipped')
    return True
  config = yaml.safe_load(ReadGitFile(CONFIGURATIONS_YAML_PATH, commit))
  schema = LoadConfigSchema(hwid_commit)
  try:
    jsonschema.validate(instance=config, schema=schema)
  except jsonschema.exceptions.ValidationError as e:
    logging.error('VerifyConfig: Validation error: %s', e.message)
    return False
  return True


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--commit', default=None, help='The commit to test')
  parser.add_argument('--hwid-commit', default=None,
                      help='The commit of chromeos-hwid repo referred to')
  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO)

  rv = VerifyConfig(args.commit, args.hwid_commit)
  sys.exit(0 if rv else 1)
