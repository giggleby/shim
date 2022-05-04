# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from typing import Optional, Sequence, Set

from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_v2_action
from cros.factory.hwid.service.appengine import hwid_v3_action
from cros.factory.hwid.service.appengine import memcache_adapter

# Shorter identifiers to type definition.
_HWIDDBData = hwid_db_data.HWIDDBData
_HWIDDBMetadata = hwid_db_data.HWIDDBMetadata
_HWIDPreprocData = hwid_preproc_data.HWIDPreprocData


class ProjectNotFoundError(KeyError):
  """Indicates that the specified project was not found."""


class ProjectNotSupportedError(ValueError):
  """Indicates the HWID DB version of the specified project is not supported."""


class ProjectUnavailableError(RuntimeError):
  """Indicates that the specified project has unexpected malformed HWID data."""


class InstanceFactory:

  def CreateHWIDPreprocData(
      self, metadata: _HWIDDBMetadata, raw_db: _HWIDDBData,
      raw_db_internal: Optional[_HWIDDBData] = None) -> _HWIDPreprocData:
    """Creates the correct instance of `HWIDPreprocData` for the given DB info.

    Args:
      metadata: The HWID DB metadata instance that includes the version info.
      raw_db: The raw string of the HWID DB contents.

    Returns:
      An instance of `hwid_preproc_data.HWIDPreprocData`.

    Raises:
      hwid_preproc_data.PreprocHWIDError: If an error occurs while preprocessing
          the given HWID DB.
      ProjectNotSupportedError: If the HWID DB version is not supported.
    """
    raise NotImplementedError

  def CreateHWIDAction(self, hwid_data: _HWIDDBData) -> hwid_action.HWIDAction:
    """Creates the correct instance of `HWIDAction` for the given DB data.

    Args:
      hwid_data: The `hwid_preproc_data.HWIDPreprocData` instance that
          holds the preprocessed data of the target HWID DB.

    Returns:
      An instance of `hwid_action.HWIDAction` that provides functionalities to
      use the underlying HWID DB.

    Raises:
      ProjectUnavailableError: If the HWID DB version is not supported.
    """
    raise NotImplementedError


class InstanceFactoryImpl(InstanceFactory):

  def CreateHWIDPreprocData(
      self, metadata: _HWIDDBMetadata, raw_db: _HWIDDBData,
      raw_db_internal: Optional[_HWIDDBData] = None) -> _HWIDPreprocData:
    if metadata.version == '2':
      logging.debug('Processing as version 2 file.')
      return hwid_preproc_data.HWIDV2PreprocData(metadata.project, raw_db)

    if metadata.version == '3':
      logging.debug('Processing as version 3 file.')
      return hwid_preproc_data.HWIDV3PreprocData(
          metadata.project, raw_db, raw_db_internal, metadata.commit)

    raise ProjectNotSupportedError(
        f'Project {metadata.project!r} has invalid version '
        f'{metadata.version!r}.')

  def CreateHWIDAction(self, hwid_data: _HWIDPreprocData):
    if isinstance(hwid_data, hwid_preproc_data.HWIDV2PreprocData):
      return hwid_v2_action.HWIDV2Action(hwid_data)

    if isinstance(hwid_data, hwid_preproc_data.HWIDV3PreprocData):
      return hwid_v3_action.HWIDV3Action(hwid_data)

    raise ProjectUnavailableError(
        f'unexpected HWID version: {hwid_data.__class__.__name__}')


class HWIDActionManager:
  """The canonical portal to get HWID action instances for given projects."""

  def __init__(self, hwid_db_data_manager: hwid_db_data.HWIDDBDataManager,
               mem_adapter: memcache_adapter.MemcacheAdapter,
               instance_factory: Optional[InstanceFactory] = None):
    self._hwid_db_data_manager = hwid_db_data_manager
    self._memcache_adapter = mem_adapter
    self._instance_factory = instance_factory or InstanceFactoryImpl()

  def GetHWIDAction(self, project: str) -> hwid_action.HWIDAction:
    """Retrieves the HWID action for a given project, caching as necessary.

    Args:
      project: The project to get for.

    Returns:
      A HWIDAction object for the project.

    Raises:
      ProjectNotFoundError: If the given project is unknown.
      ProjectNotSupportedError: If HWID DB version is not supported.
      ProjectUnavailableError: The given project is known, but it encounters
        an error while loading the project's HWID DB.
    """
    logging.debug('Loading data for %r.', project)
    project = _NormalizeProjectString(project)

    hwid_preproc_data_inst = self._GetHWIDPreprocDataFromCache(project)
    if hwid_preproc_data_inst:
      logging.debug('Found cached data for %r.', project)
    else:
      try:
        metadata = self._hwid_db_data_manager.GetHWIDDBMetadataOfProject(
            project)
        hwid_preproc_data_inst = self._LoadHWIDPreprocData(metadata)
      except hwid_db_data.HWIDDBNotFoundError as ex:
        raise ProjectNotFoundError(str(ex)) from ex
      except hwid_db_data.TooManyHWIDDBError as ex:
        raise ProjectUnavailableError(str(ex)) from ex
      self._SaveHWIDPreprocDataToCache(project, hwid_preproc_data_inst)

    return self._instance_factory.CreateHWIDAction(hwid_preproc_data_inst)

  def _LoadHWIDPreprocData(self, metadata: _HWIDDBMetadata) -> _HWIDPreprocData:
    """Load preprocessed HWID DB from the backend datastore.

    Args:
      metadata: A `hwid_db_data.HWIDDBMetadata` object.

    Returns:
      The hwid_preproc_data.HWIDPreprocData object loaded based on the metadata.

    Raises:
      ProjectUnavailableError: The HWID DB data to load doesn't exist or error
        occurs while loading it.
      ProjectNotSupportedError: If HWID DB version is not supported.
    """
    try:
      raw_hwid_yaml = self._hwid_db_data_manager.LoadHWIDDB(metadata)
    except hwid_db_data.HWIDDBNotFoundError as ex:
      raise ProjectUnavailableError(str(ex)) from ex

    try:
      raw_hwid_yaml_internal = self._hwid_db_data_manager.LoadHWIDDB(
          metadata, internal=True)
    except hwid_db_data.HWIDDBNotFoundError as ex:
      raise ProjectUnavailableError(str(ex)) from ex

    try:
      return self._instance_factory.CreateHWIDPreprocData(
          metadata, raw_hwid_yaml, raw_hwid_yaml_internal)
    except hwid_preproc_data.PreprocHWIDError as ex:
      raise ProjectUnavailableError(str(ex)) from ex

  def ReloadMemcacheCacheFromFiles(
      self, limit_models: Optional[Sequence[str]] = None):
    """For every known project, load its info into the cache.

    Args:
      limit_models: List of names of models which will be updated.
    """
    if limit_models is not None:
      limit_models = [_NormalizeProjectString(m) for m in limit_models]
    metadata_list = self._hwid_db_data_manager.ListHWIDDBMetadata(
        projects=limit_models)
    for metadata in metadata_list:
      try:
        self._SaveHWIDPreprocDataToCache(metadata.project,
                                         self._LoadHWIDPreprocData(metadata))
      except Exception:  # pylint: disable=broad-except
        # Catch any exception and continue with other files.  The reason for
        # the broad exception is that the various exceptions we could catch
        # are large and from libraries out of our control.  For example, the
        # HWIDv3 library can throw various unknown errors.  We could have IO
        # errors, errors with Google Cloud Storage, or YAML parsing errors.
        #
        # This may catch some exceptions we do not wish it to, such as SIGINT,
        # but we expect that to be unlikely in this context and not adversely
        # affect the system.
        logging.exception('Exception encountered while reloading cache for %r.',
                          metadata.project)

  def _ClearMemcache(self):
    """Clear all cache items via memcache_adapter.

    This method is for testing purpose since each integration test should have
    empty cache in the beginning.
    """
    self._memcache_adapter.ClearAll()

  def _GetHWIDPreprocDataFromCache(self, project: str) -> _HWIDPreprocData:
    """Get the HWID file data from memcache.

    Args:
      project: String, the name of the project to retrieve from cache.

    Returns:
       HWIDPreprocData object that was cached or null if not found in the
       memcache.
    """
    try:
      hwid_preproc_data_inst = self._memcache_adapter.Get(project)
    except Exception as ex:
      logging.debug('Memcache read miss %s: caught exception: %s.', project, ex)
      return None
    if not hwid_preproc_data_inst:
      logging.info('Memcache read miss %s.', project)
      return None
    if (not isinstance(hwid_preproc_data_inst, _HWIDPreprocData) or
        hwid_preproc_data_inst.is_out_of_date):
      logging.info('Memcache read miss %s: got legacy cache value.', project)
      return None
    return hwid_preproc_data_inst

  def _SaveHWIDPreprocDataToCache(self, project: str,
                                  hwid_preproc_data_inst: _HWIDPreprocData):
    self._memcache_adapter.Put(project, hwid_preproc_data_inst)

  def ListProjects(self) -> Set[str]:
    """Lists all available projects in a set."""
    metadata_list = self._hwid_db_data_manager.ListHWIDDBMetadata()
    return {m.project
            for m in metadata_list}


def _NormalizeProjectString(string: str) -> Optional[str]:
  """Normalizes a string to account for things like case."""
  return string.strip().upper() if string else None
