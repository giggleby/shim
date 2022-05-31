#!/usr/bin/env python3
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for cros.factory.hwid.service.appengine.git_util"""

import datetime
import hashlib
import http.client
import os.path
import unittest
from unittest import mock

from dulwich.objects import Tree

from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import json_utils
from cros.factory.utils import type_utils


class RetryOnExceptionTest(unittest.TestCase):

  class _FakeException(Exception):
    pass

  def setUp(self):
    self.retried = 0

  @git_util.RetryOnException(
      retry_value=(_FakeException, ), delay_sec=0.5, num_retries=3)
  def _FakeFunction(self, succeed_on):
    if succeed_on == self.retried:
      return
    self.retried += 1
    raise self._FakeException()

  def testRetryOnException_RetryThreeTimesSucceed(self):
    self._FakeFunction(succeed_on=3)

  def testRetryOnException_RetryThreeTimesFailed(self):
    with self.assertRaises(self._FakeException):
      self._FakeFunction(succeed_on=4)


class MemoryRepoTest(unittest.TestCase):

  def testAddFiles(self):
    new_files = [
        ('a/b/c', 0o100644, b'content of a/b/c'),
        ('///a/b////d', 0o100644, b'content of a/b/d'),
        ('a/b/e/./././f', 0o100644, b'content of a/b/e/f'),
    ]
    repo = git_util.MemoryRepo('')
    tree = Tree()
    try:
      tree = repo.add_files(new_files, tree)
      tree.check()
    except Exception as ex:
      self.fail("testAddFiles raise Exception unexpectedly: %r" % ex)

    mode1, sha1 = tree.lookup_path(repo.get_object, b'a/b/c')
    self.assertEqual(mode1, 0o100644)
    self.assertEqual(repo[sha1].data, b'content of a/b/c')

    mode2, sha2 = tree.lookup_path(repo.get_object, b'a/b/d')
    self.assertEqual(mode2, 0o100644)
    self.assertEqual(repo[sha2].data, b'content of a/b/d')

    mode3, sha3 = tree.lookup_path(repo.get_object, b'a/b/e/f')
    self.assertEqual(mode3, 0o100644)
    self.assertEqual(repo[sha3].data, b'content of a/b/e/f')

  def testInvalidFileStructure1(self):
    new_files = [
        ('a/b/c', 0o100644, b'content of a/b/c'),
        ('a/b/c/d', 0o100644, b'content of a/b/c/d'),
    ]
    repo = git_util.MemoryRepo('')
    tree = Tree()
    with self.assertRaises(git_util.GitUtilException) as ex:
      repo.add_files(new_files, tree)
    self.assertEqual(str(ex.exception), "Invalid filepath 'a/b/c/d'.")

  def testInvalidFileStructure2(self):
    new_files = [
        ('a/b/c/d', 0o100644, b'content of a/b/c/d'),
        ('a/b/c', 0o100644, b'content of a/b/c'),
    ]
    repo = git_util.MemoryRepo('')
    tree = Tree()
    with self.assertRaises(git_util.GitUtilException) as ex:
      repo.add_files(new_files, tree)
    self.assertEqual(str(ex.exception), "Invalid filepath 'a/b/c'.")

  def testNoModification(self):
    file_name = 'README.md'
    repo = git_util.MemoryRepo(auth_cookie='')
    repo.shallow_clone(
        'https://chromium.googlesource.com/chromiumos/platform/factory',
        branch='stabilize-rust-13562.B')
    tree = repo[repo[b'HEAD'].tree]
    unused_size, object_id = tree[file_name.encode()]
    new_files = [(file_name, 0o100644, repo[object_id].data)]
    self.assertRaises(
        git_util.GitUtilNoModificationException, git_util.CreateCL,
        'https://chromium.googlesource.com/chromiumos/platform/factory', '',
        'stabilize-rust-13562.B', new_files, 'John Doe <no-reply@google.com>',
        'John Doe <no-reply@google.com>', '')

  def testListFiles(self):
    new_files = [
        ('a/b/c', 0o100644, b'content of a/b/c'),
        ('///a/b////d', 0o100644, b'content of a/b/d'),
        ('a/b/e/./././f', 0o100644, b'content of a/b/e/f'),
    ]
    repo = git_util.MemoryRepo('')
    tree = Tree()
    try:
      tree = repo.add_files(new_files, tree)
      tree.check()
    except Exception as ex:
      self.fail("testListFiles raise Exception unexpectedly: %r" % ex)
    repo.do_commit(b'Test_commit', tree=tree.id)

    self.assertEqual(
        sorted(repo.list_files('a/b')),
        [('c', git_util.NORMAL_FILE_MODE, b'content of a/b/c'),
         ('d', git_util.NORMAL_FILE_MODE, b'content of a/b/d'),
         ('e', git_util.DIR_MODE, None)])


class GetChangeIdTest(unittest.TestCase):

  @mock.patch('cros.factory.hwid.service.appengine.git_util.datetime')
  def testGetChangeId(self, datetime_mock):
    """Reference result of expected implementation."""

    datetime_mock.datetime.now.return_value = datetime.datetime.fromtimestamp(
        1556616237)
    tree_id = '4e7b52cf7c0b196914c924114c7225333f549bf1'
    parent = '3ef27b7a56e149a7cc64aaf1af837248daac514e'
    author = 'change-id test <change-id-test@google.com>'
    committer = 'change-id test <change-id-test@google.com>'
    commit_msg = 'Change Id test'
    expected_change_id = 'I3b5a06d980966aaa3d981ecb4d578f0cc1dd8179'
    # pylint: disable=protected-access
    change_id = git_util._GetChangeId(tree_id, parent, author, committer,
                                      commit_msg)
    # pylint: enable=protected-access
    self.assertEqual(change_id, expected_change_id)


class GetCommitIdTest(unittest.TestCase):

  def testGetCommitId(self):
    git_url_prefix = 'https://chromium-review.googlesource.com'
    project = 'chromiumos/platform/factory'
    branch = None

    auth_cookie = ''  # auth_cookie is not needed in chromium repo
    commit = git_util.GetCommitId(git_url_prefix, project, branch, auth_cookie)
    self.assertRegex(commit, '^[0-9a-f]{40}$')

  @mock.patch('urllib3.PoolManager')
  def testGetCommitIdFormatError(self, mocked_poolmanager):
    """Mock response and status to test if exceptions are raised."""
    git_url_prefix = 'dummy'
    project = 'dummy'
    branch = 'dummy'
    auth_cookie = 'dummy'

    instance = mocked_poolmanager.return_value  # pool_manager instance
    error_responses = [
        # 400 error
        mock.MagicMock(status=http.client.BAD_REQUEST, data=''),
        # invalid json
        mock.MagicMock(
            status=http.client.OK,
            data=(")]}'\n"
                  '\n'
                  '  "revision": "0123456789abcdef0123456789abcdef01234567"\n'
                  '}\n')),
        # no magic line
        mock.MagicMock(
            status=http.client.OK,
            data=('{\n'
                  '  "revision": "0123456789abcdef0123456789abcdef01234567"\n'
                  '}\n')),
        # no "revision" field
        mock.MagicMock(
            status=http.client.OK, data=(
                ")]}'\n"
                '{\n'
                '  "no_revision": "0123456789abcdef0123456789abcdef01234567"\n'
                '}\n')),
    ]

    for resp in error_responses:
      instance.urlopen.return_value = resp
      self.assertRaises(git_util.GitUtilException, git_util.GetCommitId,
                        git_url_prefix, project, branch, auth_cookie)


class GetCLInfoTest(unittest.TestCase):
  _THE_CREATED_TIMESTAMP = datetime.datetime(2022, 2, 10, 18, 6, 6, 0)
  _THE_CHANGE_ID = 'the_change_id_value'
  _THE_CL_NUMBER = 123
  _THE_CL_STATUS = 'NEW'
  _THE_CL_SUBJECT = 'SUBJECT'

  def setUp(self):
    super().setUp()
    patcher = mock.patch('urllib3.PoolManager')
    self._mocked_pool_manager_cls = patcher.start()
    self.addCleanup(patcher.stop)

  def _BuildGerritSuccResponse(self, json_obj):
    data = b")]}'\n" + json_utils.DumpStr(json_obj, pretty=True).encode('utf-8')
    return type_utils.Obj(status=http.client.OK, data=data)

  def _BuildGetChangeSuccResponseWithDefaults(
      self, change_id=None, cl_number=None, created_timestamp=None, status=None,
      subject=None, **other_fields):
    created_timestamp = created_timestamp or self._THE_CREATED_TIMESTAMP
    json_obj = {
        'change_id': change_id or self._THE_CHANGE_ID,
        '_number': cl_number or self._THE_CL_NUMBER,
        'created': created_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f000'),
        'status': status or self._THE_CL_STATUS,
        'subject': subject or self._THE_CL_SUBJECT,
    }
    json_obj.update(other_fields)
    return self._BuildGerritSuccResponse(json_obj)

  def testGetCLInfo_BasicInfo(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.return_value = self._BuildGetChangeSuccResponseWithDefaults()

    actual_cl_info = git_util.GetCLInfo('unused_review_host',
                                        self._THE_CHANGE_ID)

    self.assertEqual(actual_cl_info.change_id, self._THE_CHANGE_ID)
    self.assertEqual(actual_cl_info.cl_number, self._THE_CL_NUMBER)
    self.assertEqual(actual_cl_info.created_time, self._THE_CREATED_TIMESTAMP)
    self.assertEqual(actual_cl_info.subject, self._THE_CL_SUBJECT)

  def testGetCLInfo_WithStatus(self):
    pm_inst = self._mocked_pool_manager_cls.return_value
    pm_inst.urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(status='MERGED'),
        self._BuildGetChangeSuccResponseWithDefaults(status='NEW'),
        self._BuildGetChangeSuccResponseWithDefaults(status='ABANDONED'),
    ]

    host = 'unused_review_host'
    merged_cl_info = git_util.GetCLInfo(host, self._THE_CHANGE_ID)
    new_cl_info = git_util.GetCLInfo(host, self._THE_CHANGE_ID)
    abandoned_cl_info = git_util.GetCLInfo(host, self._THE_CHANGE_ID)

    self.assertEqual(merged_cl_info.status, git_util.CLStatus.MERGED)
    self.assertEqual(new_cl_info.status, git_util.CLStatus.NEW)
    self.assertEqual(abandoned_cl_info.status, git_util.CLStatus.ABANDONED)

  def testGetCLInfo_WithMergeableInfo(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(status='NEW'),
        self._BuildGerritSuccResponse({'mergeable': True}),
    ]

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_mergeable=True)

    self.assertTrue(actual_cl_info.mergeable)

  def testGetCLInfo_WithMergeableInfoForAbandonedCL(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(status='ABANDONED'),
    ]

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_mergeable=True)

    self.assertFalse(actual_cl_info.mergeable)

  def testGetCLInfo_WithApprovedReviewStatus(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.return_value = self._BuildGetChangeSuccResponseWithDefaults(
        labels={
            'Code-Review': {
                'approved': {
                    '_account_id': 12345
                },
            },
        })

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)

    self.assertEqual(actual_cl_info.review_status,
                     git_util.CLReviewStatus.APPROVED)

  def testGetCLInfo_WithAmbiguousReviewStatus(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(
            labels={
                'Code-Review': {
                    'approved': {
                        '_account_id': 12345
                    },
                    'disliked': {
                        '_account_id': 12345
                    },
                },
            }),
        self._BuildGetChangeSuccResponseWithDefaults(
            labels={
                'Code-Review': {
                    'approved': {
                        '_account_id': 12345
                    },
                    'rejected': {
                        '_account_id': 12345
                    },
                },
            }),
        self._BuildGetChangeSuccResponseWithDefaults(
            labels={
                'Code-Review': {
                    'recommended': {
                        '_account_id': 12345
                    },
                    'disliked': {
                        '_account_id': 12345
                    },
                },
            }),
    ]

    actual_cl_info1 = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)
    actual_cl_info2 = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)
    actual_cl_info3 = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)

    self.assertEqual(actual_cl_info1.review_status,
                     git_util.CLReviewStatus.AMBIGUOUS)
    self.assertEqual(actual_cl_info2.review_status,
                     git_util.CLReviewStatus.AMBIGUOUS)
    self.assertEqual(actual_cl_info3.review_status,
                     git_util.CLReviewStatus.AMBIGUOUS)

  def testGetCLInfo_WithDislikedReviewStatus(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.return_value = self._BuildGetChangeSuccResponseWithDefaults(
        labels={
            'Code-Review': {
                'disliked': {
                    '_account_id': 12345
                },
            },
        })

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)

    self.assertEqual(actual_cl_info.review_status,
                     git_util.CLReviewStatus.DISLIKED)

  def testGetCLInfo_WithRejectedReviewStatus(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(
            labels={
                'Code-Review': {
                    'disliked': {
                        '_account_id': 12345
                    },
                    'rejected': {
                        '_account_id': 12345
                    },
                },
            }),
        self._BuildGetChangeSuccResponseWithDefaults(labels={
            'Code-Review': {
                'rejected': {
                    '_account_id': 12345
                },
            },
        }),
    ]

    actual_cl_info1 = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)
    actual_cl_info2 = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)

    self.assertEqual(actual_cl_info2.review_status,
                     git_util.CLReviewStatus.REJECTED)
    self.assertEqual(actual_cl_info1.review_status,
                     git_util.CLReviewStatus.REJECTED)

  def testGetCLInfo_WithNoReviewStatus(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.return_value = self._BuildGetChangeSuccResponseWithDefaults(
        labels={
            'Code-Review': {},
        })

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_review_status=True)

    self.assertEqual(actual_cl_info.review_status,
                     git_util.CLReviewStatus.NEUTRAL)

  def testGetCLInfo_WithPatchsetLevelComment(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(),
        self._BuildGerritSuccResponse({
            '/PATCHSET_LEVEL': [{
                'id': 'comment_id_1',
                'message': 'This is comment 1.',
                'author': {
                    'email': 'somebody@not_google.com',
                }
            }, ],
        }),
    ]
    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_comment_thread=True)

    self.assertEqual(actual_cl_info.comment_threads, [
        git_util.CLCommentThread(
            path=None, context=None, comments=[
                git_util.CLComment('somebody@not_google.com',
                                   'This is comment 1.'),
            ])
    ])

  def testGetCLInfo_WithFileComment(self):
    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(),
        self._BuildGerritSuccResponse({
            'file1': [{
                'id':
                    'comment_id_1',
                'message':
                    'This is comment 1.',
                'author': {
                    'email': 'somebody@not_google.com',
                },
                'context_lines': [
                    {
                        'line_number': 123,
                        'context_line': 'The source code line 123.',
                    },
                    {
                        'line_number': 124,
                        'context_line': 'The source code line 124.',
                    },
                ],
            }],
        }),
    ]

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_comment_thread=True)

    expected_context = ('file1:123:The source code line 123.\n'
                        'file1:124:The source code line 124.')
    self.assertEqual(actual_cl_info.comment_threads, [
        git_util.CLCommentThread(
            path='file1', context=expected_context, comments=[
                git_util.CLComment('somebody@not_google.com',
                                   'This is comment 1.'),
            ])
    ])

  def testGetCLInfo_WithCommentThreads(self):

    def _CreateCommentInfoJSONFromTemplate(numeric_id, in_reply_to=None):
      json_obj = {
          'id': f'id{numeric_id}',
          'message': f'Message {numeric_id}.',
          'author': {
              'email': f'author{numeric_id}@not_google.com',
          },
      }
      if in_reply_to is not None:
        json_obj['in_reply_to'] = f'id{in_reply_to}'
      return json_obj

    mock_urlopen = self._mocked_pool_manager_cls.return_value.urlopen
    mock_urlopen.side_effect = [
        self._BuildGetChangeSuccResponseWithDefaults(),
        self._BuildGerritSuccResponse({
            '/PATCHSET_LEVEL': [
                _CreateCommentInfoJSONFromTemplate(1),
                _CreateCommentInfoJSONFromTemplate(2, in_reply_to=1),
                _CreateCommentInfoJSONFromTemplate(3, in_reply_to=1),
                _CreateCommentInfoJSONFromTemplate(4, in_reply_to=2),
                _CreateCommentInfoJSONFromTemplate(5),
            ],
        }),
    ]

    actual_cl_info = git_util.GetCLInfo(
        'unused_review_host', self._THE_CHANGE_ID, include_comment_thread=True)

    self.assertCountEqual(actual_cl_info.comment_threads, [
        git_util.CLCommentThread(
            path=None, context=None, comments=[
                git_util.CLComment('author1@not_google.com', 'Message 1.'),
                git_util.CLComment('author2@not_google.com', 'Message 2.'),
                git_util.CLComment('author3@not_google.com', 'Message 3.'),
                git_util.CLComment('author4@not_google.com', 'Message 4.'),
            ]),
        git_util.CLCommentThread(
            path=None, context=None, comments=[
                git_util.CLComment('author5@not_google.com', 'Message 5.'),
            ]),
    ])


class CreateCLTest(unittest.TestCase):

  @mock.patch('cros.factory.hwid.service.appengine.git_util.porcelain')
  def testCreateCLOptions(self, mock_porcelain):
    file_name = 'README.md'
    url = 'https://chromium.googlesource.com/chromiumos/platform/factory'
    auth_cookie = ''
    branch = 'stabilize-rust-13562.B'
    author = 'Author <author@email.com>'
    committer = 'Committer <committer@email.com>'
    reviewers = ['reviewer@email.com']
    ccs = ['cc@email.com']
    commit_msg = 'commit msg'
    repo = git_util.MemoryRepo(auth_cookie='')
    repo.shallow_clone(url, branch=branch)
    new_files = [(file_name, 0o100644, b'')]
    git_util.CreateCL(url, auth_cookie, branch, new_files, author, committer,
                      commit_msg, reviewers, ccs, True)
    mock_porcelain.push.assert_called_once_with(
        mock.ANY, url,
        (f'HEAD:refs/for/refs/heads/{branch}%'
         'r=reviewer@email.com,cc=cc@email.com,l=Bot-Commit+1,l=Commit-Queue+2'
        ).encode('UTF-8'), errstream=mock.ANY, pool_manager=mock.ANY)


class GitFilesystemAdapterTest(unittest.TestCase):

  def setUp(self):
    self.repo = git_util.MemoryRepo(auth_cookie='')
    self.repo.shallow_clone(
        'https://chromium.googlesource.com/chromiumos/platform/factory',
        branch='stabilize-13360.B')  # use a stabilize branch as a repo snapshot
    self.git_fs = git_util.GitFilesystemAdapter(self.repo)
    self.target_dir = 'deploy'
    self.file_name = 'README.md'
    self.file_path = os.path.join(self.target_dir, self.file_name)

  def testListFiles(self):
    self.assertIn(self.file_name, self.git_fs.ListFiles(self.target_dir))

  def testReadFile(self):
    # Validate the consistency between content hash and object hash in git.
    content = self.git_fs.ReadFile(self.file_path)
    head_commit = self.repo[b'HEAD']
    unused_mode, sha = self.repo[head_commit.tree].lookup_path(
        self.repo.get_object, self.file_path.encode())
    self.assertEqual(
        sha.decode(),
        hashlib.sha1((b'blob %d\x00%b' % (len(content), content))).hexdigest())

  def testReadOnly(self):
    # Test if GitFilesystemAdapter is unsupported for WriteFile and DeleteFile.
    self.assertRaises(filesystem_adapter.FileSystemAdapterException,
                      self.git_fs.WriteFile, self.file_path, b'')
    self.assertRaises(filesystem_adapter.FileSystemAdapterException,
                      self.git_fs.DeleteFile, self.file_path)


class ApprovalCaseTest(unittest.TestCase):

  def testConvertToVotes(self):
    self.assertCountEqual([
        git_util.ReviewVote('Bot-Commit', 1),
        git_util.ReviewVote('Code-Review', 0),
        git_util.ReviewVote('Commit-Queue', 2),
    ], git_util.ApprovalCase.APPROVED.ConvertToVotes())

    self.assertCountEqual([
        git_util.ReviewVote('Bot-Commit', 0),
        git_util.ReviewVote('Code-Review', -2),
        git_util.ReviewVote('Commit-Queue', 0),
    ], git_util.ApprovalCase.REJECTED.ConvertToVotes())

    self.assertCountEqual([
        git_util.ReviewVote('Bot-Commit', 0),
        git_util.ReviewVote('Code-Review', 0),
        git_util.ReviewVote('Commit-Queue', 0),
    ], git_util.ApprovalCase.NEED_MANUAL_REVIEW.ConvertToVotes())


if __name__ == '__main__':
  unittest.main()
