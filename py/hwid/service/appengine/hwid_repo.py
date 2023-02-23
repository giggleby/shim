# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provide functionalities to access the HWID DB repository."""

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


class RepoFileContents(NamedTuple):
  commit_id: str
  file_contents: Sequence[str]


INTERNAL_REPO_REVIEW_URL = 'https://chrome-internal-review.googlesource.com'
INTERNAL_REPO_URL = 'https://chrome-internal.googlesource.com'
_CHROMEOS_HWID_PROJECT = 'chromeos/chromeos-hwid'
_PROJECTS_YAML_PATH = 'projects.yaml'


def _ParseMetadata(raw_metadata):
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


class HWIDRepo:

  INTERNAL_DB_NAME_SUFFIX = '.internal'

  def __init__(self, repo, repo_url, repo_branch):
    """Constructor.

    Args:
      repo: The local cloned git repo.
      repo_url: URL of the HWID repo.
      repo_branch: Branch name to track in the HWID repo.
    """
    self._repo = repo
    self._repo_url = repo_url
    self._repo_branch = repo_branch

    self._git_fs = git_util.GitFilesystemAdapter(self._repo)

  def ListHWIDDBMetadata(self):
    """Returns a list of metadata of HWID DBs recorded in the HWID repo."""
    return list(self._hwid_db_metadata_of_name.values())

  def GetHWIDDBMetadataByName(self, name):
    """Returns the metadata of the specific HWID DB in the HWID repo."""
    try:
      return self._hwid_db_metadata_of_name[name]
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None

  @property
  def hwid_db_commit_id(self) -> str:
    return self._repo.head().decode()

  def LoadHWIDDBByName(self, name: str, internal: bool = False):
    """Reads out the specific HWID DB content.

    Args:
      name: The project name of the HWID DB.  One can get the available names
          from the HWIDDBMetadata instances.

    Returns:
      A string of HWID DB content.

    Raises:
      ValueError if the given HWID DB name is invalid.
      HWIDRepoError for other unexpected errors.
    """
    try:
      path = self._hwid_db_metadata_of_name[name].path
      if internal:
        path = self.InternalDBPath(path)
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None
    try:
      return self._git_fs.ReadFile(path).decode('utf-8')
    except (KeyError, ValueError,
            filesystem_adapter.FileSystemAdapterException) as ex:
      raise HWIDRepoError(
          f'failed to load the HWID DB (name={name}): {ex}') from None

  def CommitHWIDDB(self, name: str, hwid_db_contents: str, commit_msg: str,
                   reviewers: Sequence[str], cc_list: Sequence[str],
                   bot_commit: bool = False, commit_queue: bool = False,
                   update_metadata: Optional[HWIDDBMetadata] = None,
                   hwid_db_contents_internal: Optional[str] = None):
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

    Returns:
      A numeric ID of the created CL.

    Raises:
      ValueError if the given HWID DB name is invalid.
      git_util.GitUtilNoModificationException if no modification is made.
      HWIDRepoError for other unexpected errors.
    """
    new_files = []
    if update_metadata:
      self._hwid_db_metadata_of_name[name] = update_metadata
      new_raw_metadata = _DumpMetadata(self._hwid_db_metadata_of_name)
      new_files.append((_PROJECTS_YAML_PATH, git_util.NORMAL_FILE_MODE,
                        new_raw_metadata.encode('utf-8')))
    try:
      path = self._hwid_db_metadata_of_name[name].path
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None
    hwid_db_contents = _RemoveChecksum(hwid_db_contents)
    new_files.append(
        (path, git_util.NORMAL_FILE_MODE, hwid_db_contents.encode('utf-8')))

    if not hwid_db_contents_internal:
      hwid_db_contents_internal = hwid_db_contents

    internal_path = self.InternalDBPath(path)
    hwid_db_contents_internal = _RemoveChecksum(hwid_db_contents_internal)
    new_files.append((internal_path, git_util.NORMAL_FILE_MODE,
                      hwid_db_contents_internal.encode('utf-8')))

    try:
      author_email, unused_token = git_util.GetGerritCredentials()
      author = f'chromeoshwid <{author_email}>'
      change_id, cl_number = git_util.CreateCL(
          git_url=self._repo_url, auth_cookie=git_util.GetGerritAuthCookie(),
          branch=self._repo_branch, new_files=new_files, author=author,
          committer=author, commit_msg=commit_msg, reviewers=reviewers,
          cc=cc_list, bot_commit=bot_commit, commit_queue=commit_queue,
          repo=self._repo)
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

  @type_utils.LazyProperty
  def _hwid_db_metadata_of_name(self):
    try:
      raw_metadata = self._git_fs.ReadFile(_PROJECTS_YAML_PATH)
    except (KeyError, ValueError,
            filesystem_adapter.FileSystemAdapterException) as ex:
      raise HWIDRepoError(
          f'failed to load {_PROJECTS_YAML_PATH}: {ex}') from None
    try:
      return _ParseMetadata(raw_metadata)
    except Exception as ex:
      raise HWIDRepoError(f'invalid {_PROJECTS_YAML_PATH}: {ex}') from None

  @classmethod
  def InternalDBPath(cls, path):
    return f'{path}{cls.INTERNAL_DB_NAME_SUFFIX}'


HWIDDBCLInfo = git_util.CLInfo
HWIDDBCLStatus = git_util.CLStatus
HWIDDBCLReviewStatus = git_util.CLReviewStatus
HWIDDBCLCommentThread = git_util.CLCommentThread
HWIDDBCLComment = git_util.CLComment


class HWIDRepoManager:

  def __init__(self, repo_branch):
    """Constructor.

    Args:
      repo_branch: The git branch name of the HWID repo to access.  Assigning
          `None` to use the default "main" branch.
    """
    self._repo_branch = repo_branch

  def GetLiveHWIDRepo(self):
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
    return HWIDRepo(repo, repo_url, repo_branch)

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

  def GetHWIDDBMetadataByProject(self, project: str) -> HWIDDBMetadata:
    """Gets the metadata from HWID repo tot by project name."""
    metadata = self.GetHWIDDBMetadata()
    if project not in metadata:
      raise KeyError(f'Project: "{project}" does not exist in the repo.')
    return metadata[project]

  def GetHWIDDBMetadata(
      self, cl_number: Optional[int] = None) -> Mapping[str, HWIDDBMetadata]:
    """Gets the metadata from HWID repo."""
    repo_file_contents = self.GetRepoFileContents([_PROJECTS_YAML_PATH],
                                                  cl_number)
    return _ParseMetadata(repo_file_contents.file_contents[0])

  def GetRepoFileContents(self, paths: Sequence[str],
                          cl_number: Optional[int] = None) -> RepoFileContents:
    """Gets the file content as well as the commit id from HWID repo."""
    commit_id = None
    if cl_number is None:
      commit_id = git_util.GetCommitId(
          INTERNAL_REPO_REVIEW_URL, _CHROMEOS_HWID_PROJECT,
          branch=self._repo_branch, auth_cookie=git_util.GetGerritAuthCookie())

    file_contents = [
        git_util.GetFileContent(
            INTERNAL_REPO_REVIEW_URL, _CHROMEOS_HWID_PROJECT, path,
            commit_id=commit_id, change_id=str(cl_number),
            auth_cookie=git_util.GetGerritAuthCookie()).decode()
        for path in paths
    ]
    return RepoFileContents(commit_id, file_contents)

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

    metadata = self.GetHWIDDBMetadata()
    cl_metadata = self.GetHWIDDBMetadata(cl_number=cl_info.cl_number)
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
