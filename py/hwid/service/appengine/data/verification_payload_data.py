# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Verification payload generation related data models and their manager."""

from typing import List, Optional

from google.cloud import ndb  # pylint: disable=no-name-in-module, import-error

from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module


class CLNotification(ndb.Model):
  """Emails of CL notification recipients."""

  notification_type = ndb.StringProperty()
  email = ndb.StringProperty()


class LatestHWIDMainCommit(ndb.Model):
  """Latest main commit of private overlay repo with generated payloads."""

  commit = ndb.StringProperty()


class LatestPayloadHash(ndb.Model):
  """Latest hash of payload generated from verification_payload_generator."""

  payload_hash = ndb.StringProperty()


class VerificationPayloadDataManager:

  def __init__(self, ndb_connector: ndbc_module.NDBConnector):
    self._ndb_connector = ndb_connector

  def GetCLReviewers(self) -> List[str]:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = CLNotification.query(CLNotification.notification_type == 'reviewer')
      return [notification.email for notification in q]

  def GetCLCCs(self) -> List[str]:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = CLNotification.query(CLNotification.notification_type == 'cc')
      return [notification.email for notification in q]

  def GetLatestHWIDMainCommit(self) -> str:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      key = ndb.Key(LatestHWIDMainCommit, 'commit')
      entry = LatestHWIDMainCommit.query(LatestHWIDMainCommit.key == key).get()
      return entry.commit

  def SetLatestHWIDMainCommit(self, commit):
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      key = ndb.Key(LatestHWIDMainCommit, 'commit')
      entity = LatestHWIDMainCommit.query(LatestHWIDMainCommit.key == key).get()
      entity.commit = commit
      entity.put()

  def GetLatestPayloadHash(self, board) -> Optional[str]:
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      key = ndb.Key(LatestPayloadHash, board)
      entity = LatestPayloadHash.query(LatestPayloadHash.key == key).get()
      if entity is not None:
        return entity.payload_hash
      return None

  def SetLatestPayloadHash(self, board, payload_hash):
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      latest_hash = LatestPayloadHash.get_or_insert(board)
      latest_hash.payload_hash = payload_hash
      latest_hash.put()
