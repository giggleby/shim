# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provide functionalities to access the HWID DB repository."""

from typing import NamedTuple

import yaml

from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import type_utils


class HWIDDBMetadata(NamedTuple):
  """A placeholder for metadata of a HWID DB."""
  name: str
  board_name: str
  version: int
  path: str


_INTERNAL_REPO_URL = 'https://chrome-internal-review.googlesource.com'
_CHROMEOS_HWID_PROJECT = 'chromeos/chromeos-hwid'
_PROJECTS_YAML_PATH = 'projects.yaml'


def _ParseMetadata(raw_metadata):
  metadata_yaml = yaml.safe_load(raw_metadata)
  hwid_db_metadata_of_name = {}
  for name, hwid_db_info in metadata_yaml.items():
    hwid_db_metadata_of_name[name] = HWIDDBMetadata(name, hwid_db_info['board'],
                                                    hwid_db_info['version'],
                                                    hwid_db_info['path'])
  return hwid_db_metadata_of_name


class HWIDRepoError(Exception):
  """Root exception class for reporting unexpected error in HWID repo."""


class HWIDRepo:
  _AVL_NAME_MAPPING_FOLDER = 'avl_name_mapping'

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

  def IterAVLNameMappings(self):
    """Iterate through the AVL name mappings recorded in the HWID repo.

    Yields:
      A tuple of (mapping file name, mapping file content).

    Raises:
      HWIDRepoError
    """
    try:
      for name in self._git_fs.ListFiles(self._AVL_NAME_MAPPING_FOLDER):
        content = self._git_fs.ReadFile(
            f'{self._AVL_NAME_MAPPING_FOLDER}/{name}').decode('utf-8')
        yield name, content
    except (KeyError, ValueError,
            filesystem_adapter.FileSystemAdapterException) as ex:
      raise HWIDRepoError(
          f'unable to retrive AVL name mappings: {ex}') from None

  def ListHWIDDBMetadata(self):
    """Returns a list of metadata of HWID DBs recorded in the HWID repo."""
    return list(self._hwid_db_metadata_of_name.values())

  def GetHWIDDBMetadataByName(self, name):
    """Returns the metadata of the specific HWID DB in the HWID repo."""
    name = name.upper()
    try:
      return self._hwid_db_metadata_of_name[name]
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None

  def LoadHWIDDBByName(self, name):
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
    name = name.upper()
    try:
      path = self._hwid_db_metadata_of_name[name].path
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None
    try:
      return self._git_fs.ReadFile(path).decode('utf-8')
    except (KeyError, ValueError,
            filesystem_adapter.FileSystemAdapterException) as ex:
      raise HWIDRepoError(
          f'failed to load the HWID DB (name={name}): {ex}') from None

  def CommitHWIDDB(self, name, hwid_db_contents, commit_msg, reviewers, cc_list,
                   auto_approved):
    """Commit an HWID DB to the repo.

    Args:
      name: The project name of the HWID DB.
      hwid_db_contents: The contents of the HWID DB.
      commit_msg: The commit message.
      author: Author in form of "Name <email@domain>".
      reviewers: List of emails of reviewers.
      cc_list: List of emails of CC's.
      auto_approved: A bool indicating if this CL should be auto-approved.

    Returns:
      A numeric ID of the created CL.

    Raises:
      ValueError if the given HWID DB name is invalid.
      HWIDRepoError for other unexpected errors.
    """
    name = name.upper()
    try:
      path = self._hwid_db_metadata_of_name[name].path
    except KeyError:
      raise ValueError(f'invalid HWID DB name: {name}') from None
    new_files = [
        (path, git_util.NORMAL_FILE_MODE, hwid_db_contents.encode('utf-8')),
    ]
    try:
      author_email, unused_token = git_util.GetGerritCredentials()
      author = f'chromeoshwid <{author_email}>'
      change_id = git_util.CreateCL(
          self._repo_url, git_util.GetGerritAuthCookie(), self._repo_branch,
          new_files, author, author, commit_msg, reviewers=reviewers,
          cc=cc_list, auto_approved=auto_approved, repo=self._repo)
      cl_info = git_util.GetCLInfo(_INTERNAL_REPO_URL, change_id,
                                   auth_cookie=git_util.GetGerritAuthCookie())
    except git_util.GitUtilException as ex:
      raise HWIDRepoError from ex
    return cl_info.cl_number

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


HWIDDBCLInfo = git_util.CLInfo
HWIDDBCLStatus = git_util.CLStatus
HWIDDBCLMessage = git_util.CLMessage


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
      repo_branch = git_util.GetCurrentBranch(_INTERNAL_REPO_URL,
                                              _CHROMEOS_HWID_PROJECT,
                                              git_util.GetGerritAuthCookie())
    else:
      repo_branch = self._repo_branch
    repo_url = f'{_INTERNAL_REPO_URL}/{_CHROMEOS_HWID_PROJECT}'
    repo = git_util.MemoryRepo(git_util.GetGerritAuthCookie())
    repo.shallow_clone(repo_url, repo_branch)
    return HWIDRepo(repo, repo_url, repo_branch)

  def GetHWIDDBCLInfo(self, cl_number) -> HWIDDBCLInfo:
    try:
      return git_util.GetCLInfo(_INTERNAL_REPO_URL, cl_number,
                                auth_cookie=git_util.GetGerritAuthCookie(),
                                include_detailed_accounts=True,
                                include_messages=True, include_mergeable=True)
    except git_util.GitUtilException as ex:
      raise HWIDRepoError from ex

  def GetMainCommitID(self):
    """Fetches the latest commit ID of the main branch on the upstream."""
    return git_util.GetCommitId(_INTERNAL_REPO_URL, _CHROMEOS_HWID_PROJECT,
                                auth_cookie=git_util.GetGerritAuthCookie())

  def GetHWIDDBMetadata(self, project: str) -> HWIDDBMetadata:
    """Gets the metadata from HWID repo."""
    project = project.upper()
    metadata = _ParseMetadata(self.GetFileContent(_PROJECTS_YAML_PATH))
    if project not in metadata:
      raise KeyError(f'Project: "{project}" does not exist in the repo.')
    return metadata[project]

  def GetFileContent(self, path: str) -> str:
    """Gets the file content from HWID repo."""
    return git_util.GetFileContent(
        _INTERNAL_REPO_URL, _CHROMEOS_HWID_PROJECT, path, self._repo_branch,
        auth_cookie=git_util.GetGerritAuthCookie()).decode()

  def AbandonCL(self, cl_number: int, reason=None):
    """Abandons the given CL number."""
    return git_util.AbandonCL(_INTERNAL_REPO_URL,
                              git_util.GetGerritAuthCookie(), cl_number,
                              reason=reason)
