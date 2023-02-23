#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import os
import textwrap
from typing import Dict
import unittest
from unittest import mock

from dulwich import objects as dulwich_objects

from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.utils import file_utils


_SERVER_BOARDS_YAML = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/boards_server.yaml')
_SERVER_BOARDS_DATA = file_utils.ReadFile(_SERVER_BOARDS_YAML, encoding=None)


class HWIDRepoBaseTest(unittest.TestCase):

  def setUp(self):
    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.GetGerritCredentials')
    self._mocked_get_gerrit_credentials = patcher.start()
    self.addCleanup(patcher.stop)
    self._mocked_get_gerrit_credentials.return_value = ('author@email', 'token')

    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.GetGerritAuthCookie')
    self._mocked_get_gerrit_auth_cookie = patcher.start()
    self.addCleanup(patcher.stop)
    self._mocked_get_gerrit_auth_cookie.return_value = 'cookie'

    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.CreateCL')
    self._mocked_create_cl = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.GetCLInfo')
    self._mocked_get_cl_info = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.GetFileContent')
    self._mocked_get_file_content = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.RebaseCL')
    self._mocked_rebase_cl = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(
        'cros.factory.hwid.service.appengine.git_util.GetCommitId')
    self._mocked_get_commit_id = patcher.start()
    self.addCleanup(patcher.stop)


class HWIDRepoTest(HWIDRepoBaseTest):

  def setUp(self):
    super().setUp()
    self._fake_repo = git_util.MemoryRepo('')
    tree = dulwich_objects.Tree()
    self._fake_repo.object_store.add_object(tree)
    self._fake_repo.do_commit(message=b'initial commit', tree=tree.id)

    self._hwid_repo = hwid_repo.HWIDRepo(self._fake_repo, 'test_repo',
                                         'test_branch')

  def testListHWIDDBMetadata_Success(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})

    actual_hwid_db_metadata_list = self._hwid_repo.ListHWIDDBMetadata()

    expected_hwid_db_metadata_list = [
        hwid_repo.HWIDDBMetadata('KBOARD', 'KBOARD', 2, 'KBOARD'),
        hwid_repo.HWIDDBMetadata('KBOARD.old', 'KBOARD', 2, 'KBOARD.old'),
        hwid_repo.HWIDDBMetadata('SBOARD', 'SBOARD', 3, 'SBOARD'),
        hwid_repo.HWIDDBMetadata('COOLCBOARD', 'COOLCBOARD', 3, 'COOLCBOARD'),
        hwid_repo.HWIDDBMetadata('BETTERCBOARD', 'BETTERCBOARD', 3,
                                 'BETTERCBOARD'),
    ]
    self.assertCountEqual(actual_hwid_db_metadata_list,
                          expected_hwid_db_metadata_list)

  def testListHWIDDBMetadata_InvalidProjectYaml(self):
    self._AddFilesToFakeRepo({
        'projects.yaml': b':this_is_not_an_invalid_data ^.<',
    })

    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo.ListHWIDDBMetadata()

  def testLoadHWIDDBByName_Success(self):
    self._AddFilesToFakeRepo({
        'projects.yaml': _SERVER_BOARDS_DATA,
        'SBOARD': b'sboard data',
        'SBOARD.internal': b'sboard data (internal)',
    })

    actual_hwid_db = self._hwid_repo.LoadHWIDDBByName('SBOARD')
    self.assertEqual('sboard data', actual_hwid_db)

    actual_hwid_db_internal = self._hwid_repo.LoadHWIDDBByName(
        'SBOARD', internal=True)
    self.assertEqual('sboard data (internal)', actual_hwid_db_internal)

  def testLoadHWIDDBByName_InvalidName(self):
    self._AddFilesToFakeRepo({
        'projects.yaml': _SERVER_BOARDS_DATA,
        'SBOARD': b'sboard data',
    })

    with self.assertRaises(ValueError):
      self._hwid_repo.LoadHWIDDBByName('NO_SUCH_BOARD')

  def testLoadHWIDDBByName_ValidNameButDbNotFound(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})

    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo.LoadHWIDDBByName('SBOARD')

  def testCommitHWIDDB_InvalidHWIDDBName(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})

    with self.assertRaises(ValueError):
      self._hwid_repo.CommitHWIDDB('no_such_board', 'unused_test_str',
                                   'unused_test_str', [], [], False)

  def testCommitHWIDDB_FailedToUploadCL(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})
    self._mocked_create_cl.side_effect = git_util.GitUtilException

    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo.CommitHWIDDB('SBOARD', 'unused_test_str',
                                   'unused_test_str', [], [], False)

  def testCommitHWIDDB_FailedToGetCLNumber(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})
    self._mocked_create_cl.return_value = 'Ithis_is_change_id', None
    self._mocked_get_cl_info.side_effect = git_util.GitUtilException

    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo.CommitHWIDDB('SBOARD', 'unused_test_str',
                                   'unused_test_str', [], [], False)

  def testCommitHWIDDB_FailedNoModificationException(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})
    self._mocked_create_cl.side_effect = (
        git_util.GitUtilNoModificationException)

    with self.assertRaises(git_util.GitUtilNoModificationException):
      self._hwid_repo.CommitHWIDDB('SBOARD', 'unused_test_str',
                                   'unused_test_str', [], [], False)

  def testCommitHWIDDB_Succeed(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})
    expected_cl_number = 123
    self._mocked_create_cl.return_value = ('Ithis_is_change_id',
                                           expected_cl_number)

    actual_cl_number = self._hwid_repo.CommitHWIDDB(
        'SBOARD', 'hwid_db_contents', 'unused_test_str', [], [], False, False,
        None, 'hwid_db_contents_internal')
    self.assertEqual(actual_cl_number, expected_cl_number)
    kwargs = self._mocked_create_cl.call_args[1]
    self.assertEqual(
        [('SBOARD', 0o100644, b'hwid_db_contents'),
         ('SBOARD.internal', 0o100644, b'hwid_db_contents_internal')],
        kwargs['new_files'])

  def testCommitHWIDDB_Succeed_RemoveChecksum(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})
    self._mocked_create_cl.return_value = ('unused_change_id', 123)

    self._hwid_repo.CommitHWIDDB(
        'SBOARD', 'hwid_db_contents\nchecksum: 12345\n', 'unused_test_str', [],
        [], False, False, None, 'hwid_db_contents_internal\nchecksum: 12345\n')
    kwargs = self._mocked_create_cl.call_args[1]
    self.assertEqual([
        ('SBOARD', 0o100644, b'hwid_db_contents\nchecksum:\n'),
        ('SBOARD.internal', 0o100644, b'hwid_db_contents_internal\nchecksum:\n')
    ], kwargs['new_files'])

  def testHWIDRepoHasCommitProperty(self):
    self.assertEqual(self._hwid_repo.hwid_db_commit_id,
                     self._fake_repo.head().decode('utf-8'))

  def _AddFilesToFakeRepo(self, contents_of_pathname: Dict[str, bytes]):
    updated_tree = self._fake_repo.add_files(
        [(p, 0o100644, c) for p, c in contents_of_pathname.items()])
    self._fake_repo.do_commit(message=b'add test files', tree=updated_tree.id)


class HWIDRepoManagerTest(HWIDRepoBaseTest):
  _RAW_METADATA = textwrap.dedent("""\
      PROJ1:
          board: BOARD
          branch: main
          version: 3
          path: v3/PROJ1
      """).encode()
  _METADATA = {
      'PROJ1':
          hwid_repo.HWIDDBMetadata(name='PROJ1', board_name='BOARD', version=3,
                                   path='v3/PROJ1')
  }

  def setUp(self):
    super().setUp()
    self._hwid_repo_manager = hwid_repo.HWIDRepoManager('unused_test_branch')

  def testGetHWIDDBCLInfo_Failed(self):
    self._mocked_get_cl_info.side_effect = git_util.GitUtilException
    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo_manager.GetHWIDDBCLInfo(123)

  def testGetHWIDDBMetadata_Succeed(self):
    self._mocked_get_commit_id.return_value = 'unused_commit_id'
    self._mocked_get_file_content.return_value = self._RAW_METADATA
    metadata = self._hwid_repo_manager.GetHWIDDBMetadata()
    self.assertEqual(metadata, self._METADATA)

  def testGetHWIDDBMetadataByProject_Succeed(self):
    self._mocked_get_commit_id.return_value = 'unused_commit_id'
    self._mocked_get_file_content.return_value = self._RAW_METADATA
    metadata = self._hwid_repo_manager.GetHWIDDBMetadataByProject('PROJ1')
    self.assertEqual(metadata, self._METADATA['PROJ1'])

  def testGetHWIDDBMetadataByProject_NotFound(self):
    self._mocked_get_commit_id.return_value = 'unused_commit_id'
    self._mocked_get_file_content.return_value = self._RAW_METADATA
    with self.assertRaises(KeyError):
      self._hwid_repo_manager.GetHWIDDBMetadataByProject('PROJ2')

  def testGetHWIDDBCLInfo_Succeed(self):
    cl_mergeable = False
    cl_created_time = datetime.datetime.utcnow()
    cl_patchset_comment_thread = git_util.CLCommentThread(
        path=None, context=None, comments=[
            git_util.CLComment('somebody@notgoogle.com', 'msg1'),
        ])
    cl_file_comment_thread = git_util.CLCommentThread(
        path='v3/THE_HWID_DB', context='v3/THE_HWID_DB:123:  text123',
        comments=[
            git_util.CLComment('somebody@notgoogle.com', 'msg2'),
        ])
    returned_cl_info = git_util.CLInfo(
        'unused_change_id', 123, 'subject', git_util.CLStatus.MERGED,
        git_util.CLReviewStatus.APPROVED, cl_mergeable, cl_created_time,
        [cl_patchset_comment_thread, cl_file_comment_thread], None, None, None,
        None)
    self._mocked_get_cl_info.return_value = returned_cl_info

    actual_cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(123)

    expected_cl_info = hwid_repo.HWIDDBCLInfo(
        'unused_change_id', 123, 'subject', git_util.CLStatus.MERGED,
        git_util.CLReviewStatus.APPROVED, cl_mergeable, cl_created_time,
        [cl_file_comment_thread], None, None, None, None)
    self.assertEqual(actual_cl_info, expected_cl_info)


  @mock.patch('cros.factory.hwid.service.appengine.git_util.PatchCL')
  @mock.patch('cros.factory.hwid.service.appengine.git_util.ReviewCL')
  def testRebaseCLMetadata(self, review_cl, patch_cl):
    self._mocked_rebase_cl.return_value = ['projects.yaml']
    self._mocked_get_commit_id.return_value = 'unused_commit_id'
    metadata = self._RAW_METADATA
    cl_metadata = textwrap.dedent("""\
        PROJ2:
            board: BOARD
            branch: main
            version: 3
            path: v3/PROJ2
        """).encode()
    expected_metadata = metadata + cl_metadata

    self._mocked_get_file_content.side_effect = [metadata, cl_metadata]

    cl_info = git_util.CLInfo('unused_change_id', 123, 'PROJ2: subject',
                              git_util.CLStatus.NEW, None, None,
                              datetime.datetime.utcnow(), None, None, None,
                              None, None)
    self._hwid_repo_manager.RebaseCLMetadata(cl_info)

    patch_cl.assert_called_with(mock.ANY, mock.ANY, mock.ANY, expected_metadata,
                                mock.ANY)
    review_cl.assert_called_once()

  def testRebaseCLMetadata_OtherFilesConflict(self):
    self._mocked_rebase_cl.return_value = ['projects.yaml', 'not_project.yaml']
    cl_info = git_util.CLInfo('unused_change_id', 123, 'PROJ: subject',
                              git_util.CLStatus.NEW, None, None,
                              datetime.datetime.utcnow(), None, None, None,
                              None, None)

    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo_manager.RebaseCLMetadata(cl_info)

  def testRebaseCLMetadata_NoProjectNameInCommitMessage(self):
    self._mocked_rebase_cl.return_value = ['projects.yaml']
    cl_info = git_util.CLInfo('unused_change_id', 123, 'NO_PROJECT_NAME',
                              git_util.CLStatus.NEW, None, None,
                              datetime.datetime.utcnow(), None, None, None,
                              None, None)

    with self.assertRaises(ValueError):
      self._hwid_repo_manager.RebaseCLMetadata(cl_info)


if __name__ == '__main__':
  unittest.main()
