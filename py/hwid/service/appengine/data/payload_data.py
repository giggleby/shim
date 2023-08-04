# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Payload generation related data models and their manager."""

import enum
from typing import Optional

from google.cloud import ndb

from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module


class PayloadType(str, enum.Enum):
  """The known payload types."""

  UNKNOWN = ''
  VERIFICATION = 'verification'
  HWID_SELECTION = 'hwid_selection'

  def __str__(self):
    return self.value


class Config(ndb.Model):
  """A config for payload generation which can be modified on Datastore.

  Attributes:
    payload_type: The payload type of config, which should be one of
        PayloadType.
    reviewers: E-mail addresses to be added to reviewer of CL.
    ccs: E-mail addresses to be added to cc of CL.
  """

  @classmethod
  def _get_kind(cls):
    return 'PayloadConfig'

  payload_type = ndb.StringProperty()
  reviewers = ndb.StringProperty(repeated=True)
  ccs = ndb.StringProperty(repeated=True)


class LatestHWIDMainCommit(ndb.Model):
  """Latest main commit of private overlay repo with generated payloads."""

  payload_type = ndb.StringProperty()
  commit = ndb.StringProperty()


class LatestPayloadHash(ndb.Model):
  """Latest hash of generated payloads."""

  payload_type = ndb.StringProperty()
  board = ndb.StringProperty()
  payload_hash = ndb.StringProperty()


class PayloadDataManager:

  def __init__(self, ndb_connector: ndbc_module.NDBConnector,
               payload_type: PayloadType):
    self._ndb_connector = ndb_connector
    self._payload_type = payload_type

  @property
  def payload_type(self) -> PayloadType:
    return self._payload_type

  @property
  def config(self) -> Config:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entity = Config.query(Config.payload_type == self._payload_type).get()
      if entity is None:
        return Config(payload_type=self._payload_type)
      return entity

  def GetLatestHWIDMainCommit(self) -> Optional[str]:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entity = LatestHWIDMainCommit.query(
          LatestHWIDMainCommit.payload_type == self._payload_type).get()
      return entity.commit if entity is not None else None

  def SetLatestHWIDMainCommit(self, commit: str):
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entity = LatestHWIDMainCommit.query(
          LatestHWIDMainCommit.payload_type == self._payload_type).get()
      if entity is None:
        entity = LatestHWIDMainCommit(payload_type=self._payload_type)
      entity.commit = commit
      entity.put()

  def GetLatestPayloadHash(self, board: str) -> Optional[str]:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entity = LatestPayloadHash.query(
          LatestPayloadHash.board == board,
          LatestPayloadHash.payload_type == self._payload_type).get()
      return entity.payload_hash if entity is not None else None

  def SetLatestPayloadHash(self, board: str, payload_hash: str):
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entity = LatestPayloadHash.query(
          LatestPayloadHash.board == board,
          LatestPayloadHash.payload_type == self._payload_type).get()
      if entity is None:
        entity = LatestPayloadHash(board=board, payload_type=self._payload_type)
      entity.payload_hash = payload_hash
      entity.put()
