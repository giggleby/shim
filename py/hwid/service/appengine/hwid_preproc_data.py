# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines Preprocessors for HWID DBs."""

from cros.factory.hwid.v2 import yaml_datastore as v2_yaml_datastore
from cros.factory.hwid.v3 import common as v3_common
from cros.factory.hwid.v3 import database as v3_database


class PreprocHWIDError(Exception):
  """Indicates an error regarding preprocessing HWID DB contents."""


class HWIDPreprocData:
  """Base class of versioned HWID proprocessed data."""

  # A version value for identifying out-of-date cached data.
  #
  # Implementations of `HWIDPreprocData` must assign and maintain this version
  # value as a class attribute (not instance attribute) carefully.  When an
  # instance is constructed, it snapshots this version value as an instance
  # attribute.  When other modules load an instance of `HWIDPreprocData` from
  # non-volatile storages, they should check if the snapshotted version value
  # matches the current `CACHE_VERSION` or not to determine if that instance
  # is out-of-date or not.
  CACHE_VERSION: str

  def __init__(self, project: str):
    self._cache_version_snapshot = self.CACHE_VERSION
    self.project = project

  @property
  def is_out_of_date(self) -> bool:
    """Returns `True` if this instance is considered as expired."""
    return self._cache_version_snapshot != self.CACHE_VERSION


class HWIDV2PreprocData(HWIDPreprocData):
  """Holds preprocessed HWIDv2 data."""

  CACHE_VERSION = '2'

  def __init__(self, project, raw_hwid_yaml):
    """Constructor.

    Requires one of hwid_file, hwid_yaml or hwid_data.

    Args:
      project: The project name
      raw_hwid_yaml: the raw YAML string of HWID data.

    Raises:
      PreprocHWIDError: Fails to load the given HWIDv2 DB contents.
    """
    super().__init__(project)
    self.bom_map = {}
    self.variant_map = {}
    self.volatile_map = {}
    self.hwid_status_map = {}
    self.volatile_value_map = {}

    self._SeedFromData(v2_yaml_datastore.YamlRead(raw_hwid_yaml))

  def _SeedFromData(self, hwid_data):
    fields = ['boms', 'variants', 'volatiles', 'hwid_status', 'volatile_values']
    for field in fields:
      if field not in hwid_data:
        raise PreprocHWIDError(
            f'invalid HWIDv2 file supplied, missing required field {field!r}')

    for (local_map, data) in [(self.bom_map, hwid_data['boms']),
                              (self.variant_map, hwid_data['variants']),
                              (self.volatile_map, hwid_data['volatiles'])]:
      for name in data:
        normalized_name = _NormalizeString(name)
        local_map[normalized_name] = data[name]
    for (local_map, data) in [(self.hwid_status_map, hwid_data['hwid_status']),
                              (self.volatile_value_map,
                               hwid_data['volatile_values'])]:
      for name in data:
        local_map[name] = data[name]


class HWIDV3PreprocData(HWIDPreprocData):
  """Holds preprocessed HWIDv3 data."""

  CACHE_VERSION = '6'

  def __init__(self, project: str, raw_hwid_yaml: str,
               raw_hwid_yaml_internal: str, hwid_db_commit_id: str):
    """Constructor.

    Requires one of hwid_file, hwid_yaml or hwid_data.

    Args:
      project: The project name
      raw_hwid_yaml: the raw YAML string of HWID data.
      raw_hwid_yaml_internal: the internal format of HWID data.
      hwid_db_commit_id: the commit id of the HWIDB data.

    Raises:
      PreprocHWIDError: Fails to load the given HWIDv3 DB contents.
    """
    super().__init__(project)
    self._raw_database = raw_hwid_yaml
    self._raw_database_internal = raw_hwid_yaml_internal
    self._hwid_db_commit_id = hwid_db_commit_id
    try:
      self._database = v3_database.Database.LoadData(raw_hwid_yaml_internal,
                                                     expected_checksum=None)
    except v3_common.HWIDException as ex:
      raise PreprocHWIDError(f'fail to load HWIDv3 DB: {ex}') from ex

  @property
  def hwid_db_commit_id(self):
    return self._hwid_db_commit_id

  @property
  def raw_database(self):
    return self._raw_database

  @property
  def raw_database_internal(self):
    return self._raw_database_internal

  @property
  def database(self):
    return self._database


def _NormalizeString(string):
  """Normalizes a string to account for things like case."""
  return string.strip().upper() if string else None
