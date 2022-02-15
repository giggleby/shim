# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
from typing import Optional

from google.cloud import datastore  # pylint: disable=no-name-in-module

from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import type_utils


class IProbeInfoStorageConnector(abc.ABC):
  """Interface for a probe info storage connector."""

  @abc.abstractmethod
  def SaveComponentProbeInfo(
      self, component_id: int, qual_id: int,
      component_probe_info: stubby_pb2.ComponentProbeInfo):
    """Saves the auto-generated `ComponentProbeInfo` proto.

      Args:
        component_id: Numeric identity of the component.
        qual_id: Numeric identity of the qualification.
        component_probe_info: A proto message of `ComponentProbeInfo`.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def GetComponentProbeInfo(
      self, component_id: int,
      qual_id: int) -> Optional[stubby_pb2.ComponentProbeInfo]:
    """Load the specific `ComponentProbeInfo` proto.

      Args:
        component_id: Numeric identity of the component.
        qual_id: Numeric identity of the qualification.

      Returns:
        `ComponentProbeInfo` if it exists.  Otherwise `None` is returned.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def Clean(self):
    """Testing purpose.  Clean-out all the data."""
    raise NotImplementedError


class _InMemoryProbeInfoStorageConnector(IProbeInfoStorageConnector):
  """An in-memory implementation for unittesting purpose."""

  def __init__(self):
    super().__init__()
    self._component_probe_info = {}

  def SaveComponentProbeInfo(self, component_id, qual_id, component_probe_info):
    key = (component_id, qual_id)
    self._component_probe_info[key] = component_probe_info

  def GetComponentProbeInfo(self, component_id, qual_id):
    key = (component_id, qual_id)
    return self._component_probe_info.get(key)

  def Clean(self):
    self._component_probe_info = {}


class _DataStoreProbeInfoStorageConnector(IProbeInfoStorageConnector):
  """An implementation for the instance running on AppEngine."""

  _COMPONENT_PROBE_INFO_KIND = 'component_probe_info'
  _DATA_KEY_NAME = 'bytes'

  def __init__(self):
    super(_DataStoreProbeInfoStorageConnector, self).__init__()
    self._client = datastore.Client()

  def SaveComponentProbeInfo(self, component_id, qual_id, component_probe_info):
    entity_path = self._GetProbeInfoDataPath(component_id, qual_id)
    data = {
        self._DATA_KEY_NAME: component_probe_info.SerializeToString()
    }
    self._SaveEntity(entity_path, data)

  def GetComponentProbeInfo(self, component_id, qual_id):
    entity_path = self._GetProbeInfoDataPath(component_id, qual_id)
    data = self._LoadEntity(entity_path)
    if data is None or self._DATA_KEY_NAME not in data:
      return None
    component_probe_info = stubby_pb2.ComponentProbeInfo()
    component_probe_info.ParseFromString(data[self._DATA_KEY_NAME])
    return component_probe_info

  def Clean(self):
    if config.Config().env_type == config.EnvType.PROD:
      raise RuntimeError(
          'Cleaning up datastore data for %r in production '
          'runtime environment is forbidden.' % self._COMPONENT_PROBE_INFO_KIND)
    q = self._client.query(kind=self._COMPONENT_PROBE_INFO_KIND)
    self._client.delete_multi([e.key for e in q.fetch()])

  def _GetProbeInfoDataPath(self, component_id, qual_id):
    name = f'{component_id}-{qual_id}'
    return [self._COMPONENT_PROBE_INFO_KIND, name]

  def _SaveEntity(self, path_args, data):
    key = self._client.key(*path_args)
    entity = datastore.Entity(key)
    entity.update(data)
    self._client.put(entity)

  def _LoadEntity(self, path_args):
    key = self._client.key(*path_args)
    return self._client.get(key)


@type_utils.CachedGetter
def GetProbeInfoStorageConnector():
  if config.Config().env_type == config.EnvType.LOCAL:
    return _InMemoryProbeInfoStorageConnector()
  return _DataStoreProbeInfoStorageConnector()
