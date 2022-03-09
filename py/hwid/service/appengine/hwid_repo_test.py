#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import os
from typing import Dict
import unittest
from unittest import mock

from dulwich import objects as dulwich_objects  # pylint: disable=wrong-import-order, import-error

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
    })

    actual_hwid_db = self._hwid_repo.LoadHWIDDBByName('SBOARD')
    self.assertCountEqual(actual_hwid_db, 'sboard data')

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

  def testCommitHWIDDB_Succeed(self):
    self._AddFilesToFakeRepo({'projects.yaml': _SERVER_BOARDS_DATA})
    expected_cl_number = 123
    self._mocked_create_cl.return_value = ('Ithis_is_change_id',
                                           expected_cl_number)

    actual_cl_number = self._hwid_repo.CommitHWIDDB(
        'SBOARD', 'unused_test_str', 'unused_test_str', [], [], False)
    self.assertEqual(actual_cl_number, expected_cl_number)

  def _AddFilesToFakeRepo(self, contents_of_pathname: Dict[str, bytes]):
    updated_tree = self._fake_repo.add_files(
        [(p, 0o100644, c) for p, c in contents_of_pathname.items()])
    self._fake_repo.do_commit(message=b'add test files', tree=updated_tree.id)


class HWIDRepoManagerTest(HWIDRepoBaseTest):

  def setUp(self):
    super().setUp()
    self._hwid_repo_manager = hwid_repo.HWIDRepoManager('unused_test_branch')

  def testGetHWIDDBCLInfo_Failed(self):
    self._mocked_get_cl_info.side_effect = git_util.GitUtilException
    with self.assertRaises(hwid_repo.HWIDRepoError):
      self._hwid_repo_manager.GetHWIDDBCLInfo(123)

  def testGetHWIDDBCLInfo_Succeed(self):
    cl_mergeable = False
    cl_created_time = datetime.datetime.utcnow()
    returned_cl_info = git_util.CLInfo('unused_change_id', 123,
                                       git_util.CLStatus.MERGED,
                                       git_util.CLReviewStatus.APPROVED, [
                                           git_util.CLMessage('msg1', 'email1'),
                                           git_util.CLMessage('msg2', 'email2')
                                       ], cl_mergeable, cl_created_time)
    self._mocked_get_cl_info.return_value = returned_cl_info

    actual_cl_info = self._hwid_repo_manager.GetHWIDDBCLInfo(123)
    self.assertEqual(actual_cl_info, returned_cl_info)


if __name__ == '__main__':
  unittest.main()
