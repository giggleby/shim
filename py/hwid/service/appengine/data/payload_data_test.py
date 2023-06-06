#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from google.cloud import ndb

from cros.factory.hwid.service.appengine.data import payload_data
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module


class PayloadDataManagerTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._ndb_connector = ndbc_module.NDBConnector()

  def tearDown(self):
    super().tearDown()
    self._ClearAll()

  def _AddCLNotification(self, manager: payload_data.PayloadDataManager,
                         notification_type: payload_data.NotificationType,
                         email: str):
    with self._ndb_connector.CreateClientContext():
      entity = payload_data.CLNotification(payload_type=manager.payload_type,
                                           notification_type=notification_type,
                                           email=email)
      entity.put()

  def _ClearAll(self):
    with self._ndb_connector.CreateClientContext():
      ndb.delete_multi(payload_data.CLNotification.query().iter(keys_only=True))
      ndb.delete_multi(
          payload_data.LatestHWIDMainCommit.query().iter(keys_only=True))
      ndb.delete_multi(
          payload_data.LatestPayloadHash.query().iter(keys_only=True))

  def testGetCLReviewers(self):
    manager = payload_data.PayloadDataManager(
        self._ndb_connector, payload_data.PayloadType.VERIFICATION)
    manager2 = payload_data.PayloadDataManager(self._ndb_connector,
                                               payload_data.PayloadType.UNKNOWN)

    self._AddCLNotification(manager, payload_data.NotificationType.REVIEWER,
                            'reviewer@example.com')
    self._AddCLNotification(manager, payload_data.NotificationType.CC,
                            'cc@example.com')
    self._AddCLNotification(manager2, payload_data.NotificationType.REVIEWER,
                            'foo@example.com')
    self._AddCLNotification(manager2, payload_data.NotificationType.CC,
                            'bar@example.com')

    actual = manager.GetCLReviewers()
    self.assertCountEqual(actual, ['reviewer@example.com'])

  def testGetCLCCs(self):
    manager = payload_data.PayloadDataManager(
        self._ndb_connector, payload_data.PayloadType.VERIFICATION)
    manager2 = payload_data.PayloadDataManager(self._ndb_connector,
                                               payload_data.PayloadType.UNKNOWN)

    self._AddCLNotification(manager, payload_data.NotificationType.REVIEWER,
                            'reviewer@example.com')
    self._AddCLNotification(manager, payload_data.NotificationType.CC,
                            'cc@example.com')
    self._AddCLNotification(manager2, payload_data.NotificationType.REVIEWER,
                            'foo@example.com')
    self._AddCLNotification(manager2, payload_data.NotificationType.CC,
                            'bar@example.com')

    actual = manager.GetCLCCs()
    self.assertCountEqual(actual, ['cc@example.com'])

  def testGetLatestHWIDMainCommit(self):
    manager = payload_data.PayloadDataManager(
        self._ndb_connector, payload_data.PayloadType.VERIFICATION)
    manager2 = payload_data.PayloadDataManager(self._ndb_connector,
                                               payload_data.PayloadType.UNKNOWN)

    manager.SetLatestHWIDMainCommit('abcdef')
    manager2.SetLatestHWIDMainCommit('123456')

    actual = manager.GetLatestHWIDMainCommit()
    self.assertEqual(actual, 'abcdef')

  def testGetLatestPayloadHash(self):
    manager = payload_data.PayloadDataManager(
        self._ndb_connector, payload_data.PayloadType.VERIFICATION)
    manager2 = payload_data.PayloadDataManager(self._ndb_connector,
                                               payload_data.PayloadType.UNKNOWN)

    manager.SetLatestPayloadHash('board1', 'hash1')
    manager.SetLatestPayloadHash('board2', 'hash2')
    manager2.SetLatestPayloadHash('board1', 'foo')

    actual = manager.GetLatestPayloadHash('board1')
    self.assertEqual(actual, 'hash1')


if __name__ == '__main__':
  unittest.main()
