# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Payload generation related data models and their manager."""

import enum
from typing import Collection, Optional

from google.cloud import ndb

from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module


class PayloadType(str, enum.Enum):
  """The known payload types."""

  UNKNOWN = ''
  VERIFICATION = 'verification'

  def __str__(self):
    return self.value


class NotificationType(str, enum.Enum):
  """The notification types."""

  REVIEWER = 'reviewer'
  CC = 'cc'

  def __str__(self):
    return self.value


class CLNotification(ndb.Model):
  """Emails of CL notification recipients."""

  payload_type = ndb.StringProperty()
  notification_type = ndb.StringProperty()
  email = ndb.StringProperty()


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
  def payload_type(self):
    return self._payload_type

  def _GetCLNotifications(
      self, notification_type: NotificationType) -> Collection[str]:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = CLNotification.query(
          CLNotification.notification_type == notification_type,
          CLNotification.payload_type == self._payload_type)
      return [notification.email for notification in q]

  def GetCLReviewers(self) -> Collection[str]:
    return self._GetCLNotifications(NotificationType.REVIEWER)

  def GetCLCCs(self) -> Collection[str]:
    return self._GetCLNotifications(NotificationType.CC)

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
