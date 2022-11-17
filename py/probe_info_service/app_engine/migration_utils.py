# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import importlib
import logging
import os
import re
from typing import NamedTuple, Optional

from google.cloud import datastore

from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine import datastore_utils
from cros.factory.probe_info_service.app_engine import migration_scripts
from cros.factory.probe_info_service.app_engine.migration_scripts import migration_script_types

MigrationResultCase = migration_script_types.MigrationResultCase


class MigrationReport(NamedTuple):
  script_name: str
  script_order: int
  result_case: MigrationResultCase


class MigrationScriptRunner:

  def __init__(self, script_name: str, script_order: int,
               migrator: migration_script_types.Migrator):
    self.script_name = script_name
    self.script_order = script_order
    self._migrator = migrator

  def Run(self) -> MigrationReport:
    """Runs the migration process."""
    logging.info('Perform %d-th migration %r.', self.script_order,
                 self.script_name)
    try:
      result_case = self._migrator.Run()
      return MigrationReport(self.script_name, self.script_order, result_case)
    except Exception:
      logging.exception('Caught unexpected exception from the migrator of %r.',
                        self.script_name)
      return MigrationReport(self.script_name, self.script_order,
                             MigrationResultCase.FAILED_NOT_ROLLBACKED)


class _MigrationProgressModel(datastore_utils.KeylessModelBase):
  """Stores the progress of the data migration.

  Attributes:
    progress: The index of the last successfully applied migration script.
  """
  progress: int


class MigrationManager:
  _PROGRESS_KEY_PATH = ('MigrationProgress', 'default')

  def __init__(self, migration_script_package=None):
    self._client = datastore.Client()
    self._migration_script_package = (
        migration_script_package or migration_scripts)
    self._pending_runners = None

  def RunNextPendingMigrationScript(self) -> Optional[MigrationReport]:
    """Loads and runs the following migration script.

    Returns:
      The migration script invocation report if there's any.  Or `None` if
      no any remaining migration script.
    """
    if self._pending_runners is None:
      self._LoadPendingScriptRunners()
    if not self._pending_runners:
      return None
    runner = self._pending_runners.popleft()
    report = runner.Run()
    logging.info('Migration report: %r.', report)
    if report.result_case == MigrationResultCase.SUCCESS:
      self.ForwardProgress(report.script_order)
    return report

  def GetProgress(self):
    """Gets the migration progress."""
    return self._GetModel().progress

  def ForwardProgress(self, progress: int):
    """Force sets the migration progress to the given value."""
    model = self._GetModel()
    model.progress = progress
    self._client.put(model.entity)
    logging.info('Marked migration progress to %d.', progress)

  def _GetModel(self):
    key = self._client.key(*self._PROGRESS_KEY_PATH)
    entity = self._client.get(key)
    if entity is None:
      return _MigrationProgressModel.Create(self._client, key, progress=-1)
    return _MigrationProgressModel.FromEntity(entity)

  _MIGRATION_SCRIPT_MODULE_NAME_PATTERN = re.compile(
      r'migration_script_(?P<script_order>\d+)\.py')

  def _LoadPendingScriptRunners(self):
    runners = []
    for script_name in os.listdir(self._migration_script_package.__path__[0]):
      match = self._MIGRATION_SCRIPT_MODULE_NAME_PATTERN.fullmatch(script_name)
      if not match:
        continue
      script_order = int(match.group('script_order'))
      if script_order <= self.GetProgress():
        continue
      logging.info('Loading the migration script %r.', script_name)
      try:
        script_module = importlib.import_module(
            '.' + script_name.rpartition('.')[0],
            self._migration_script_package.__name__)
      except Exception:
        logging.exception('Failed to load the migration script %r.',
                          script_name)
        continue
      migrators = []
      for module_attr_name in dir(script_module):
        module_attr = getattr(script_module, module_attr_name)
        if isinstance(module_attr, migration_script_types.Migrator):
          migrators.append(module_attr)
      if len(migrators) != 1:
        logging.error(
            '%r contains unexpected number of migrator instances (%r).',
            script_name, len(migrators))
        continue
      runners.append(
          MigrationScriptRunner(script_name, script_order, migrators[0]))
    self._pending_runners = collections.deque(
        sorted(runners, key=lambda runner: runner.script_order))

  def CleanupForTest(self):
    """Clean-up stateful data for unittest purpose."""
    if config.Config().is_prod:
      raise RuntimeError(
          f'Cleaning up datastore data for {self._PROGRESS_KEY_PATH!r} '
          'in production runtime environment is forbidden.')
    self._client.delete(self._client.key(*self._PROGRESS_KEY_PATH))
