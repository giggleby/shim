# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import importlib
import os.path
import sys
import tempfile
import textwrap
import unittest

from cros.factory.probe_info_service.app_engine import migration_utils
from cros.factory.utils import file_utils


class MigrationManagerTest(unittest.TestCase):
  _MIGRATION_SCRIPT_PKG_NAME = (
      'cros_factory_probe_info_service_app_engine_migration_scripts')
  _MIGRATION_SCRIPT_PKG = None
  _EXTRA_PYTHON_PATH_FOR_TEST = None

  @classmethod
  def setUpClass(cls):
    super().setUpClass()
    cls._EXTRA_PYTHON_PATH_FOR_TEST = tempfile.mkdtemp()
    sys.path.append(cls._EXTRA_PYTHON_PATH_FOR_TEST)
    package_path = os.path.join(cls._EXTRA_PYTHON_PATH_FOR_TEST,
                                cls._MIGRATION_SCRIPT_PKG_NAME)
    file_utils.TryMakeDirs(package_path)
    file_utils.TouchFile(os.path.join(package_path, '__init__.py'))
    cls._MIGRATION_SCRIPT_PKG = importlib.import_module(
        cls._MIGRATION_SCRIPT_PKG_NAME)

  @classmethod
  def tearDownClass(cls):
    sys.path.remove(cls._EXTRA_PYTHON_PATH_FOR_TEST)

  def _CreateMigrationManager(self) -> migration_utils.MigrationManager:
    importlib.reload(self._MIGRATION_SCRIPT_PKG)
    manager = migration_utils.MigrationManager(self._MIGRATION_SCRIPT_PKG)
    self.addCleanup(manager.CleanupForTest)
    return manager

  def _WriteMigrationScript(self, script_name, contents):
    fullpath = os.path.join(self._EXTRA_PYTHON_PATH_FOR_TEST,
                            self._MIGRATION_SCRIPT_PKG_NAME, script_name)
    file_utils.WriteFile(fullpath, contents)
    self.addCleanup(functools.partial(file_utils.TryUnlink, fullpath))

  def testRunNextMigrationScriptsCorrectly(self):
    self._WriteMigrationScript(
        'migration_script_0000.py',
        textwrap.dedent('''
            from cros.factory.probe_info_service.app_engine.migration_scripts \\
                import migration_script_types
            class Migrator(migration_script_types.Migrator):
              def Run(self):
                return migration_script_types.MigrationResultCase.SUCCESS
            MIGRATOR = Migrator()
        '''))
    self._WriteMigrationScript(
        'migration_script_0001.py',
        textwrap.dedent('''
            from cros.factory.probe_info_service.app_engine.migration_scripts \\
                import migration_script_types
            class Migrator(migration_script_types.Migrator):
              def Run(self):
                raise RuntimeError
            MIGRATOR = Migrator()
        '''))
    manager = self._CreateMigrationManager()

    report = manager.RunNextPendingMigrationScript()
    self.assertTupleEqual(
        report,
        migration_utils.MigrationReport(
            'migration_script_0000.py', 0,
            migration_utils.MigrationResultCase.SUCCESS))
    self.assertEqual(manager.GetProgress(), 0)

    report = manager.RunNextPendingMigrationScript()
    self.assertTupleEqual(
        report,
        migration_utils.MigrationReport(
            'migration_script_0001.py', 1,
            migration_utils.MigrationResultCase.FAILED_NOT_ROLLBACKED))
    self.assertEqual(manager.GetProgress(), 0)

  def testForwardProgressMakeOldMigrationScriptSkipped(self):
    self._WriteMigrationScript(
        'migration_script_0000.py',
        textwrap.dedent('''
            from cros.factory.probe_info_service.app_engine.migration_scripts \\
                import migration_script_types
            class Migrator(migration_script_types.Migrator):
              def Run(self):
                return migration_script_types.MigrationResultCase.SUCCESS
            MIGRATOR = Migrator()
        '''))
    manager = self._CreateMigrationManager()

    manager.ForwardProgress(1)

    report = manager.RunNextPendingMigrationScript()
    self.assertIsNone(report)


if __name__ == '__main__':
  unittest.main()
