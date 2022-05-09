#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for HwidManager and related classes."""

import tempfile
import textwrap
import unittest

from dulwich import objects as dulwich_objects  # pylint: disable=wrong-import-order, import-error

from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import filesystem_adapter


class HWIDDBDataManagerTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    tmpdir = tempfile.TemporaryDirectory()
    self.fs_adapter = filesystem_adapter.LocalFileSystemAdapter(tmpdir.name)
    self.addCleanup(tmpdir.cleanup)
    self.ndb_connector = ndbc_module.NDBConnector()
    self.hwid_db_data_manager = hwid_db_data.HWIDDBDataManager(
        self.ndb_connector, self.fs_adapter)

  def tearDown(self):
    super().tearDown()
    self.hwid_db_data_manager.CleanAllForTest()

  def testListHWIDDBMetadataWithoutExistingProjects(self):
    metadata_list = self.hwid_db_data_manager.ListHWIDDBMetadata()

    self.assertCountEqual([], metadata_list)

  def testListHWIDDBMetadataWithExistingProjects(self):
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDA', 'PROJECTA', '3',
                                                     'sample data')

    metadata_list = self.hwid_db_data_manager.ListHWIDDBMetadata()

    self.assertCountEqual(['PROJECTA'], [m.project for m in metadata_list])

  def testListHWIDDBMetadataOfProjects(self):
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDA', 'PROJECTA', '3',
                                                     'sample data 1')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDB', 'PROJECTB', '3',
                                                     'sample data 2')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDC', 'PROJECTC', '3',
                                                     'sample data 3')

    metadata_list = self.hwid_db_data_manager.ListHWIDDBMetadata(
        projects=['PROJECTA', 'PROJECTB'])

    self.assertCountEqual(['PROJECTA', 'PROJECTB'],
                          [m.project for m in metadata_list])

  def testGetHWIDDBMetadataOfProject(self):
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDA', 'PROJECTA', '3',
                                                     'sample data', 'commit1')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDB', 'PROJECTB', '3',
                                                     'sample data 2', 'commit2')

    metadata = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject('PROJECTA')

    self.assertEqual(metadata.board, 'BOARDA')
    self.assertEqual(metadata.path, 'PROJECTA')
    self.assertEqual(metadata.version, '3')
    self.assertEqual(metadata.project, 'PROJECTA')
    self.assertEqual(metadata.commit, 'commit1')

  def testListHWIDDBMetadataOfVersion(self):
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDA', 'PROJECTA', '1',
                                                     'sample data 1')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDB', 'PROJECTB', '2',
                                                     'sample data 2')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDC', 'PROJECTC', '3',
                                                     'sample data 3')

    metadata_list = self.hwid_db_data_manager.ListHWIDDBMetadata(
        versions=['1', '2'])

    self.assertCountEqual(['PROJECTA', 'PROJECTB'],
                          [m.project for m in metadata_list])

  def testGetHWIDDBMetadataOfProjectNotFound(self):
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDA', 'PROJECTA', '3',
                                                     'sample data')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDB', 'PROJECTB', '3',
                                                     'sample data 2')

    with self.assertRaises(hwid_db_data.HWIDDBNotFoundError):
      self.hwid_db_data_manager.GetHWIDDBMetadataOfProject('PROJECTC')

  def testLoadHWIDDB(self):
    sample_hwid_db_contents = 'sample data'
    sample_hwid_db_contents_internal = 'sample data internal'
    self.hwid_db_data_manager.RegisterProjectForTest(
        'BOARDA', 'PROJECTA', '3', sample_hwid_db_contents,
        hwid_db_internal=sample_hwid_db_contents_internal)
    metadata = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject('PROJECTA')

    fetched_hwid_db_contents = self.hwid_db_data_manager.LoadHWIDDB(metadata)
    self.assertEqual(sample_hwid_db_contents, fetched_hwid_db_contents)

    fetched_hwid_db_contents_internal = self.hwid_db_data_manager.LoadHWIDDB(
        metadata, internal=True)
    self.assertEqual(sample_hwid_db_contents_internal,
                     fetched_hwid_db_contents_internal)

  def testUpdateProjectContent(self):
    self.hwid_db_data_manager.RegisterProjectForTest(
        'BOARDA', 'PROJECTA', '3', 'will be updated', 'OLD-COMMIT-ID',
        'will be updated(internal)')

    old_metadata = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        project='PROJECTA')
    self.assertEqual('OLD-COMMIT-ID', old_metadata.commit)

    repo_metadata = hwid_repo.HWIDDBMetadata(
        name='PROJECTA', board_name='BOARDA', version='3', path='v3/PROJECTA')

    self.hwid_db_data_manager.UpdateProjectContent(
        repo_metadata, 'PROJECTA', 'updated data', 'updated data(internal)',
        'NEW-COMMIT-ID')

    updated_metadata = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        project='PROJECTA')
    self.assertEqual('NEW-COMMIT-ID', updated_metadata.commit)

    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(updated_metadata), 'updated data')
    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(updated_metadata, internal=True),
        'updated data(internal)')

  def testUpdateProjectContent_CreateNewMetadata(self):
    repo_metadata = hwid_repo.HWIDDBMetadata(
        name='PROJECTA', board_name='BOARDA', version='3', path='v3/PROJECTA')

    self.hwid_db_data_manager.UpdateProjectContent(
        repo_metadata, 'PROJECTA', 'updated data', 'updated data(internal)',
        'NEW-COMMIT-ID')

    created_metadata = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        project='PROJECTA')
    self.assertEqual('NEW-COMMIT-ID', created_metadata.commit)

    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(created_metadata), 'updated data')
    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(created_metadata, internal=True),
        'updated data(internal)')

  def testUpdateProjectsByRepo(self):
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDA', 'PROJECTA', '3',
                                                     'will be updated')
    self.hwid_db_data_manager.RegisterProjectForTest('BOARDB', 'PROJECTB', '3',
                                                     'will be deleted')
    repo = git_util.MemoryRepo('')
    tree = repo.add_files([
        ('projects.yaml', 0o100644,
         textwrap.dedent("""\
            PROJECTA:
              board: BOARDA
              branch: main
              version: 3
              path: v3/PROJECTA
            PROJECTC:
              board: BOARDC
              branch: main
              version: 3
              path: v3/PROJECTC
        """).encode('utf-8')),
        ('v3/PROJECTA', 0o100644, b'updated data'),
        ('v3/PROJECTA.internal', 0o100644, b'updated data (internal)'),
        ('v3/PROJECTC', 0o100644, b'newly added data'),
        ('v3/PROJECTC.internal', 0o100644, b'newly added data (internal)'),
    ], tree=dulwich_objects.Tree())
    repo.do_commit(message=b'the head commit', tree=tree.id)
    expected_commit_id = repo.head().decode()

    hwid_repo_inst = hwid_repo.HWIDRepo(repo, '', '')

    self.hwid_db_data_manager.UpdateProjectsByRepo(
        hwid_repo_inst, hwid_repo_inst.ListHWIDDBMetadata())

    projects = [
        m.project for m in self.hwid_db_data_manager.ListHWIDDBMetadata()
    ]
    self.assertCountEqual(projects, ['PROJECTA', 'PROJECTC'])
    metadata_a = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        'PROJECTA')
    metadata_c = self.hwid_db_data_manager.GetHWIDDBMetadataOfProject(
        'PROJECTC')

    self.assertEqual(metadata_a.commit, expected_commit_id)
    self.assertEqual(metadata_c.commit, expected_commit_id)

    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(metadata_a), 'updated data')
    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(metadata_a, internal=True),
        'updated data (internal)')
    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(metadata_c), 'newly added data')
    self.assertEqual(
        self.hwid_db_data_manager.LoadHWIDDB(metadata_c, internal=True),
        'newly added data (internal)')

    with self.assertRaises(hwid_db_data.HWIDDBNotFoundError):
      self.hwid_db_data_manager.GetHWIDDBMetadataOfProject('PROJECTB')


if __name__ == '__main__':
  unittest.main()
