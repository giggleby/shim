# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import contextlib
import datetime
import enum
import functools
import hashlib
import http.client
import io
import logging
import os
import re
import time
from typing import Any, NamedTuple, Optional, Sequence, Tuple, Type
import urllib.parse

# pylint: disable=import-error, no-name-in-module
import certifi
from dulwich.client import HttpGitClient
from dulwich.objects import Blob
from dulwich.objects import Tree
from dulwich import porcelain
from dulwich import refs
from dulwich.repo import MemoryRepo as _MemoryRepo
import google.auth
from google.auth import impersonated_credentials
import google.auth.transport.requests


# pylint: enable=import-error, no-name-in-module
# isort: split

import urllib3
import urllib3.exceptions

from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import json_utils


HEAD = b'HEAD'
DEFAULT_REMOTE_NAME = b'origin'
REF_HEADS_PREFIX = b'refs/heads/'
REF_REMOTES_PREFIX = b'refs/remotes/'
NORMAL_FILE_MODE = 0o100644
EXEC_FILE_MODE = 0o100755
DIR_MODE = 0o040000
GERRIT_SCOPE = 'https://www.googleapis.com/auth/gerritcodereview'
IMPERSONATED_SERVICE_ACCOUNT = os.getenv('IMPERSONATED_SERVICE_ACCOUNT')


def RetryOnException(retry_value: Tuple[Type[Exception], ...] = (Exception, ),
                     delay_sec: int = 1, num_retries: int = 5):
  """Retries when fail to request to Gerrit server.

  Args:
    retry_value: Tuple of The expected exceptions to trigger retries.
    delay_sec: Delay seconds between retries.
    num_retries: Max number of retries.

  Returns:
    A wrapper function which can be used as a decorator.
  """

  def RetryDecorator(func):

    @functools.wraps(func)
    def RetryFunction(*args, **kwargs):
      for retried in range(1, num_retries + 1):
        try:
          return func(*args, **kwargs)
        except retry_value as ex:
          logging.info('%s failed: %s. Retry: %d', func.__name__, ex, retried)
          time.sleep(delay_sec)
      return func(*args, **kwargs)

    return RetryFunction

  return RetryDecorator


def _B(s):
  """Converts str to bytes if needed."""
  return s if isinstance(s, bytes) else s.encode()


class GitUtilException(Exception):
  pass


def _CreatePoolManager(cookie: str = '', content_type: str = '',
                       keep_alive: bool = False) -> urllib3.PoolManager:
  """Helps creating a pool manager instance.

  Args:
    cookie: If not empty, it sets the header field "Cookie" to the value.
    content_type: If not empty, it sets the header field "Content-Type" to the
      value.
    keep_alive: If `True`, it sets the header field "Connection" to
      "keep-alive"; Otherwise it sets the field to "close".

  Returns:
    A pool manager instance with proper configured header fields.
  """
  pool_manager = urllib3.PoolManager(ca_certs=certifi.where())
  for header_field, header_value in (
      ('Cookie', cookie),
      ('Content-Type', content_type),
      ('Connection', 'keep-alive' if keep_alive else 'close'),
  ):
    if header_value:
      pool_manager.headers[header_field] = header_value
  return pool_manager


def _InvokeGerritAPI(method: str, url: str,
                     params: Optional[Sequence[Tuple[str, str]]] = None,
                     auth_cookie: str = '', content_type: str = '',
                     body: bytes = b'') -> bytes:
  """Invokes a Gerrit API endpoint and returns the response in bytes.

  Args:
    method: The HTTP method like "GET" or "POST".
    url: The URL of the API without HTTP parameters.
    params: A list of HTTP parameters.
    auth_cookie: The auth cookie uses to create the pool manager.
    content_type: The Content-type field in the request header.
    body: The HTTP request body in bytes.

  Returns:
    The response in bytes.

  Raises:
    GitUtilException: If the invocation ends unsuccessfully.
  """
  if params:
    url = f'{url}?{urllib.parse.urlencode(params)}'

  pool_manager = _CreatePoolManager(cookie=auth_cookie,
                                    content_type=content_type)

  try:
    resp = pool_manager.urlopen(method, url, body=body)
  except urllib3.exceptions.HTTPError as ex:
    raise GitUtilException(f'Invalid url {url!r}.') from ex
  if resp.status != http.client.OK:
    raise GitUtilException(
        f'Request {url!r} unsuccessfully with code {resp.status!r}.')

  return resp.data


def _InvokeGerritAPIJSON(
    method: str, url: str, params: Optional[Sequence[Tuple[str, str]]] = None,
    auth_cookie: str = '', json_body: Optional[Any] = None):
  """Invokes a Gerrit API endpoint and returns the response payload in JSON.

  Args:
    method: See `_InvokeGerritAPI`.
    url: See `_InvokeGerritAPI`.
    params: See `_InvokeGerritAPI`.
    auth_cookie: See `_InvokeGerritAPI`.
    json_body: The JSON-seralizable object to be attached in the HTTP body.

  Returns:
    The JSON-compatible response payload.

  Raises:
    GitUtilException: If the invocation ends unsuccessfully.
  """
  kwargs = {
      'params': params,
      'auth_cookie': auth_cookie
  }
  if json_body is not None:
    kwargs['content_type'] = 'application/json'
    kwargs['body'] = json_utils.DumpStr(json_body).encode('utf-8')

  raw_data = _InvokeGerritAPI(method, url, **kwargs)
  try:
    # the response starts with a magic prefix line for preventing XSSI which
    # should be stripped.
    stripped_json_bytes = raw_data.split(b'\n', 1)[1]
    return json_utils.LoadStr(stripped_json_bytes)
  except Exception as ex:
    raise GitUtilException(f'Response format error: {raw_data!r}.') from ex


class GitUtilNoModificationException(GitUtilException):
  """Raised if no modification is made for commit."""


class GitFilesystemAdapter(filesystem_adapter.FileSystemAdapter):

  def __init__(self, memory_repo):
    self._memory_repo = memory_repo

  class ExceptionMapper(contextlib.AbstractContextManager):

    def __exit__(self, value_type, value, traceback):
      if isinstance(value, GitUtilException):
        raise KeyError(value)
      if isinstance(value, Exception):
        raise filesystem_adapter.FileSystemAdapterException(str(value))

  EXCEPTION_MAPPER = ExceptionMapper()

  @classmethod
  def GetExceptionMapper(cls):
    return cls.EXCEPTION_MAPPER

  def _ReadFile(self, path):
    head_commit = self._memory_repo[HEAD]
    root = self._memory_repo[head_commit.tree]
    mode, sha = root.lookup_path(self._memory_repo.get_object, _B(path))
    if mode != NORMAL_FILE_MODE:
      raise GitUtilException(f'Path {path!r} is not a file.')
    return self._memory_repo[sha].data

  def _WriteFile(self, path, content):
    raise NotImplementedError('GitFilesystemAdapter is read-only.')

  def _DeleteFile(self, path):
    raise NotImplementedError('GitFilesystemAdapter is read-only.')

  def _ListFiles(self, prefix=None):
    if prefix is None:
      prefix = ''

    ret = []
    for name, mode, unused_data in self._memory_repo.list_files(prefix):
      if mode == NORMAL_FILE_MODE:
        ret.append(name)
    return ret


class MemoryRepo(_MemoryRepo):
  """Enhance MemoryRepo with push ability."""

  def __init__(self, auth_cookie, *args, **kwargs):
    """Initializes with auth_cookie."""
    _MemoryRepo.__init__(self, *args, **kwargs)
    self.auth_cookie = auth_cookie

  def shallow_clone(self, remote_location, branch):
    """Shallow clones objects of a branch from a remote server.

    Args:
      remote_location: String identifying a remote server
      branch: Branch
    """

    parsed = urllib.parse.urlparse(remote_location)

    pool_manager = _CreatePoolManager(cookie=self.auth_cookie)

    client = HttpGitClient.from_parsedurl(
        parsed, config=self.get_config_stack(), pool_manager=pool_manager)
    fetch_result = client.fetch(
        parsed.path, self, determine_wants=lambda mapping:
        [mapping[REF_HEADS_PREFIX + _B(branch)]], depth=1)
    stripped_refs = refs.strip_peeled_refs(fetch_result.refs)
    branches = {
        n[len(REF_HEADS_PREFIX):]: v
        for (n, v) in stripped_refs.items()
        if n.startswith(REF_HEADS_PREFIX)
    }
    self.refs.import_refs(REF_REMOTES_PREFIX + DEFAULT_REMOTE_NAME, branches)
    self[HEAD] = self[REF_REMOTES_PREFIX + DEFAULT_REMOTE_NAME + b'/' +
                      _B(branch)]

  def recursively_add_file(self, cur, path_splits, file_name, mode, blob):
    """Adds files in object store.

    Since we need to collect all tree objects with modified children, a
    recursively approach is applied

    Args:
      cur: Current tree obj
      path_splits: Directories between cur and file
      file_name: File name
      mode: File mode in git
      blob: Blob obj of the file
    """

    if path_splits:
      child_name = path_splits[0]
      if child_name in cur:
        unused_mode, sha = cur[child_name]
        sub = self[sha]
        if not isinstance(sub, Tree):  # if child_name exists but not a dir
          raise GitUtilException
      else:
        # not exists, create a new tree
        sub = Tree()
      self.recursively_add_file(sub, path_splits[1:], file_name, mode, blob)
      cur.add(child_name, DIR_MODE, sub.id)
    else:
      # reach the directory of the target file
      if file_name in cur:
        unused_mod, sha = cur[file_name]
        existed_obj = self[sha]
        if not isinstance(existed_obj, Blob):
          # if file_name exists but not a Blob(file)
          raise GitUtilException
      self.object_store.add_object(blob)
      cur.add(file_name, mode, blob.id)

    self.object_store.add_object(cur)

  def add_files(self, new_files, tree=None):
    """Adds files to repository.

    Args:
      new_files: List of (file path, mode, file content)
      tree: Optional tree obj
    Returns:
      updated tree
    """

    if tree is None:
      head_commit = self[HEAD]
      tree = self[head_commit.tree]
    for (file_path, mode, content) in new_files:
      path, filename = os.path.split(file_path)
      # os.path.normpath('') returns '.' which is unexpected
      paths = [
          _B(x) for x in os.path.normpath(path).split(os.sep) if x and x != '.'
      ]
      try:
        self.recursively_add_file(tree, paths, _B(filename), mode,
                                  Blob.from_string(_B(content)))
      except GitUtilException as ex:
        raise GitUtilException(f'Invalid filepath {file_path!r}.') from ex

    return tree

  def list_files(self, path):
    """Lists files under specific path.

    Args:
      path: the path of dir
    Returns:
      A generator that generates (name, mode, content) of files under the
      path.  if the entry is a directory, content will be None instead.
    """

    head_commit = self[HEAD]
    root = self[head_commit.tree]
    try:
      mode, sha = root.lookup_path(self.get_object, _B(path))
    except KeyError as ex:
      raise GitUtilException(f'Path {path!r} not found.') from ex
    if mode not in (None, DIR_MODE):  # None for root directory
      raise GitUtilException(f'Path {path!r} is not a directory.')
    tree = self[sha]
    for name, mode, file_sha in tree.items():
      obj = self[file_sha]
      yield (name.decode(), mode,
             obj.data if obj.type_name == b'blob' else None)


def _GetChangeId(tree_id, parent_commit, author, committer, commit_msg):
  """Gets change id from information of commit.

  Implemented by referencing common .git/hooks/commit-msg script with some
  modification, this function is used to generate hash as a Change-Id based on
  the execution time and the information of the commit.  Since the commit-msg
  script may change, this function does not guarantee the consistency of the
  Change-Id with the commit-msg script in the future.

  Args:
    tree_id: Tree hash
    parent_commit: Parent commit
    author: Author in form of "Name <email@domain>"
    committer: Committer in form of "Name <email@domain>"
    commit_msg: Commit message
  Returns:
    hash of information as change id
  """

  now = int(time.mktime(datetime.datetime.now().timetuple()))
  change_msg = (f'tree {tree_id}\n'
                f'parent {parent_commit}\n'
                f'author {author} {now}\n'
                f'committer {committer} {now}\n'
                '\n'
                f'{commit_msg}')
  change_id_input = f'commit {len(change_msg)}\x00{change_msg}'.encode('utf-8')
  return f'I{hashlib.sha1(change_id_input).hexdigest()}'


def CreateCL(git_url, auth_cookie, branch, new_files, author, committer,
             commit_msg, reviewers=None, cc=None, auto_approved=False,
             repo=None):
  """Creates a CL from adding files in specified location.

  Args:
    git_url: HTTPS repo url
    auth_cookie: Auth_cookie
    branch: Branch needs adding file
    new_files: List of (filepath, mode, bytes)
    author: Author in form of "Name <email@domain>"
    committer: Committer in form of "Name <email@domain>"
    commit_msg: Commit message
    reviewers: List of emails of reviewers
    cc: List of emails of cc's
    auto_approved: A bool indicating if this CL should be auto-approved.
    repo: The `MemoryRepo` instance to create the commit.  If not specified,
        this function clones the repository from `git_url:branch`.
  Returns:
    A tuple of (change id, cl number).
    cl number will be None if fail to parse git-push output.
  """
  if repo is None:
    repo = MemoryRepo(auth_cookie=auth_cookie)
    # only fetches last commit
    repo.shallow_clone(git_url, branch=_B(branch))
  head_commit = repo[HEAD]
  original_tree_id = head_commit.tree
  updated_tree = repo.add_files(new_files)
  if updated_tree.id == original_tree_id:
    raise GitUtilNoModificationException

  change_id = _GetChangeId(updated_tree.id, repo.head(), author, committer,
                           commit_msg)
  repo.do_commit(
      _B(commit_msg + f'\n\nChange-Id: {change_id}'), author=_B(author),
      committer=_B(committer), tree=updated_tree.id)

  options = []
  if reviewers:
    options += ['r=' + email for email in reviewers]
  if cc:
    options += ['cc=' + email for email in cc]
  if auto_approved:
    options += ['l=Bot-Commit+1', 'l=Commit-Queue+2']
  target_branch = 'refs/for/refs/heads/' + branch
  if options:
    target_branch += '%' + ','.join(options)

  stderr = io.BytesIO()
  porcelain.push(repo, git_url, HEAD + b':' + _B(target_branch),
                 errstream=stderr,
                 pool_manager=_CreatePoolManager(cookie=repo.auth_cookie))

  def _ParseCLNumber(message):
    pattern = re.sub(r'googlesource\.com/', 'googlesource.com/c/', git_url)
    pattern = re.escape(pattern) + r'/\+/(\d+)'
    matches = re.findall(pattern, message)
    return int(matches[0]) if matches else None

  return change_id, _ParseCLNumber(stderr.getvalue().decode())


@RetryOnException(retry_value=(GitUtilException, ))
def GetCurrentBranch(git_url_prefix, project, auth_cookie=''):
  """Gets the branch HEAD tracks.

  Uses the gerrit API to get the branch name HEAD tracks.

  Args:
    git_url_prefix: HTTPS repo url
    project: Project name
    auth_cookie: Auth cookie

  Raises:
    GitUtilException if error occurs while querying the Gerrit API.
  """
  quoted_project = urllib.parse.quote(project, safe='')
  git_url = f'{git_url_prefix}/projects/{quoted_project}/HEAD'
  branch_name = _InvokeGerritAPIJSON('GET', git_url, auth_cookie=auth_cookie)
  if branch_name.startswith(REF_HEADS_PREFIX.decode()):
    branch_name = branch_name[len(REF_HEADS_PREFIX.decode()):]
  return branch_name


@RetryOnException(retry_value=(GitUtilException, ))
def GetCommitId(git_url_prefix, project, branch=None, auth_cookie=''):
  """Gets branch commit.

  Uses the gerrit API to get the commit id.

  Args:
    git_url_prefix: HTTPS repo url
    project: Project name
    branch: Branch name, use the branch HEAD tracks if set to None.
    auth_cookie: Auth cookie

  Raises:
    GitUtilException if error occurs while querying the Gerrit API.
  """
  branch = branch or GetCurrentBranch(git_url_prefix, project, auth_cookie)

  quoted_proj = urllib.parse.quote(project, safe='')
  quoted_branch = urllib.parse.quote(branch, safe='')
  git_url = f'{git_url_prefix}/projects/{quoted_proj}/branches/{quoted_branch}'
  branch_info = _InvokeGerritAPIJSON('GET', git_url, auth_cookie=auth_cookie)
  try:
    return branch_info['revision']
  except KeyError as ex:
    raise GitUtilException(
        f'Commit ID not found in the branch info: {branch_info}.') from ex


@RetryOnException(retry_value=(GitUtilException, ))
def GetFileContent(git_url_prefix: str, project: str, path: str,
                   branch: Optional[str] = None,
                   auth_cookie: Optional[str] = None) -> bytes:
  """Gets file content on Gerrit.

  Uses the gerrit API to get the file content.

  Args:
    git_url_prefix: HTTPS repo url.
    project: Project name.
    path: Path to the file.
    branch: Branch name, use the branch HEAD tracks if set to None.
    auth_cookie: Auth cookie.
  """
  branch = branch or GetCurrentBranch(git_url_prefix, project, auth_cookie)
  project, branch, path = map(lambda s: urllib.parse.quote(s, safe=''),
                              (project, branch, path))
  git_url = (f'{git_url_prefix}/projects/{project}/branches/{branch}/files/'
             f'{path}/content')
  raw_data = _InvokeGerritAPI('GET', git_url, auth_cookie=auth_cookie)
  try:
    return base64.b64decode(raw_data)
  except Exception as ex:
    raise GitUtilException(f'Response format error: {raw_data!r}.') from ex


class CLStatus(enum.Enum):
  NEW = enum.auto()
  MERGED = enum.auto()
  ABANDONED = enum.auto()


class CLReviewStatus(enum.Enum):
  AMBIGUOUS = enum.auto()
  NEUTRAL = enum.auto()
  APPROVED = enum.auto()
  RECOMMENDED = enum.auto()
  DISLIKED = enum.auto()
  REJECTED = enum.auto()


_GERRIT_CL_STATUS_TO_CL_STATUS = {
    'NEW': CLStatus.NEW,
    'MERGED': CLStatus.MERGED,
    'ABANDONED': CLStatus.ABANDONED,
}


class CLMessage(NamedTuple):
  message: str
  author_email: Optional[str]


class CLInfo(NamedTuple):
  change_id: str
  cl_number: int
  status: CLStatus
  review_status: Optional[CLReviewStatus]
  messages: Optional[Sequence[CLMessage]]
  mergeable: Optional[bool]
  created_time: datetime.datetime


def GetCLInfo(review_host, change_id, auth_cookie='', include_messages=False,
              include_detailed_accounts=False, include_mergeable=False,
              include_review_status=False):
  """Gets the info of the specified CL by querying the Gerrit API.

  Args:
    review_host: Base URL to the API endpoint.
    change_id: Identity of the CL to query.
    auth_cookie: Auth cookie if the API is not public.
    include_messages: Whether to pull and return the CL messages.
    include_detailed_accounts: Whether to pull and return the email of users
        in CL messages.
    include_mergeable: Whether to pull the mergeable status of the CL.
    include_review_status: Whether to pull the CL review status.

  Returns:
    An instance of `CLInfo`.  Optional fields might be `None`.

  Raises:
    GitUtilException if error occurs while querying the Gerrit API.
  """
  base_url = f'{review_host}/changes/{change_id}'
  gerrit_resps = []

  @RetryOnException(retry_value=(GitUtilException, ))
  def GetChangeInfo(scope: str, params: Sequence[Tuple[str, str]]):
    resp = _InvokeGerritAPIJSON('GET', f'{base_url}{scope}', params,
                                auth_cookie=auth_cookie)
    gerrit_resps.append(resp)
    return resp

  params = []
  if include_messages:
    params.append(('o', 'MESSAGES'))
  if include_detailed_accounts:
    params.append(('o', 'DETAILED_ACCOUNTS'))
  if include_review_status:
    params.append(('o', 'LABELS'))
  cl_info_json = GetChangeInfo('', params)

  def ConvertGerritCLMessage(cl_message_info_json):
    return CLMessage(
        cl_message_info_json['message'], cl_message_info_json['author']['email']
        if include_detailed_accounts else None)

  def ConvertGerritTimestamp(timestamp):
    return datetime.datetime.strptime(timestamp[:-3], '%Y-%m-%d %H:%M:%S.%f')

  def GetCLMergeableInfo(cl_status):
    if cl_status != CLStatus.NEW:
      return False
    cl_mergeable_info_json = GetChangeInfo('/revisions/current/mergeable', [])
    return cl_mergeable_info_json['mergeable']

  def GetCLReviewStatus(labels):
    code_review_labels = labels.get('Code-Review')
    if code_review_labels is None:
      raise GitUtilException('The Code-Review labels are missing.')
    is_approved = bool(code_review_labels.get('approved'))
    is_recommended = bool(code_review_labels.get('recommended'))
    is_rejected = bool(code_review_labels.get('rejected'))
    is_disliked = bool(code_review_labels.get('disliked'))

    # If some review votes are positive while some are negative, return
    # ambiguous.
    if (is_approved or is_recommended) and (is_rejected or is_disliked):
      return CLReviewStatus.AMBIGUOUS

    # Approved and rejected takes the priority.
    if is_approved:
      return CLReviewStatus.APPROVED
    if is_rejected:
      return CLReviewStatus.REJECTED
    if is_recommended:
      return CLReviewStatus.RECOMMENDED
    if is_disliked:
      return CLReviewStatus.DISLIKED
    return CLReviewStatus.NEUTRAL

  try:
    cl_status = _GERRIT_CL_STATUS_TO_CL_STATUS[cl_info_json['status']]
    cl_info_messages = (
        list(map(ConvertGerritCLMessage, cl_info_json['messages']))
        if include_messages else None)
    cl_info_created_time = ConvertGerritTimestamp(cl_info_json['created'])
    cl_info_mergeable = (
        GetCLMergeableInfo(cl_status) if include_mergeable else None)
    cl_review_status = (
        GetCLReviewStatus(cl_info_json['labels'])
        if include_review_status else None)
    return CLInfo(cl_info_json['change_id'], cl_info_json['_number'], cl_status,
                  cl_review_status, cl_info_messages, cl_info_mergeable,
                  cl_info_created_time)
  except GitUtilException:
    raise
  except Exception as ex:
    logging.debug('Unexpected Gerrit API response for CL: %r.', gerrit_resps)
    raise GitUtilException('Failed to parse the Gerrit API response.') from ex


def AbandonCL(review_host, auth_cookie, change_id,
              reason: Optional[str] = None):
  """Abandons a CL

  Args:
    review_host: Review host of repo
    auth_cookie: Auth cookie
    change_id: Change ID
    reason: An optional string message as the reason to abandon the CL.
  """
  try:
    _InvokeGerritAPIJSON('POST', f'{review_host}/a/changes/{change_id}/abandon',
                         auth_cookie=auth_cookie,
                         json_body={'message': reason} if reason else None)
  except GitUtilException as ex:
    raise GitUtilException(
        f'Abandon failed for change id: {change_id}.') from ex


def GetGerritCredentials():
  credential, unused_project_id = google.auth.default(scopes=[GERRIT_SCOPE])

  # If not running on AppEngine env, use impersonated credential.
  # Require `gcloud auth application-default login`
  if IMPERSONATED_SERVICE_ACCOUNT:
    credential = impersonated_credentials.Credentials(
        source_credentials=credential,
        target_principal=IMPERSONATED_SERVICE_ACCOUNT,
        target_scopes=[GERRIT_SCOPE])

  credential.refresh(google.auth.transport.requests.Request())
  service_account_name = credential.service_account_email
  token = credential.token
  return service_account_name, token


def GetGerritAuthCookie():
  service_account_name, token = GetGerritCredentials()
  return f'o=git-{service_account_name}={token}'
