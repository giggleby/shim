# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Classes for managing and querying HWID information.

This module should provide a unified interface for querying HWID information
regardless of the source of that information or the version.
"""

import logging
from typing import Dict, List, NamedTuple, Optional

from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_v2_action
from cros.factory.hwid.service.appengine import hwid_v3_action
from cros.factory.hwid.service.appengine import memcache_adapter


class ProjectNotFoundError(KeyError):
  """Indicates that the specified project was not found."""


class ProjectNotSupportedError(ValueError):
  """Indicates the HWID DB version of the specified project is not supported."""


class ProjectUnavailableError(Exception):
  """Indicates that the specified project has unexpected malformed HWID data."""


HWIDDecodeError = hwid_action.HWIDDecodeError
InvalidHWIDError = hwid_action.InvalidHWIDError
MethodNotSupportedError = hwid_action.NotSupportedError


class BomAndConfigless(NamedTuple):
  """A class to collect bom and configless obtained from HwidData."""

  bom: Optional[Dict]
  configless: Optional[Dict]
  error: Optional[Exception]


Component = hwid_action.Component
Label = hwid_action.Label
BOM = hwid_action.BOM


class HwidManager:
  """The HWID Manager class itself.

  This is the class that should be instantiated elsewhere to query HWID
  information.
  """

  def __init__(self, vpg_targets, hwid_db_data_manager, mem_adapter=None):
    self._vpg_targets = vpg_targets
    self._hwid_db_data_manager = hwid_db_data_manager
    if mem_adapter is not None:
      self._memcache_adapter = mem_adapter
    else:
      self._memcache_adapter = memcache_adapter.MemcacheAdapter(
          namespace='HWIDObject')

  def GetProjects(self, versions: Optional[List[str]] = None) -> List[str]:
    """Get a list of supported projects.

    Args:
      versions: List of BOM file versions to include.

    Returns:
      A list of projects.
    """
    metadata_list = self._hwid_db_data_manager.ListHWIDDBMetadata(
        versions=versions)
    return [m.project for m in metadata_list]

  def BatchGetBomAndConfigless(
      self, hwid_strings, verbose=False,
      require_vp_info=False) -> Dict[str, BomAndConfigless]:
    """Get the BOM and configless for a given HWID.

    Args:
      hwid_strings: list of HWID strings.
      verbose: Requires all fields of components in bom if set to True.
      require_vp_info: A bool to indicate if the is_vp_related field of
          each component is required.

    Returns:
      A dict of {hwid: BomAndConfigless instance} where the BomAndConfigless
      instance stores an optional bom dict and an optional configless field
      dict.  If an exception occurs while decoding the HWID string, the
      exception will also be provided in the instance.
    """

    action_cache = {}
    result = {}
    for hwid_string in hwid_strings:
      logging.debug('Getting BOM for %r.', hwid_string)
      project_and_brand, unused_sep, unused_part = hwid_string.partition(' ')
      project, unused_sep, unused_part = project_and_brand.partition('-')

      model_info = self._vpg_targets.get(project)
      waived_comp_categories = model_info and model_info.waived_comp_categories

      bom = configless = error = None
      action = action_cache.get(project)
      try:
        if action is None:
          action_cache[project] = action = self._GetHWIDAction(project)

        bom, configless = action.GetBOMAndConfigless(
            hwid_string, verbose, waived_comp_categories, require_vp_info)
      except (ProjectUnavailableError, ValueError, KeyError,
              MethodNotSupportedError) as ex:
        error = ex
      result[hwid_string] = BomAndConfigless(bom, configless, error)
    return result

  def GetHwids(self, project, with_classes=None, without_classes=None,
               with_components=None, without_components=None):
    """Get a filtered list of HWIDs for the given project.

    Args:
      project: The project that you want the HWIDs of.
      with_classes: Filter for component classes that the HWIDs include.
      without_classes: Filter for component classes that the HWIDs don't
        include.
      with_components: Filter for components that the HWIDs include.
      without_components: Filter for components that the HWIDs don't include.

    Returns:
      A list of HWIDs.

    Raises:
      ProjectNotFoundError: The HWID DB of the given project doesn't exists.
      ProjectNotSupportedError: If HWID DB version is not supported.
      ProjectUnavailableError: Fails to load the project's HWID DB.
      InvalidHWIDError: If the project is invalid.
      MethodNotSupportedError: If the HWID version of the project doesn't
        support this method.
    """
    logging.debug('Getting filtered list of HWIDs for %r.', project)
    action = self._GetHWIDAction(project)

    return list(
        action.EnumerateHWIDs(with_classes, without_classes, with_components,
                              without_components))

  def GetComponentClasses(self, project):
    """Get a list of all component classes for the given project.

    Args:
      project: The project that you want the component classes of.

    Returns:
      A list of component classes.

    Raises:
      ProjectNotFoundError: The HWID DB of the given project doesn't exists.
      ProjectNotSupportedError: If HWID DB version is not supported.
      ProjectUnavailableError: Fails to load the project's HWID DB.
      InvalidHWIDError: If the project is invalid.
      MethodNotSupportedError: If the HWID version of the project doesn't
        support this method.
    """
    logging.debug('Getting list of component classes for %r.', project)
    action = self._GetHWIDAction(project)

    return list(action.GetComponentClasses())

  def GetComponents(self, project, with_classes=None):
    """Get a filtered dict of components for the given project.

    Args:
      project: The project that you want the components of.
      with_classes: Filter for component classes that the dict include.

    Returns:
      A dict of components.

    Raises:
      ProjectNotFoundError: The HWID DB of the given project doesn't exists.
      ProjectNotSupportedError: If HWID DB version is not supported.
      ProjectUnavailableError: Fails to load the project's HWID DB.
      InvalidHWIDError: If the project is invalid.
      MethodNotSupportedError: If the HWID version of the project doesn't
        support this method.
    """
    logging.debug('Getting list of components for %r.', project)
    action = self._GetHWIDAction(project)

    return action.GetComponents(with_classes)

  def _GetHWIDAction(self, project):
    """Retrieves the HWID data for a given project, caching as necessary.

    Args:
      project: The project to get data for.

    Returns:
      A HwidData object for the project.

    Raises:
      ProjectNotFoundError: If the given project is unknown.
      ProjectNotSupportedError: If HWID DB version is not supported.
      ProjectUnavailableError: The given project is known, but it encounters
        an error while loading the project's HWID DB.
    """
    logging.debug('Loading data for %r.', project)
    project = _NormalizeString(project)

    hwid_data = self.GetHWIDPreprocDataFromCache(project)
    if hwid_data:
      logging.debug('Found cached data for %r.', project)
    else:
      try:
        metadata = self._hwid_db_data_manager.GetHWIDDBMetadataOfProject(
            project)
        hwid_data = self._LoadHWIDPreprocData(metadata)
      except hwid_db_data.HWIDDBNotFoundError as ex:
        raise ProjectNotFoundError(str(ex)) from ex
      except hwid_db_data.TooManyHWIDDBError as ex:
        raise ProjectUnavailableError(str(ex)) from ex
      self._SaveHWIDPreprocDataToCache(project, hwid_data)

    if isinstance(hwid_data, hwid_preproc_data.HWIDV2PreprocData):
      return hwid_v2_action.HWIDV2Action(hwid_data)
    if isinstance(hwid_data, hwid_preproc_data.HWIDV3PreprocData):
      return hwid_v3_action.HWIDV3Action(hwid_data)
    raise ProjectUnavailableError(
        f'unexpected HWID version: {hwid_data.__class__.__name__}')

  def _LoadHWIDPreprocData(self, metadata):
    """Load hwid data from a file.

    Args:
      metadata: A `hwid_db_data.HWIDDBMetadata` object.

    Returns:
      The HwidData object loaded based on the metadata.

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
      if metadata.version == '2':
        logging.debug('Processing as version 2 file.')
        hwid_data = hwid_preproc_data.HWIDV2PreprocData(metadata.project,
                                                        raw_hwid_yaml)
      elif metadata.version == '3':
        logging.debug('Processing as version 3 file.')
        hwid_data = hwid_preproc_data.HWIDV3PreprocData(metadata.project,
                                                        raw_hwid_yaml)
      else:
        raise ProjectNotSupportedError(
            f'Project {metadata.project!r} has invalid version '
            f'{metadata.version!r}.')
    except hwid_preproc_data.PreprocHWIDError as ex:
      raise ProjectUnavailableError(str(ex)) from ex

    return hwid_data

  def ReloadMemcacheCacheFromFiles(self, limit_models=None):
    """For every known project, load its info into the cache.

    Args:
      limit_models: List of names of models which will be updated.
    """
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
        logging.exception('Exception encountered while reloading cache.')

  def _ClearMemcache(self):
    """Clear all cache items via memcache_adapter.

    This method is for testing purpose since each integration test should have
    empty cache in the beginning.
    """
    self._memcache_adapter.ClearAll()

  def GetHWIDPreprocDataFromCache(self, project):
    """Get the HWID file data from cache.

    There is a two level caching strategy for hwid_data object, first check is
    to the in memory cache.  If the data is not found in memory then we
    attempt to retrieve from memcache.  On memcache success we expand the
    in memory cache with the value retrieved from memcache.

    This allows fast startup of new instances, that slowly get a better and
    better in memory caching.

    Args:
      project: String, the name of the project to retrieve from cache.

    Returns:
       HWIDData object that was cached or null if not found in memory or in the
       memcache.
    """
    try:
      hwid_data = self._memcache_adapter.Get(project)
    except Exception as ex:
      logging.info('Memcache read miss %s: caught exception: %s.', project, ex)
      return None
    if not hwid_data:
      logging.info('Memcache read miss %s.', project)
      return None
    if (not isinstance(hwid_data, hwid_preproc_data.HWIDPreprocData) or
        hwid_data.is_out_of_date):
      logging.info('Memcache read miss %s: got legacy cache value.', project)
      return None
    return hwid_data

  def _SaveHWIDPreprocDataToCache(self, project, hwid_data):
    self._memcache_adapter.Put(project, hwid_data)


def _NormalizeString(string):
  """Normalizes a string to account for things like case."""
  return string.strip().upper() if string else None
