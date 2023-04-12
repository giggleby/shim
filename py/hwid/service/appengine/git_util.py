# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import collections
import contextlib
import datetime
import enum
import functools
import hashlib
import http
import http.client
import io
import logging
import os
import re
import time
from typing import Any, DefaultDict, Deque, MutableMapping, MutableSequence, NamedTuple, Optional, Sequence, Tuple, Type, Union
import urllib.parse

import certifi
from dulwich import client as dw_client
from dulwich import objects as dw_objects
from dulwich import porcelain
from dulwich import refs as dw_refs
from dulwich import repo as dw_repo
import google.auth
from google.auth import impersonated_credentials
import google.auth.transport.requests
import urllib3
import urllib3.exceptions

from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import json_utils
from cros.factory.utils import schema


# Constants.
HEAD = b'HEAD'
DEFAULT_REMOTE_NAME = b'origin'
REF_HEADS_PREFIX = b'refs/heads/'
REF_REMOTES_PREFIX = b'refs/remotes/'
NORMAL_FILE_MODE = 0o100644
EXEC_FILE_MODE = 0o100755
DIR_MODE = 0o040000
GERRIT_SCOPE = 'https://www.googleapis.com/auth/gerritcodereview'
IMPERSONATED_SERVICE_ACCOUNT = os.getenv('IMPERSONATED_SERVICE_ACCOUNT')

_BOT_COMMIT = 'Bot-Commit'
_CODE_REVIEW = 'Code-Review'
_COMMIT_QUEUE = 'Commit-Queue'
_VERIFIED = 'Verified'
_AUTO_SUBMIT = 'Auto-Submit'
_RUBBER_STAMPER_ACCOUNT = 'rubber-stamper@appspot.gserviceaccount.com'


class ReviewVote(NamedTuple):
  label: str
  score: int


class ApprovalCase(enum.Enum):
  APPROVED = enum.auto()
  REJECTED = enum.auto()
  NEED_MANUAL_REVIEW = enum.auto()
  COMMIT_QUEUE = enum.auto()

  def ConvertToVotes(self) -> Sequence[ReviewVote]:
    return _REVIEW_VOTES_OF_CASE[self]


_REVIEW_VOTES_OF_CASE = {
    ApprovalCase.APPROVED: [
        ReviewVote(_BOT_COMMIT, 1),
        ReviewVote(_CODE_REVIEW, 0),
        ReviewVote(_COMMIT_QUEUE, 2),
    ],
    ApprovalCase.REJECTED: [
        ReviewVote(_BOT_COMMIT, 0),
        ReviewVote(_CODE_REVIEW, -2),
        ReviewVote(_COMMIT_QUEUE, 0),
    ],
    ApprovalCase.NEED_MANUAL_REVIEW: [
        ReviewVote(_BOT_COMMIT, 0),
        ReviewVote(_CODE_REVIEW, 0),
        ReviewVote(_COMMIT_QUEUE, 0),
    ],
    ApprovalCase.COMMIT_QUEUE: [
        ReviewVote(_VERIFIED, 0),
        ReviewVote(_COMMIT_QUEUE, 2)
    ],
}


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
  """Exceptions of git_util operations."""


class GitFileNotFoundException(GitUtilException):
  """Raised when file is not found."""


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


def _InvokeGerritAPI(
    method: str,
    url: str,
    params: Optional[Sequence[Tuple[str, str]]] = None,
    auth_cookie: str = '',
    content_type: str = '',
    body: bytes = b'',
    json_body: Optional[Any] = None,
    return_resp: bool = False,
    accept_not_found: bool = False,
) -> Union[type(None), bytes, http.client.HTTPResponse]:
  """Invokes a Gerrit API endpoint and returns the response in bytes.

  Args:
    method: The HTTP method like "GET" or "POST".
    url: The URL of the API without HTTP parameters.
    params: A list of HTTP parameters.
    auth_cookie: The auth cookie uses to create the pool manager.
    content_type: The Content-type field in the request header.
    body: The HTTP request body in bytes.
    json_body: The JSON-seralizable object to be attached in the HTTP body. Will
      override `content_type` and `body` if provided.
    return_resp: Return the whole response body.
    accept_not_found: If `return_resp` is `False` and `accept_not_found` is
      `True`, this method returns `None` when the response code is 404 instead
      of raising the exception.

  Returns:
    The response in bytes.

  Raises:
    GitUtilException: If the invocation ends unsuccessfully.
  """
  if params:
    url = f'{url}?{urllib.parse.urlencode(params)}'

  if json_body is not None:
    content_type = 'application/json'
    body = json_utils.DumpStr(json_body).encode('utf-8')

  pool_manager = _CreatePoolManager(cookie=auth_cookie,
                                    content_type=content_type)

  try:
    resp = pool_manager.urlopen(method, url, body=body)
  except urllib3.exceptions.HTTPError as ex:
    raise GitUtilException(f'Invalid url {url!r}.') from ex

  if return_resp:
    return resp

  if resp.status == http.HTTPStatus.NOT_FOUND and accept_not_found:
    return None

  if resp.status != http.HTTPStatus.OK:
    raise GitUtilException(
        f'Request {url!r} unsuccessfully with code {resp.status!r}.')

  return resp.data


def _InvokeGerritAPIJSON(method: str, url: str,
                         params: Optional[Sequence[Tuple[str, str]]] = None,
                         auth_cookie: str = '', json_body: Optional[Any] = None,
                         response_schema: Optional[schema.BaseType] = None):
  """Invokes a Gerrit API endpoint and returns the response payload in JSON.

  Args:
    method: See `_InvokeGerritAPI`.
    url: See `_InvokeGerritAPI`.
    params: See `_InvokeGerritAPI`.
    auth_cookie: See `_InvokeGerritAPI`.
    json_body: The JSON-seralizable object to be attached in the HTTP body.
    response_schema: If specified, validates the schema response JSON value.

  Returns:
    The JSON-compatible response payload.

  Raises:
    GitUtilException: If the invocation ends unsuccessfully.
  """
  kwargs = {
      'params': params,
      'auth_cookie': auth_cookie,
      'json_body': json_body,
  }
  raw_data = _InvokeGerritAPI(method, url, **kwargs)
  try:
    # the response starts with a magic prefix line for preventing XSSI which
    # should be stripped.
    stripped_json_bytes = raw_data.split(b'\n', 1)[1]
    json_obj = json_utils.LoadStr(stripped_json_bytes)
    if response_schema:
      response_schema.Validate(json_obj)
    return json_obj
  except Exception as ex:
    raise GitUtilException(f'Response format error: {raw_data!r}.') from ex


class GitUtilNoModificationException(GitUtilException):
  """Raised if no modification is made for commit."""


class GitFilesystemAdapter(filesystem_adapter.IFileSystemAdapter):

  def __init__(self, memory_repo):
    self._memory_repo = memory_repo

  class ExceptionMapper(contextlib.AbstractContextManager):

    def __exit__(self, value_type, value, traceback):
      if isinstance(value, GitFileNotFoundException):
        raise filesystem_adapter.NotFoundException(str(value)) from value
      if isinstance(value, Exception):
        raise filesystem_adapter.FileSystemAdapterException(str(value)) from \
            value

  EXCEPTION_MAPPER = ExceptionMapper()

  @classmethod
  def GetExceptionMapper(cls):
    """See base class."""
    return cls.EXCEPTION_MAPPER

  def _ReadFile(self, path: str,
                encoding: Optional[str] = 'utf-8') -> Union[str, bytes]:
    """See base class."""
    head_commit = self._memory_repo[HEAD]
    root = self._memory_repo[head_commit.tree]
    try:
      mode, sha = root.lookup_path(self._memory_repo.get_object, _B(path))
    except KeyError:
      raise GitFileNotFoundException(f'Path {path!r} is not a file.') from None
    if mode != NORMAL_FILE_MODE:
      raise GitUtilException(f'Path {path!r} is not a file.')
    data = self._memory_repo[sha].data
    if encoding is not None:
      return str(data, encoding=encoding)
    return data

  def _WriteFile(self, path: str, content: Union[str, bytes],
                 encoding: Optional[str] = 'utf-8'):
    raise NotImplementedError('GitFilesystemAdapter is read-only.')

  def _DeleteFile(self, path: str):
    raise NotImplementedError('GitFilesystemAdapter is read-only.')

  def _ListFiles(self, prefix: Optional[str] = None) -> Sequence[str]:
    """See base class."""
    if prefix is None:
      prefix = ''

    ret = []
    for name, mode, unused_data in self._memory_repo.list_files(prefix):
      if mode == NORMAL_FILE_MODE:
        ret.append(name)
    return ret


class MemoryRepo(dw_repo.MemoryRepo):
  """Enhance MemoryRepo with push ability."""

  def __init__(self, auth_cookie, *args, **kwargs):
    """Initializes with auth_cookie."""
    super().__init__(*args, **kwargs)
    self.auth_cookie = auth_cookie

  def shallow_clone(self, remote_location, branch):
    """Shallow clones objects of a branch from a remote server.

    Args:
      remote_location: String identifying a remote server
      branch: Branch
    """

    parsed = urllib.parse.urlparse(remote_location)

    pool_manager = _CreatePoolManager(cookie=self.auth_cookie)

    client = dw_client.HttpGitClient.from_parsedurl(
        parsed, config=self.get_config_stack(), pool_manager=pool_manager)
    fetch_result = client.fetch(
        parsed.path, self, determine_wants=lambda mapping:
        [mapping[REF_HEADS_PREFIX + _B(branch)]], depth=1)
    stripped_refs = dw_refs.strip_peeled_refs(fetch_result.refs)
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
        if not isinstance(sub, dw_objects.Tree):
          # if child_name exists but not a dir
          raise GitUtilException
      else:
        # not exists, create a new tree
        sub = dw_objects.Tree()
      self.recursively_add_file(sub, path_splits[1:], file_name, mode, blob)
      cur.add(child_name, DIR_MODE, sub.id)
    else:
      # reach the directory of the target file
      if file_name in cur:
        unused_mod, sha = cur[file_name]
        existed_obj = self[sha]
        if not isinstance(existed_obj, dw_objects.Blob):
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
                                  dw_objects.Blob.from_string(_B(content)))
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


def CreateCL(
    git_url: str,
    auth_cookie: str,
    branch: str,
    new_files: Sequence[Tuple[str, int, Union[str, bytes]]],
    author: str,
    committer: str,
    commit_msg: str,
    reviewers: Optional[Sequence[str]] = None,
    cc: Optional[Sequence[str]] = None,
    bot_commit: bool = False,
    commit_queue: bool = False,
    repo: Optional[MemoryRepo] = None,
    topic: Optional[str] = None,
    verified: int = 0,
    auto_submit: bool = False,
    rubber_stamper: bool = False,
):
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
    bot_commit: True if this is an auto-approved CL.
    commit_queue: True if this CL is ready to be put into the commit queue.
    repo: The `MemoryRepo` instance to create the commit.  If not specified,
        this function clones the repository from `git_url:branch`.
    topic: A string of topic set for CL.
    verified: Vote Verified. The score should be {-1, 0, 1}.
    auto_submit: True if Auto-Submit vote is set.
    rubber_stamper: True if Rubber Stamper is set as a reviewer.
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
      _B(f'{commit_msg}\n\nChange-Id: {change_id}'), author=_B(author),
      committer=_B(committer), tree=updated_tree.id)

  options = []
  if reviewers:
    options.extend(f'r={email}' for email in reviewers)
  if rubber_stamper:
    options.append(f'r={_RUBBER_STAMPER_ACCOUNT}')
  if cc:
    options.extend(f'cc={email}' for email in cc)
  if bot_commit:
    options.append(f'l={_BOT_COMMIT}+1')
  if commit_queue:
    options.append(f'l={_COMMIT_QUEUE}+2')
  if verified:
    options.append(f'l={_VERIFIED}{verified:+d}')
  if auto_submit:
    options.append(f'l={_AUTO_SUBMIT}+1')
  if topic:
    options.append(f'topic={topic}')
  target_branch = f'refs/for/refs/heads/{branch}'
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
  branch_name = _InvokeGerritAPIJSON(
      'GET', git_url, auth_cookie=auth_cookie, response_schema=schema.Scalar(
          'refs head', str))
  if branch_name.startswith(REF_HEADS_PREFIX.decode()):
    branch_name = branch_name[len(REF_HEADS_PREFIX.decode()):]
  return branch_name


_BRANCH_INFO_SCHEMA = schema.FixedDict(
    'BranchInfo', items={
        'ref': schema.Scalar('ref', str),
        'revision': schema.Scalar('revision', str),
    }, allow_undefined_keys=True)


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
  branch_info = _InvokeGerritAPIJSON('GET', git_url, auth_cookie=auth_cookie,
                                     response_schema=_BRANCH_INFO_SCHEMA)
  return branch_info['revision']


@RetryOnException(retry_value=(GitUtilException, ))
def GetFileContent(git_url_prefix: str, project: str, path: str,
                   commit_id: Optional[str] = None,
                   change_id: Optional[str] = None,
                   branch: Optional[str] = None, auth_cookie: str = '',
                   optional: bool = False) -> Optional[bytes]:
  """Gets file content on Gerrit.

  Uses the gerrit API to get the file content.  If commit_id is specified

  Args:
    git_url_prefix: HTTPS repo url.
    project: Project name.
    path: Path to the file.
    commit_id: The commit id which is the version of the file.
    change_id: The identity of CL which is the version of the file.
    branch: Branch name, use the branch HEAD tracks if set to None.
    auth_cookie: Auth cookie.
    optional: Whether the file is optional.

  Returns:
    If the file is not found and `optional` is `True`, it returns `None`.
    Otherwise it returns the file contents in bytes.
  """
  project, path = map(lambda s: urllib.parse.quote(s, safe=''), (project, path))
  if commit_id:
    if branch:
      logging.warning('Commit id is already specified, ignore branch %r.',
                      branch)
    if change_id:
      logging.warning('Commit id is already specified, ignore change_id %s.',
                      change_id)

    git_url = (f'{git_url_prefix}/projects/{project}/commits/{commit_id}/files/'
               f'{path}/content')
  elif change_id:
    if branch:
      logging.warning('Change ID is already specified, ignore branch %r.',
                      branch)
    git_url = (f'{git_url_prefix}/changes/{change_id}/revisions/current/files/'
               f'{path}/content')
  else:
    branch = branch or urllib.parse.quote(
        GetCurrentBranch(git_url_prefix, project, auth_cookie), safe='')
    git_url = (f'{git_url_prefix}/projects/{project}/branches/{branch}/files/'
               f'{path}/content')
  raw_data = _InvokeGerritAPI('GET', git_url, auth_cookie=auth_cookie,
                              accept_not_found=optional)
  if raw_data is None:
    return raw_data
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


class CLComment(NamedTuple):
  """Holds one single comment on Gerrit.

  Attributes:
    email: The comment author if the server provides such info.
    message: The raw comment message.
  """
  email: Optional[str]
  message: str


class CLCommentThread(NamedTuple):
  """Holds one comment thread on Gerrit.

  Attributes:
    path: `None` if the comment thread targets the patch set.  `"/COMMIT_MSG"`
      if the comment thread targets to the commit message.  The file path name
      in the git repo if the comment thread targets to a touched file.
    context: The source context of the comment.  `None` if the comment thread
      targets the patch set.
    comments: The comment thread.
  """
  path: Optional[str]
  context: Optional[str]
  comments: Sequence[CLComment]


class CLInfo(NamedTuple):
  change_id: str
  cl_number: int
  subject: str
  status: CLStatus
  review_status: Optional[CLReviewStatus]
  mergeable: Optional[bool]
  created_time: datetime.datetime
  comment_threads: Optional[Sequence[CLCommentThread]]
  bot_commit: Optional[bool]
  commit_queue: Optional[bool]
  parent_cl_numbers: Optional[Sequence[int]]
  verified: Optional[bool]


def _ConvertGerritTimestamp(timestamp):
  return datetime.datetime.strptime(timestamp[:-3], '%Y-%m-%d %H:%M:%S.%f')


_ACCOUNT_INFO_SCHEMA = schema.FixedDict(
    'AccountInfo', items={
        '_account_id': schema.Scalar('_account_id', int),
    }, optional_items={
        'display_name': schema.Scalar('display_name', str),
        'email': schema.Scalar('email', str),
    }, allow_undefined_keys=True)
_APPROVAL_INFO_SCHEMA = schema.FixedDict(
    'ApprovalInfo', items={
        '_account_id': schema.Scalar('_account_id', int),
    }, optional_items={
        'value': schema.Scalar('value', int),
    }, allow_undefined_keys=True)
_LABEL_INFO_SCHEMA = schema.FixedDict(
    'LabelInfo', optional_items={
        'approved': _ACCOUNT_INFO_SCHEMA,
        'rejected': _ACCOUNT_INFO_SCHEMA,
        'recommended': _ACCOUNT_INFO_SCHEMA,
        'disliked': _ACCOUNT_INFO_SCHEMA,
        'all': schema.List('all', _APPROVAL_INFO_SCHEMA),
    }, allow_undefined_keys=True)
_CHANGE_INFO_SCHEMA = schema.FixedDict(
    'ChangeInfo', items={
        'status': schema.Scalar('status', str),
        'created': schema.Scalar('created', str),
        'change_id': schema.Scalar('change_id', str),
        '_number': schema.Scalar('_number', int),
        'subject': schema.Scalar('subject', str),
        'current_revision': schema.Scalar('current_revision', str),
        'owner': _ACCOUNT_INFO_SCHEMA,
    }, optional_items={
        'labels':
            schema.Dict('labels', schema.Scalar('label_name', str),
                        _LABEL_INFO_SCHEMA),
    }, allow_undefined_keys=True)
_MERGEABLE_INFO = schema.FixedDict(
    'MergeableInfo', items={'mergeable': schema.Scalar('mergeable', bool)},
    allow_undefined_keys=True)
_CONTEXT_LINE_SCHEMA = schema.FixedDict(
    'ContextLine', items={
        'line_number': schema.Scalar('line_number', int),
        'context_line': schema.Scalar('context_line', str),
    })
_COMMENT_INFO = schema.FixedDict(
    'CommentInfo', items={
        'id': schema.Scalar('id', str),
    }, optional_items={
        'path': schema.Scalar('path', str),
        'message': schema.Scalar('message', str),
        'author': _ACCOUNT_INFO_SCHEMA,
        'in_reply_to': schema.Scalar('in_reply_to', str),
        'context_lines': schema.List('context_lines', _CONTEXT_LINE_SCHEMA),
    }, allow_undefined_keys=True)
_COMMIT_INFO = schema.FixedDict(
    'commit', items={
        'commit':
            schema.Scalar('commit', str),
        'parents':
            schema.List(
                'parents',
                schema.FixedDict(
                    'commit', items={'commit': schema.Scalar('commit', str)}))
    }, allow_undefined_keys=True)
_RELATED_CHANGE_INFO = schema.FixedDict(
    'RelatedChangeInfo', items={
        'commit': _COMMIT_INFO,
        '_change_number': schema.Scalar('_change_number', int),
    }, allow_undefined_keys=True)
_RELATED_CHANGES_INFO = schema.FixedDict(
    'RelatedChangesInfo',
    items={'changes': schema.List('changes', _RELATED_CHANGE_INFO)},
    allow_undefined_keys=True)


def _ConvertCodeReviewLabelsToCLReviewStatus(code_review_labels):
  is_approved = bool(code_review_labels.get('approved'))
  is_recommended = bool(code_review_labels.get('recommended'))
  is_rejected = bool(code_review_labels.get('rejected'))
  is_disliked = bool(code_review_labels.get('disliked'))

  # No matter what other votes are, once there's a CR-2 vote, the whole CL is
  # considered rejected.
  if is_rejected:
    return CLReviewStatus.REJECTED

  # If some review votes are positive while some are negative, return
  # ambiguous.
  if (is_approved or is_recommended) and is_disliked:
    return CLReviewStatus.AMBIGUOUS

  # Approved and rejected takes the priority.
  if is_approved:
    return CLReviewStatus.APPROVED
  if is_recommended:
    return CLReviewStatus.RECOMMENDED
  if is_disliked:
    return CLReviewStatus.DISLIKED
  return CLReviewStatus.NEUTRAL


_PATCHSET_LEVEL_COMMENT_PATH = '/PATCHSET_LEVEL'


def _ConvertCommentInfoJSONToContext(comment_info_json) -> Optional[str]:
  path = comment_info_json.get('path')
  if not path:
    return None
  context_lines_json_or_none = comment_info_json.get('context_lines')
  if not context_lines_json_or_none:
    return path
  return '\n'.join([
      f'{path}:{context_line_json["line_number"]}:'
      f'{context_line_json["context_line"]}'
      for context_line_json in context_lines_json_or_none
  ])


def GetCLInfo(review_host, change_id, auth_cookie='', include_mergeable=False,
              include_review_status=False, include_comment_thread=False):
  """Gets the info of the specified CL by querying the Gerrit API.

  Args:
    review_host: Base URL to the API endpoint.
    change_id: Identity of the CL to query.
    auth_cookie: Auth cookie if the API is not public.
    include_mergeable: Whether to pull the mergeable status of the CL.
    include_review_status: Whether to pull the CL review status.
    include_comment_thread: Whether to pull comments of the CL.

  Returns:
    An instance of `CLInfo`.  Optional fields might be `None`.

  Raises:
    GitUtilException if error occurs while querying the Gerrit API.
  """
  base_url = f'{review_host}/changes/{change_id}'
  gerrit_resps = []

  @RetryOnException(retry_value=(GitUtilException, ))
  def _GetChangeInfo(scope: str, params: Sequence[Tuple[str, str]],
                     response_schema: schema.BaseType):
    resp = _InvokeGerritAPIJSON('GET', f'{base_url}{scope}', params,
                                auth_cookie=auth_cookie,
                                response_schema=response_schema)
    gerrit_resps.append(resp)
    return resp

  def _GetCLMergeableInfo(cl_status):
    if cl_status != CLStatus.NEW:
      return False
    cl_mergeable_info_json = _GetChangeInfo('/revisions/current/mergeable', [],
                                            _MERGEABLE_INFO)
    return cl_mergeable_info_json['mergeable']

  def _GetCLReviewStatus(change_info_json):
    if not include_review_status:
      return None
    code_review_labels = change_info_json.get('labels', {}).get(_CODE_REVIEW)
    if code_review_labels is None:
      raise GitUtilException('The Code-Review labels are missing.')
    return _ConvertCodeReviewLabelsToCLReviewStatus(code_review_labels)

  def _GetCLVerified(change_info_json):
    if not include_review_status:
      return None
    verified_labels = change_info_json.get('labels', {}).get(_VERIFIED, {})

    # Exclude the rejected vote by bot (as CL owner) itself
    owner_id = change_info_json.get('owner', {}).get('_account_id')
    verified = any(
        vote.get('value') == 1 for vote in verified_labels.get('all', []))
    rejected = any(
        vote.get('value') == -1
        for vote in verified_labels.get('all', [])
        if vote.get('_account_id') != owner_id)
    return verified and not rejected

  def _GetBotApprovalStatus(change_info_json):
    if not include_review_status:
      return None
    bot_commit_labels = change_info_json.get('labels', {}).get(_BOT_COMMIT, {})
    return bool(bot_commit_labels.get('approved'))

  def _GetCommitQueueStatus(change_info_json):
    if not include_review_status:
      return None
    cq_labels = change_info_json.get('labels', {}).get(_COMMIT_QUEUE, {})
    return bool(cq_labels.get('approved'))

  def _GetParentCLNumbers(commit_id: str) -> Optional[Sequence[int]]:
    if not include_review_status:
      return None
    related_cls_info = _GetChangeInfo('/revisions/current/related', [],
                                      _RELATED_CHANGES_INFO)

    parent_cids: DefaultDict[str, MutableSequence[str]] = (
        collections.defaultdict(list))
    related_cl_numbers: MutableMapping = {}
    for related_cl in related_cls_info['changes']:
      commit = related_cl['commit']
      related_cl_numbers[commit['commit']] = related_cl['_change_number']
      parent_cids[commit['commit']].extend(
          c['commit'] for c in commit['parents'])

    # Use BFS to collect all parent CL numbers from all related CLs.
    q: Deque[str] = collections.deque()
    q.append(commit_id)
    parent_cl_numbers: MutableSequence[int] = []
    while q:
      cid = q.popleft()
      for parent_commit_id in parent_cids[cid]:
        if parent_commit_id in related_cl_numbers:
          parent_cl_numbers.append(related_cl_numbers[parent_commit_id])
          q.append(parent_commit_id)

    return parent_cl_numbers

  def _GetCLCommentThread():
    comment_json_of_path = _GetChangeInfo(
        '/comments', [('enable-context', 'true')],
        schema.Dict('comment_map', schema.Scalar('path', str),
                    schema.List('comments', _COMMENT_INFO)))

    comment_json_list_of_reply_id = collections.defaultdict(list)
    comment_id_queue = collections.deque()
    root_comment_threads = []
    comment_thread_of_comment_id = {}
    for path, comment_json_list in comment_json_of_path.items():
      if path == _PATCHSET_LEVEL_COMMENT_PATH:
        path = None
      for comment_info_json in comment_json_list:
        # From
        # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#comment-info
        # , we should backfill the path because the response message from Gerrit
        # is a dictionary that maps the file path to the comment info instance.
        comment_info_json['path'] = path

        reply_id = comment_info_json.get('in_reply_to')
        if reply_id:
          comment_json_list_of_reply_id[reply_id].append(comment_info_json)
        else:
          comment_id = comment_info_json['id']
          root_comment_thread = CLCommentThread(
              path, _ConvertCommentInfoJSONToContext(comment_info_json), [
                  CLComment(comment_info_json['author'].get('email'),
                            comment_info_json.get('message', '')),
              ])
          comment_thread_of_comment_id[comment_id] = root_comment_thread
          comment_id_queue.append(comment_id)
          root_comment_threads.append(root_comment_thread)

    while comment_id_queue:
      comment_id = comment_id_queue.popleft()
      comment_thread = comment_thread_of_comment_id[comment_id]
      replying_comment_json_list = comment_json_list_of_reply_id.pop(
          comment_id, [])
      for replying_comment_json in replying_comment_json_list:
        comment_thread.comments.append(
            CLComment(replying_comment_json['author'].get('email'),
                      replying_comment_json.get('message', '')))
        replying_comment_id = replying_comment_json['id']
        comment_thread_of_comment_id[replying_comment_id] = comment_thread
        comment_id_queue.append(replying_comment_id)
    if comment_json_list_of_reply_id:
      logging.error(
          'Got unexpected reply comments (review host = %r, '
          'change_id = %r).', review_host, change_id)

    return root_comment_threads

  options = [('o', 'CURRENT_REVISION')]
  if include_review_status:
    options.append(('o', 'LABELS'))
  change_info_json = _GetChangeInfo('', options, _CHANGE_INFO_SCHEMA)
  commit_id = change_info_json['current_revision']

  try:
    cl_status = _GERRIT_CL_STATUS_TO_CL_STATUS[change_info_json['status']]
    mergeable_or_none = (
        _GetCLMergeableInfo(cl_status) if include_mergeable else None)
    comment_threads_or_none = (
        _GetCLCommentThread() if include_comment_thread else None)
    return CLInfo(
        change_id=change_info_json['change_id'],
        cl_number=change_info_json['_number'],
        subject=change_info_json['subject'], status=cl_status,
        review_status=_GetCLReviewStatus(change_info_json),
        mergeable=mergeable_or_none, created_time=_ConvertGerritTimestamp(
            change_info_json['created']),
        comment_threads=comment_threads_or_none,
        bot_commit=_GetBotApprovalStatus(change_info_json),
        commit_queue=_GetCommitQueueStatus(change_info_json),
        parent_cl_numbers=_GetParentCLNumbers(commit_id),
        verified=_GetCLVerified(change_info_json))
  except GitUtilException:
    raise
  except Exception as ex:
    logging.debug('Unexpected Gerrit API response for CL: %r.', gerrit_resps)
    raise GitUtilException('Failed to parse the Gerrit API response.') from ex


def ReviewCL(review_host: str, auth_cookie: str, cl_number: int,
             reasons: Sequence[str], approval_case: ApprovalCase,
             reviewers: Optional[Sequence[str]] = None,
             ccs: Optional[Sequence[str]] = None):
  """Reviews a CL.

  Args:
    review_host: Review host of repo.
    auth_cookie: Auth cookie.
    cl_number: The CL number.
    reasons: An optional list of string messages as the reason of the action.
    approval_case: The approval case.
    reviewers: The additional reviewers to be added.
    ccs: The additional CC reviewers to be added.
  """
  reviewers = reviewers or []
  ccs = ccs or []
  votes = approval_case.ConvertToVotes()
  try:
    _InvokeGerritAPIJSON(
        'POST', f'{review_host}/changes/{cl_number}/revisions/current/review',
        auth_cookie=auth_cookie, json_body={
            'ready':
                True,
            'message':
                '\n'.join(reasons),
            'labels': {vote.label: vote.score
                       for vote in votes},
            'reviewers': [{
                'reviewer': reviewer
            } for reviewer in reviewers] + [{
                'reviewer': cc,
                'state': 'CC'
            } for cc in ccs],
        })
  except GitUtilException as ex:
    raise GitUtilException(f'Review failed for CL number: {cl_number}.') from ex


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


def RebaseCL(review_host: str, change_id: str, auth_cookie: str = '',
             force=False) -> Optional[Sequence[str]]:
  """Rebases a CL.


  Args:
    review_host: Review host of repo
    change_id: Change ID
    auth_cookie: Auth cookie
    force: Force rebase if merge conflict. CL will be marked as WIP if conflict
      exists.

  Returns:
    Path of merge conflict files if `force` is not set. else None
  """
  try:
    resp = _InvokeGerritAPI(
        'POST', f'{review_host}/changes/{change_id}/rebase',
        auth_cookie=auth_cookie, return_resp=not force,
        json_body={'allow_conflicts': force} if force else None)
    if not force:
      if resp.status == 409:
        return resp.data.decode().split('merge conflict(s):\n')[-1].split()
      if resp.status == http.HTTPStatus.OK:
        return []
      raise GitUtilException

  except GitUtilException as ex:
    raise GitUtilException(f'Rebase failed for change id: {change_id}.') from ex
  return None


def PatchCL(review_host: str, change_id: str, path: str, content: bytes,
            auth_cookie=''):
  """Patches file content to a CL.

  Args:
    review_host: Review host of repo.
    change_id: Change ID.
    path: file path to be patched.
    content: content to be patched.
    auth_cookie: Auth cookie.
  """
  # Try to delete staged change edit if existing.
  _InvokeGerritAPI('DELETE', f'{review_host}/changes/{change_id}/edit',
                   auth_cookie=auth_cookie, return_resp=True)

  # Add file to change edit.
  path = urllib.parse.quote(path, safe='')
  content = f'data:text/plain;base64,{base64.b64encode(content).decode()}'
  resp = _InvokeGerritAPI(
      'PUT', f'{review_host}/changes/{change_id}/edit/{path}',
      auth_cookie=auth_cookie, json_body={"binary_content": content},
      return_resp=True)
  if resp.status == 409:
    logging.warning("No file changed. Patch request aborted.")
    return

  if resp.status != 204:
    raise GitUtilException(
        f'Failed to patch change id: {change_id}. code={resp.status}')

  # Publish change edit
  resp = _InvokeGerritAPI('POST',
                          f'{review_host}/changes/{change_id}/edit:publish',
                          auth_cookie=auth_cookie, return_resp=True)
  if resp.status != 204:
    raise GitUtilException(
        f'Failed to publish change id: {change_id}. code={resp.status}')


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
