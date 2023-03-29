# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Functionalities to access / update the HWID DBs in the datastore."""

from concurrent import futures
import logging
from typing import Mapping, Optional, Sequence

from google.cloud import ndb

from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import filesystem_adapter


class HWIDDBMetadata(ndb.Model):
  """Metadata about HWID projects and information.

  This tracks the information about HWID file for a given project.  It is unique
  per path, as each file is assumed to apply to only one project (the same file
  can be uploaded multiple times, but will be uploaded as separate files).  The
  path thus acts as the unique key.
  """

  board = ndb.StringProperty()
  path = ndb.StringProperty()
  version = ndb.StringProperty()
  project = ndb.StringProperty()
  commit = ndb.StringProperty()

  @classmethod
  def _get_kind(cls):
    return 'HwidMetadata'

  def has_internal_format(self) -> bool:
    return self.version == '3'


# In the datastore, we store the raw HWID DB payload in string.
HWIDDBData = str


class HWIDDBNotFoundError(Exception):
  """Indicates that the specified project was not found."""


class TooManyHWIDDBError(Exception):
  """There is more than one entry for a particular project in datastore."""


class HWIDDBDataManager:

  def __init__(self, ndb_connector: ndbc_module.NDBConnector,
               fs_adapter: filesystem_adapter.FileSystemAdapter):
    self._ndb_connector = ndb_connector
    self._fs_adapter = fs_adapter

  def ListHWIDDBMetadata(
      self, versions: Optional[Sequence[str]] = None,
      projects: Optional[Sequence[str]] = None) -> Sequence[HWIDDBMetadata]:
    """Get a list of supported projects.

    Args:
      versions: List of HWID DB versions to include.  `None` if no limitation.
      projects: List of HWID projects to include.  `None` if no limitation.

    Returns:
      A list of projects.
    """
    logging.debug('Getting projects for versions: %s',
                  versions if versions is not None else '(all)')
    if versions == [] or projects == []:
      return []
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = HWIDDBMetadata.query()
      if versions is not None:
        q = q.filter(HWIDDBMetadata.version.IN(versions))
      if projects is not None:
        q = q.filter(HWIDDBMetadata.project.IN(projects))
      return list(q)

  def GetHWIDDBMetadataOfProject(self, project: str) -> HWIDDBMetadata:
    """Get the metadata of the specific project.

    Args:
      project: The name of the project.

    Returns:
      An HWIDDBMetadata instance.

    Raises:
      HWIDDBNotFoundError: If no metadata is found for the given
          project.
      TooManyHWIDDBError: If we have more than one metadata entry
          for the given project.
    """
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = HWIDDBMetadata.query(HWIDDBMetadata.project == project)
      if q.count() == 0:
        raise HWIDDBNotFoundError(
            f'no metadata present for the requested project: {project}')
      if q.count() != 1:
        raise TooManyHWIDDBError(f'too many projects present for {project!r}')
      return q.get()

  def LoadHWIDDB(self, metadata: HWIDDBMetadata,
                 internal: bool = False) -> HWIDDBData:
    """Load HWID DB data from a file.

    Args:
      metadata: The HWIDDBMetadata object of the target HWID DB.
      internal: True if internal format is required.

    Returns:
      The raw HWID DB payload in string.

    Raises:
      HWIDDBNotFoundError: If the metadata references an invalid path or
          invalid version.
    """
    try:
      logging.debug('Reading file of project %s%s from live path.',
                    metadata.project, '(internal)' if internal else '')
      path = self._LivePath(metadata.path, internal=internal)
      raw_hwid_yaml = self._fs_adapter.ReadFile(path)
    except Exception as e:
      logging.exception('Missing HWID file: %r', path)
      raise HWIDDBNotFoundError(
          f'HWID file missing for the requested project: {e!r}') from None
    return raw_hwid_yaml

  def _CreateHWIDDBMetadata(self, repo_metadata: hwid_repo.HWIDDBMetadata,
                            commit_id: str) -> HWIDDBMetadata:
    path = repo_metadata.name  # Use the project name as the file path.
    return HWIDDBMetadata(board=repo_metadata.board_name, version=str(
        repo_metadata.version), path=path, project=repo_metadata.name,
                          commit=commit_id)

  def UpdateProjectContent(self,
                           gerrit_cl_hwid_repo: hwid_repo.GerritCLHWIDRepo,
                           repo_metadata: hwid_repo.HWIDDBMetadata):
    """Updates HWID DB content

    Args:
      gerrit_cl_hwid_repo: The HWID repo view of a specific Gerrit CL.
      repo_metadata: HWID DB metadata.
    """
    try:
      metadata = self.GetHWIDDBMetadataOfProject(repo_metadata.name)
      metadata.commit = gerrit_cl_hwid_repo.commit_id
    except HWIDDBNotFoundError:
      metadata = self._CreateHWIDDBMetadata(repo_metadata,
                                            gerrit_cl_hwid_repo.commit_id)
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      metadata.put()
    file_changes = self._LoadProjectFiles(gerrit_cl_hwid_repo, metadata)
    for file_path, file_contents in file_changes.items():
      self._fs_adapter.WriteFile(file_path, file_contents)

  def UpdateProjectsByRepo(
      self, live_hwid_repo: hwid_repo.HWIDRepo,
      hwid_db_metadata_list: Sequence[hwid_repo.HWIDDBMetadata],
      delete_missing=True):
    """Updates project contents with a live repo.

    Updates the set of supported projects to be exactly the list provided with
    a live HWID repo.

    Args:
      live_hwid_repo: A HWIDRepo instance that provides access to chromeos-hwid
          repo.
      hwid_db_metadata_list: A list of hwid_repo.HWIDDBMetadata containing path,
          version and name.
      delete_missing: bool to indicate whether missing metadata should be
          deleted.
    """
    hwid_db_metadata_of_name = {m.name: m
                                for m in hwid_db_metadata_list}
    hwid_db_commit_id = live_hwid_repo.hwid_db_commit_id
    metadata_to_update = []

    # Discard the names for the entries, indexing only by path.
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = HWIDDBMetadata.query()
      existing_metadata = list(q)
      old_files = set(m.project for m in existing_metadata)
      new_files = set(hwid_db_metadata_of_name)

      files_to_delete = old_files - new_files
      files_to_create = new_files - old_files

      for hwid_metadata in existing_metadata:
        if hwid_metadata.project in files_to_delete:
          if delete_missing:
            hwid_metadata.key.delete()
            self._fs_adapter.DeleteFile(self._LivePath(hwid_metadata.path))
            if hwid_metadata.has_internal_format():
              self._fs_adapter.DeleteFile(
                  self._LivePath(hwid_metadata.path, internal=True))
        else:
          new_data = hwid_db_metadata_of_name[hwid_metadata.project]
          hwid_metadata.version = str(new_data.version)
          hwid_metadata.board = new_data.board_name
          hwid_metadata.commit = hwid_db_commit_id
          metadata_to_update.append(hwid_metadata)

    for project in files_to_create:
      new_data = hwid_db_metadata_of_name[project]
      with self._ndb_connector.CreateClientContextWithGlobalCache():
        metadata = self._CreateHWIDDBMetadata(new_data, hwid_db_commit_id)
        metadata_to_update.append(metadata)

    self._ActivateProjectFiles(live_hwid_repo, metadata_to_update)

  def RegisterProjectForTest(self, board: str, project: str, version: str,
                             hwid_db: Optional[HWIDDBData],
                             commit_id: str = 'TEST-COMMIT-ID',
                             hwid_db_internal: Optional[HWIDDBData] = None):
    """Append a HWID data into the datastore.

    Args:
      board: The board name.
      project: The project name.
      version: The HWID version.
      hwid_db: The HWID DB contents in string.
      commit_id: The commit id of the HWID DB.
      hwid_db_internal: The internal HWID DB contents in string.
    """
    try:
      metadata = self.GetHWIDDBMetadataOfProject(project)
    except HWIDDBNotFoundError:
      with self._ndb_connector.CreateClientContextWithGlobalCache():
        metadata = HWIDDBMetadata(board=board, project=project, version=version,
                                  path=project, commit=commit_id)
        metadata.put()
    else:
      with self._ndb_connector.CreateClientContextWithGlobalCache():
        metadata.board = board
        metadata.version = version
        metadata.put()
    if hwid_db is not None:
      self._fs_adapter.WriteFile(self._LivePath(metadata.path), hwid_db)
      if hwid_db_internal is None:
        hwid_db_internal = hwid_db
      self._fs_adapter.WriteFile(
          self._LivePath(metadata.path, internal=True), hwid_db_internal)

  def CleanAllForTest(self):
    with self._ndb_connector.CreateClientContext():
      for key in HWIDDBMetadata.query().iter(keys_only=True):
        self._fs_adapter.DeleteFile(self._LivePath(key.get().path))
        self._fs_adapter.DeleteFile(
            self._LivePath(key.get().path, internal=True))
        key.delete()

  def _LivePath(self, file_id: str, internal: bool = False):
    path = f'live/{file_id}'
    if internal:
      return f'{path}.internal'
    return path

  def _LoadProjectFiles(self, hwid_repo_view: hwid_repo.HWIDRepoView,
                        hwid_metadata: HWIDDBMetadata) -> Mapping[str, str]:
    hwid_db_name = hwid_metadata.project
    live_file_id = hwid_metadata.path
    if hwid_metadata.version == '2':
      project_data = hwid_repo_view.LoadV2HWIDDBByName(hwid_db_name)
      return {
          self._LivePath(live_file_id): project_data
      }
    if hwid_metadata.version == '3':
      project_data = hwid_repo_view.LoadV3HWIDDBByName(hwid_db_name)
      return {
          self._LivePath(live_file_id): project_data.external_db,
          self._LivePath(live_file_id, internal=True): project_data.internal_db,
      }
    raise AssertionError('Unexpected call path.')

  def _ActivateProjectFiles(self, hwid_repo_view: hwid_repo.HWIDRepoView,
                            hwid_metadata_list: Sequence[HWIDDBMetadata]):
    with self._ndb_connector.CreateClientContextWithGlobalCache(), \
        futures.ThreadPoolExecutor() as executor:
      for hwid_metadata in hwid_metadata_list:
        file_changes = self._LoadProjectFiles(hwid_repo_view, hwid_metadata)
        for file_path, file_contents in file_changes.items():
          executor.submit(self._fs_adapter.WriteFile, file_path, file_contents)
      ndb.model.put_multi(hwid_metadata_list)
