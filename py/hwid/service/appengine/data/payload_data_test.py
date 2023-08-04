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

  def _SetConfig(self, manager: payload_data.PayloadDataManager, **kwargs):
    entity = manager.config
    with self._ndb_connector.CreateClientContext():
      entity.populate(**kwargs)
      entity.put()

  def _ClearAll(self):
    with self._ndb_connector.CreateClientContext():
      ndb.delete_multi(payload_data.Config.query().iter(keys_only=True))
      ndb.delete_multi(
          payload_data.LatestHWIDMainCommit.query().iter(keys_only=True))
      ndb.delete_multi(
          payload_data.LatestPayloadHash.query().iter(keys_only=True))

  def testConfigDefault(self):
    manager = payload_data.PayloadDataManager(
        self._ndb_connector, payload_data.PayloadType.VERIFICATION)

    config = manager.config
    self.assertFalse(config.disabled)
    self.assertFalse(config.auto_approval)
    self.assertCountEqual(config.reviewers, [])
    self.assertCountEqual(config.ccs, [])

  def testConfig(self):
    manager = payload_data.PayloadDataManager(
        self._ndb_connector, payload_data.PayloadType.VERIFICATION)
    manager2 = payload_data.PayloadDataManager(self._ndb_connector,
                                               payload_data.PayloadType.UNKNOWN)

    self._SetConfig(manager, disabled=True, auto_approval=True,
                    reviewers=['reviewer@example.com'], ccs=['cc@example.com'])
    self._SetConfig(manager2, reviewers=['foo@example.com'],
                    ccs=['bar@example.com'])

    config = manager.config
    self.assertTrue(config.disabled)
    self.assertTrue(config.auto_approval)
    self.assertCountEqual(config.reviewers, ['reviewer@example.com'])
    self.assertCountEqual(config.ccs, ['cc@example.com'])

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
