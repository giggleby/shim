# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provide functionalities to access the HWID DB repository."""

import abc
import collections
import logging
import re
from typing import Mapping, NamedTuple, Optional, Sequence

from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import type_utils


class HWIDDBMetadata(NamedTuple):
  """A placeholder for metadata of a HWID DB."""
  name: str
  board_name: str
  version: int
  path: str


INTERNAL_REPO_REVIEW_URL = 'https://chrome-internal-review.googlesource.com'
INTERNAL_REPO_URL = 'https://chrome-internal.googlesource.com'
_CHROMEOS_HWID_PROJECT = 'chromeos/chromeos-hwid'
_PROJECTS_YAML_PATH = 'projects.yaml'
_UNVERIFIED_HASHTAG = 'cros-hwid-unverified-change'


def _ParseMetadata(raw_metadata) -> Mapping[str, HWIDDBMetadata]:
  metadata_yaml = yaml.safe_load(raw_metadata)
  hwid_db_metadata_of_name = collections.OrderedDict()
  for name, hwid_db_info in metadata_yaml.items():
    hwid_db_metadata_of_name[name] = HWIDDBMetadata(name, hwid_db_info['board'],
                                                    hwid_db_info['version'],
                                                    hwid_db_info['path'])
  return hwid_db_metadata_of_name


def _DumpMetadata(hwid_db_metadata_of_name):
  # TODO(wyuang): field `branch` is not used anymore. Check is there any other
  # internal service is still using this field.
  # yapf: disable
  return yaml.safe_dump(
      collections.OrderedDict(
          sorted((name,
                   collections.OrderedDict([('board', metadata.board_name),
                                            ('branch', 'main'),
                                            ('version', metadata.version),
                                            ('path', metadata.path)]))
                  for name, metadata in hwid_db_metadata_of_name.items())),
      indent=4, default_flow_style=False)


def _RemoveChecksum(text):
  return re.sub(r'^checksum:.*$', 'checksum:', text, flags=re.MULTILINE)


class HWIDRepoError(Exception):
  """Root exception class for reporting unexpected error in HWID repo."""


class V3DBContents(NamedTuple):
  """Holds the HWID DB file contents of a v3 project."""
  internal_db: str
  external_db: str
  feature_matcher_source: Optional[str]


class HWIDRepoView(abc.ABC):
  """Represents a read-only view of a HWID repository snapshot."""

  _INTERNAL_DB_NAME_SUFFIX = '.internal'
  _FEATURE_MATCHER_SOURCE_SUFFIX = '.feature_matcher.textproto'

  @abc.abstractmethod
  def _LoadMandatoryTextFile(self, path: str) -> str:
    """Load a mandatory file from the repository file system.

    Args:
      path: The path of the file to load.

    Returns:
      The loaded file contents.

    Raises:
      HWIDRepoError: Failed to load the file.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def _LoadOptionalTextFile(self, path: str) -> Optional[str]:
    """Load an optional file from the repository file system.

    Args:
      path: The path of the file to load.

    Returns:
      The loaded file contents or `None` if the file doesn't exist.

    Raises:
      HWIDRepoError: Failed to load the file.
    """
    raise NotImplementedError

  @classmethod
  def _GetV3InternalDBPath(cls, path: str) -> str:
    return f'{path}{cls._INTERNAL_DB_NAME_SUFFIX}'

  @classmethod
  def _GetV3FeatureMatcherSourcePath(cls, path: str) -> str:
    return f'{path}{cls._FEATURE_MATCHER_SOURCE_SUFFIX}'

  @type_utils.LazyProperty
  def hwid_db_metadata_of_name(self) -> Mapping[str, HWIDDBMetadata]:
    raw_metadata = self._LoadMandatoryTextFile(_PROJECTS_YAML_PATH)
    try:
      return _ParseMetadata(raw_metadata)
    except Exception as ex:
      raise HWIDRepoError(f'Invalid {_PROJECTS_YAML_PATH}: {ex}') from None

  def ListHWIDDBMetadata(self) -> Sequence[HWIDDBMetadata]:
    """Returns a list of metadata of HWID DBs recorded in the HWID repo.

    Returns:
      A list of all HWID DB metadatas.

    Raises:
      HWIDRepoError: If unexpected error occurred while fetching the data.
    """
    return list(self.hwid_db_metadata_of_name.values())

  def GetHWIDDBMetadataByName(self, name: str) -> HWIDDBMetadata:
    """Returns the DB metadata of the specific project name in the HWID repo.

    Args:
      name: The project name to query.

    Returns:
      The HWID DB metadata.

    Raises:
      HWIDRepoError: If unexpected error occurred while fetching the data.
      ValueError: If the given project name is invalid.
    """
    try:
      return self.hwid_db_metadata_of_name[name]
    except KeyError:
      raise ValueError(f'Invalid HWID DB name: {name}.') from None

  def LoadV2HWIDDBByName(self, name: str) -> str:
    """Returns the HWID DB contents by the v2 project name.

    Args:
      name: The project name to query.

    Returns:
      The HWID V2 DB contents.

    Raises:
      ValueError: If the given project name is invalid or the corresponding
        project is not a HWID v2 one.
      HWIDRepoError: Got unexpected failures while loading.
    """
    metadata = self.GetHWIDDBMetadataByName(name)
    if metadata.version != 2:
      raise ValueError(f'{name} is not a HWID V2 project.')
    return self._LoadMandatoryTextFile(metadata.path)

  def LoadV3HWIDDBByName(self, name: str) -> V3DBContents:
    """Returns the HWID DB contents by the v3 project name.

    Args:
      name: The project name to query.

    Returns:
      The HWID V3 DB contents.

    Raises:
      ValueError: If the given project name is invalid or the corresponding
        project is not a HWID v3 one.
      HWIDRepoError: Got unexpected failures while loading.
    """
    metadata = self.GetHWIDDBMetadataByName(name)
    if metadata.version != 3:
      raise ValueError(f'{name} is not a HWID V3 project.')
    # TODO(yhong): Set `feature_matcher_source` to `None` only if the file
    #     does not exist.
    return V3DBContents(
        external_db=self._LoadMandatoryTextFile(metadata.path),
        internal_db=self._LoadMandatoryTextFile(
            self._GetV3InternalDBPath(metadata.path)),
        feature_matcher_source=self._LoadOptionalTextFile(
            self._GetV3FeatureMatcherSourcePath(metadata.path)))


class HWIDRepo(HWIDRepoView):

  def __init__(self, repo, repo_url, repo_branch, unverified_cl_ccs=None):
    """Constructor.

    Args:
      repo: The local cloned git repo.
      repo_url: URL of the HWID repo.
      repo_branch: Branch name to track in the HWID repo.
      unverified_cl_ccs: CC list when unverfied CL created.
    """
    self._repo = repo
    self._repo_url = repo_url
    self._repo_branch = repo_branch
    self._unverfied_cl_ccs = unverified_cl_ccs or []

    self._git_fs = git_util.GitFilesystemAdapter(self._repo)

  def _LoadMandatoryTextFile(self, path: str) -> str:
    """See base class."""
    try:
      return self._git_fs.ReadFile(path)
    except filesystem_adapter.FileSystemAdapterException as ex:
      raise HWIDRepoError(f'Failed to load {path}: {ex}.') from None

  def _LoadOptionalTextFile(self, path: str) -> Optional[str]:
    """See base class."""
    try:
      raw_contents = self._git_fs.ReadFile(path, encoding=None)
    except filesystem_adapter.NotFoundException:
      return None
    try:
      return raw_contents.decode('utf-8')
    except ValueError as ex:
      raise HWIDRepoError(f'Failed to load {path}: {ex}.') from None

  @property
  def hwid_db_commit_id(self) -> str:
    return self._repo.head().decode()

  def CommitHWIDDB(self, name: str, hwid_db_contents: str, commit_msg: str,
                   reviewers: Sequence[str], cc_list: Sequence[str],
                   bot_commit: bool = False, commit_queue: bool = False,
                   update_metadata: Optional[HWIDDBMetadata] = None,
                   hwid_db_contents_internal: Optional[str] = None,
                   feature_matcher_source: Optional[str] = None,
                   verified: int = 0):
    """Commit an HWID DB to the repo.

    Args:
      name: The project name of the HWID DB.
      hwid_db_contents: The contents of the HWID DB.
      commit_msg: The commit message.
      author: Author in form of "Name <email@domain>".
      reviewers: List of emails of reviewers.
      cc_list: List of emails of CC's.
      bot_commit: True if this is an auto-approved CL.
      commit_queue: True if this CL is ready to be put into the commit queue.
      update_metadata: A HWIDDBMetadata object to update for the project.
      hwid_db_contents_internal: The contents of the HWID DB in internal format.
      feature_matcher_source: Uses a string to represent the feature matcher
        source contents to push.  `None` to instruct this method not to update
        the contents.
      verified: Vote Verified. The score should be {-1, 0, 1}.

    Returns:
      A numeric ID of the created CL.

    Raises:
      ValueError if the given HWID DB name is invalid.
      git_util.GitUtilNoModificationException if no modification is made.
      HWIDRepoError for other unexpected errors.
    """
    new_files = []
    if update_metadata:
      self.hwid_db_metadata_of_name[name] = update_metadata
      new_raw_metadata = _DumpMetadata(self.hwid_db_metadata_of_name)
      new_files.append((_PROJECTS_YAML_PATH, git_util.NORMAL_FILE_MODE,
                        new_raw_metadata.encode('utf-8')))
    try:
      path = self.hwid_db_metadata_of_name[name].path
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None
    hwid_db_contents = _RemoveChecksum(hwid_db_contents)
    new_files.append(
        (path, git_util.NORMAL_FILE_MODE, hwid_db_contents.encode('utf-8')))

    if not hwid_db_contents_internal:
      hwid_db_contents_internal = hwid_db_contents

    internal_path = self._GetV3InternalDBPath(path)
    hwid_db_contents_internal = _RemoveChecksum(hwid_db_contents_internal)
    new_files.append((internal_path, git_util.NORMAL_FILE_MODE,
                      hwid_db_contents_internal.encode('utf-8')))
    if feature_matcher_source is not None:
      feature_matcher_source_path = self._GetV3FeatureMatcherSourcePath(path)
      new_files.append((feature_matcher_source_path, git_util.NORMAL_FILE_MODE,
                        feature_matcher_source.encode('utf-8')))

    try:
      author_email, unused_token = git_util.GetGerritCredentials()
      author = f'chromeoshwid <{author_email}>'
      hashtags = []
      if verified == -1:
        hashtags = [_UNVERIFIED_HASHTAG]
        cc_list.extend(self._unverfied_cl_ccs)
      change_id, cl_number = git_util.CreateCL(
          git_url=self._repo_url, auth_cookie=git_util.GetGerritAuthCookie(),
          branch=self._repo_branch, new_files=new_files, author=author,
          committer=author, commit_msg=commit_msg, reviewers=reviewers,
          cc=list(set(cc_list)), bot_commit=bot_commit,
          commit_queue=commit_queue, repo=self._repo, verified=verified,
          hashtags=hashtags)
      if cl_number is None:
        logging.warning(
            'Failed to parse CL number from change_id=%s. Get CL number from '
            'Gerrit.', change_id)
        cl_info = git_util.GetCLInfo(INTERNAL_REPO_REVIEW_URL, change_id,
                                     auth_cookie=git_util.GetGerritAuthCookie())
        cl_number = cl_info.cl_number
    except git_util.GitUtilNoModificationException:
      raise
    except git_util.GitUtilException as ex:
      raise HWIDRepoError from ex
    return cl_number


class _GerritHWIDRepo(HWIDRepoView):
  """Represents a view of HWID repository on Gerrit."""

  @abc.abstractmethod
  def _GetGitFileRawContents(
      self, path: str, optional: bool) -> Optional[bytes]:
    """Fetches file contents over Gerrit API.

    Args:
      path: The path name of the file to fetch.
      optional: Whether to return `None` if the file is not found.

    Returns:
      If `optional` is `True` and the file is not found, it returns `None`.
      Otherwise it returns the file contents in bytes.

    Raises:
      git_util.GitUtilException: if the Gerrit API invocation doesn't success.
    """

  def _LoadMandatoryTextFile(self, path: str) -> str:
    """See base class."""
    try:
      return self._GetGitFileRawContents(path, optional=False).decode()
    except (git_util.GitUtilException, ValueError) as ex:
      raise HWIDRepoError(f'Failed to load {path}: {ex}.') from None

  def _LoadOptionalTextFile(self, path: str) -> Optional[str]:
    """See base class."""
    try:
      raw_contents = self._GetGitFileRawContents(path, optional=True)
      if raw_contents is None:
        return None
      return raw_contents.decode()
    except (git_util.GitUtilException, ValueError) as ex:
      raise HWIDRepoError(f'Failed to load {path}: {ex}.') from None


class GerritCLHWIDRepo(_GerritHWIDRepo):
  """Represents a view of HWID repository from a specific Gerrit CL."""

  def __init__(self, repo_branch: str, cl_number: int):
    self._repo_branch = repo_branch
    self._cl_number = cl_number

  def _GetGitFileRawContents(
      self, path: str, optional: bool) -> Optional[bytes]:
    """See base class."""
    return git_util.GetFileContent(
        INTERNAL_REPO_REVIEW_URL, _CHROMEOS_HWID_PROJECT, path,
        change_id=self._cl_number, auth_cookie=git_util.GetGerritAuthCookie(),
        optional=optional)


class GerritToTHWIDRepo(_GerritHWIDRepo):
  """Represents a view of HWID repository from Gerrit ToT."""

  def __init__(self, repo_branch: str):
    self._repo_branch = repo_branch

  def _GetGitFileRawContents(
      self, path: str, optional: bool) -> Optional[bytes]:
    """See base class."""
    return git_util.GetFileContent(
        INTERNAL_REPO_REVIEW_URL, _CHROMEOS_HWID_PROJECT, path,
        commit_id=self.commit_id, auth_cookie=git_util.GetGerritAuthCookie(),
        optional=optional)

  @type_utils.LazyProperty
  def commit_id(self) -> str:
    return git_util.GetCommitId(
        INTERNAL_REPO_REVIEW_URL, _CHROMEOS_HWID_PROJECT,
        branch=self._repo_branch, auth_cookie=git_util.GetGerritAuthCookie())


HWIDDBCLInfo = git_util.CLInfo
HWIDDBCLStatus = git_util.CLStatus
HWIDDBCLReviewStatus = git_util.CLReviewStatus
HWIDDBCLCommentThread = git_util.CLCommentThread
HWIDDBCLComment = git_util.CLComment


class HWIDRepoManager:

  def __init__(self, repo_branch: str,
               unverified_cl_ccs: Optional[Sequence[str]] = None):
    """Constructor.

    Args:
      repo_branch: The git branch name of the HWID repo to access.  Assigning
          `None` to use the default "main" branch.
      unverified_cl_ccs: CC list when unverfied CL created.
    """
    self._repo_branch = repo_branch
    self._unverfied_cl_ccs = unverified_cl_ccs or []

  def GetLiveHWIDRepo(self) -> HWIDRepo:
    """Returns an HWIDRepo instance for accessing the up-to-date HWID repo."""
    if self._repo_branch is None:
      repo_branch = git_util.GetCurrentBranch(INTERNAL_REPO_REVIEW_URL,
                                              _CHROMEOS_HWID_PROJECT,
                                              git_util.GetGerritAuthCookie())
    else:
      repo_branch = self._repo_branch
    repo_url = f'{INTERNAL_REPO_REVIEW_URL}/{_CHROMEOS_HWID_PROJECT}'
    repo = git_util.MemoryRepo(git_util.GetGerritAuthCookie())
    repo.shallow_clone(repo_url, repo_branch)
    return HWIDRepo(repo, repo_url, repo_branch, self._unverfied_cl_ccs)

  def GetHWIDDBCLInfo(self, cl_number) -> HWIDDBCLInfo:
    """Returns the CL info of the given HWID DB CL number.

    Args:
      cl_number: The CL number.

    Returns:
      The detailed info of the queried CL, including the review status,
      mergeable status and comment threads for commit message and touched
      files.

    Raises:
      HWIDRepoError: Failed to fetch the CL info from Gerrit.
    """
    try:
      cl_info = git_util.GetCLInfo(INTERNAL_REPO_REVIEW_URL, cl_number,
                                   auth_cookie=git_util.GetGerritAuthCookie(),
                                   include_comment_thread=True,
                                   include_mergeable=True,
                                   include_review_status=True)
      kwargs = cl_info._asdict()
      kwargs['comment_threads'] = list(
          filter(lambda t: t.path, kwargs['comment_threads']))
      return HWIDDBCLInfo(**kwargs)
    except git_util.GitUtilException as ex:
      raise HWIDRepoError from ex

  def GetMainCommitID(self):
    """Fetches the latest commit ID of the main branch on the upstream."""
    return git_util.GetCommitId(INTERNAL_REPO_REVIEW_URL,
                                _CHROMEOS_HWID_PROJECT,
                                auth_cookie=git_util.GetGerritAuthCookie())

  def GetGerritCLHWIDRepo(self, cl_number: int) -> GerritCLHWIDRepo:
    return GerritCLHWIDRepo(self._repo_branch, cl_number)

  def GetGerritToTHWIDRepo(self) -> GerritToTHWIDRepo:
    return GerritToTHWIDRepo(self._repo_branch)

  def AbandonCL(self, cl_number: int, reason=None):
    """Abandons the given CL number."""
    return git_util.AbandonCL(INTERNAL_REPO_REVIEW_URL,
                              git_util.GetGerritAuthCookie(), cl_number,
                              reason=reason)

  def RebaseCLMetadata(self, cl_info: HWIDDBCLInfo):
    """Rebases `projects.yaml` and try to resolve merge conflict for the CL."""
    conflicts = git_util.RebaseCL(INTERNAL_REPO_REVIEW_URL,
                                  str(cl_info.cl_number),
                                  git_util.GetGerritAuthCookie())

    if not conflicts:
      return

    if conflicts != [_PROJECTS_YAML_PATH]:
      raise HWIDRepoError(
          f'Only {_PROJECTS_YAML_PATH} can be auto rebased: {conflicts}')

    # Find project name from CL subject and append the new metadata to tot.
    matches = re.search(r'(?:\(\d+\)\s*)?([A-Z0-9]+):', cl_info.subject)
    if not matches:
      raise ValueError('Unable to find project name from commit message.')

    project = matches.group(1)

    metadata = self.GetGerritToTHWIDRepo().hwid_db_metadata_of_name
    cl_metadata = self.GetGerritCLHWIDRepo(
        cl_info.cl_number).hwid_db_metadata_of_name
    metadata[project] = cl_metadata[project]

    # Force rebase and patch metadata when merge conflict on project.yaml.
    git_util.RebaseCL(INTERNAL_REPO_REVIEW_URL, str(cl_info.cl_number),
                      git_util.GetGerritAuthCookie(), force=True)
    git_util.PatchCL(INTERNAL_REPO_REVIEW_URL, str(cl_info.cl_number),
                     _PROJECTS_YAML_PATH,
                     _DumpMetadata(metadata).encode(),
                     git_util.GetGerritAuthCookie())
    git_util.ReviewCL(
        INTERNAL_REPO_REVIEW_URL, git_util.GetGerritAuthCookie(),
        cl_number=cl_info.cl_number, reasons=[
            f'Auto resolved merge conflict for {_PROJECTS_YAML_PATH}'
        ], approval_case=git_util.ApprovalCase.APPROVED)
