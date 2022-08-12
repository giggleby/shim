# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
from typing import Optional

from google.cloud import datastore

from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine import models
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import type_utils


class ProbeInfoStorageConnector(abc.ABC):
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

  @abc.abstractmethod
  def GetComponentProbeInfo(
      self, component_id: int,
      qual_id: int) -> Optional[stubby_pb2.ComponentProbeInfo]:
    """Loads the specific `ComponentProbeInfo` proto.

      Args:
        component_id: Numeric identity of the component.
        qual_id: Numeric identity of the qualification.

      Returns:
        `ComponentProbeInfo` if it exists.  Otherwise `None` is returned.
    """

  @abc.abstractmethod
  def Clean(self):
    """Testing purpose.  Clean-out all the data."""


class _InMemoryProbeInfoStorageConnector(ProbeInfoStorageConnector):
  """An in-memory implementation for unittesting purpose."""

  def __init__(self):
    self._component_probe_info = {}

  def SaveComponentProbeInfo(self, component_id, qual_id, component_probe_info):
    key = (component_id, qual_id)
    self._component_probe_info[key] = component_probe_info

  def GetComponentProbeInfo(self, component_id, qual_id):
    key = (component_id, qual_id)
    return self._component_probe_info.get(key)

  def Clean(self):
    self._component_probe_info = {}


class _DataStoreProbeInfoStorageConnector(ProbeInfoStorageConnector):
  """An implementation for the instance running on AppEngine."""

  def __init__(self):
    self._client = datastore.Client()

  def _GetEntityKey(self, component_id, qual_id) -> datastore.Key:
    return self._client.key(
        *models.AVLProbeEntity.GetKeyPath(cid=component_id, qid=qual_id))

  def SaveComponentProbeInfo(self, component_id, qual_id, component_probe_info):
    key = self._GetEntityKey(component_id, qual_id)
    entity = self._client.get(key)
    if entity is None:
      model = models.AVLProbeEntity.Create(
          self._client, cid=component_id, qid=qual_id,
          readable_label=component_probe_info.component_identity.readable_label,
          probe_info=component_probe_info.probe_info)
    else:
      model = models.AVLProbeEntity.FromEntity(entity)
      model.probe_info = component_probe_info.probe_info
    self._client.put(model.entity)

  def GetComponentProbeInfo(self, component_id, qual_id):
    key = self._GetEntityKey(component_id, qual_id)
    entity = self._client.get(key)
    if entity is None:
      return None

    # TODO(yhong): Handle data incompatible issues.
    model = models.AVLProbeEntity.FromEntity(entity)
    return stubby_pb2.ComponentProbeInfo(
        component_identity=stubby_pb2.ComponentIdentity(
            readable_label=model.readable_label, qual_id=qual_id,
            component_id=component_id), probe_info=model.probe_info)

  def Clean(self):
    if config.Config().is_prod:
      raise RuntimeError(
          f'Cleaning up datastore data for {self._COMPONENT_PROBE_INFO_KIND!r} '
          'in production runtime environment is forbidden.')
    q = models.AVLProbeEntity.ConstructQuery(self._client)
    q.keys_only()
    self._client.delete_multi(list(q.fetch()))


@type_utils.CachedGetter
def GetProbeInfoStorageConnector() -> ProbeInfoStorageConnector:
  if config.Config().env_type == config.EnvType.LOCAL:
    return _InMemoryProbeInfoStorageConnector()
  return _DataStoreProbeInfoStorageConnector()
