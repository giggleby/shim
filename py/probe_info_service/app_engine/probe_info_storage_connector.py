# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
from typing import Optional

from google.cloud import datastore
from google.protobuf import text_format

from cros.factory.probe_info_service.app_engine import config
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


class _EntityConverter:
  """Convert component probe info messages to / from datastore entities."""

  def ToEntity(self, key: datastore.Key,
               message: stubby_pb2.ComponentProbeInfo) -> datastore.Entity:
    """Converts a protobuf message to the corresponding entity."""
    raise NotImplementedError

  def FromEntity(self,
                 entity: datastore.Entity) -> stubby_pb2.ComponentProbeInfo:
    """Converts the entity back to the protobuf message."""
    raise NotImplementedError


class _ProdEntityConverter(_EntityConverter):
  """The entity data converter used in production."""

  _DATA_KEY = 'bytes'

  def ToEntity(self, key: datastore.Key,
               message: stubby_pb2.ComponentProbeInfo) -> datastore.Entity:
    """See base class."""
    entity = datastore.Entity(key)
    entity.update({self._DATA_KEY: message.SerializeToString()})
    return entity

  def FromEntity(self,
                 entity: datastore.Entity) -> stubby_pb2.ComponentProbeInfo:
    """See base class."""
    message = stubby_pb2.ComponentProbeInfo()
    message.ParseFromString(entity[self._DATA_KEY])
    return message


class _NonProdEntityConverter(_EntityConverter):
  """The entity data converter used in non-production environment."""

  _DATA_KEY = 'bytes'
  _RAW_TEXTPB_KEY = 'raw_textpb'

  def ToEntity(self, key: datastore.Key,
               message: stubby_pb2.ComponentProbeInfo) -> datastore.Entity:
    """See base class."""
    entity = datastore.Entity(key, exclude_from_indexes=[self._RAW_TEXTPB_KEY])
    entity.update({
        self._DATA_KEY: message.SerializeToString(deterministic=True),
        self._RAW_TEXTPB_KEY: text_format.MessageToString(message),
    })
    return entity

  def FromEntity(self,
                 entity: datastore.Entity) -> stubby_pb2.ComponentProbeInfo:
    """See base class."""
    message = stubby_pb2.ComponentProbeInfo()
    message.ParseFromString(entity[self._DATA_KEY])
    return message


class _DataStoreProbeInfoStorageConnector(ProbeInfoStorageConnector):
  """An implementation for the instance running on AppEngine."""

  _COMPONENT_PROBE_INFO_KIND = 'component_probe_info'

  def __init__(self, entity_converter: _EntityConverter):
    self._entity_converter = entity_converter

    self._client = datastore.Client()

  def _GetEntityKey(self, component_id, qual_id) -> datastore.Key:
    name = f'{component_id}-{qual_id}'
    return self._client.key(self._COMPONENT_PROBE_INFO_KIND, name)

  def SaveComponentProbeInfo(self, component_id, qual_id, component_probe_info):
    key = self._GetEntityKey(component_id, qual_id)
    entity = self._entity_converter.ToEntity(key, component_probe_info)
    self._client.put(entity)

  def GetComponentProbeInfo(self, component_id, qual_id):
    key = self._GetEntityKey(component_id, qual_id)
    entity = self._client.get(key)
    if not entity:
      return None
    # TODO(yhong): Handle data incompatible issues.
    return self._entity_converter.FromEntity(entity)

  def Clean(self):
    if config.Config().env_type == config.EnvType.PROD:
      raise RuntimeError(
          f'Cleaning up datastore data for {self._COMPONENT_PROBE_INFO_KIND!r} '
          'in production runtime environment is forbidden.')
    q = self._client.query(kind=self._COMPONENT_PROBE_INFO_KIND)
    self._client.delete_multi([e.key for e in q.fetch()])


def _ResolveComponentProbeInfoParser() -> _EntityConverter:
  if config.Config().env_type == config.EnvType.PROD:
    return _ProdEntityConverter()
  return _NonProdEntityConverter()


@type_utils.CachedGetter
def GetProbeInfoStorageConnector() -> ProbeInfoStorageConnector:
  if config.Config().env_type == config.EnvType.LOCAL:
    return _InMemoryProbeInfoStorageConnector()
  return _DataStoreProbeInfoStorageConnector(_ResolveComponentProbeInfoParser())
