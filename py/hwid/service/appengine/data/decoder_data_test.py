# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module


class DecoderDataManagerTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._ndb_connector = ndbc_module.NDBConnector()
    self._manager = decoder_data.DecoderDataManager(self._ndb_connector)

  def tearDown(self):
    super().tearDown()
    self._manager.CleanAllForTest()

  def _AddAVLNameMapping(self, component_id, name):
    with self._ndb_connector.CreateClientContext():
      decoder_data.AVLNameMapping(component_id=component_id, name=name).put()

  def testGetAVLName_NormalMatch(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1', 'category1_1234_5678')
    self.assertEqual(avl_name, 'comp_name1')

  def testGetAVLName_NormalMatchOfSubcomp(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1', 'category1_subcomp_1234')
    self.assertEqual(avl_name, 'comp_name1')

  def testGetAVLName_NoMatchWithComment(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1',
                                        'category1_9012_1234#hello-world')
    self.assertEqual(avl_name, 'category1_9012_1234#hello-world')

  def testGetAVLName_NoSuchComponentIdInDatastore(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1', 'category1_2222_5555')
    self.assertEqual(avl_name, 'category1_2222_5555')

  def testGetAVLName_CategoryNameNotInComponentName(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1', 'category2_1234_5678')
    self.assertEqual(avl_name, 'category2_1234_5678')

  def testGetAVLName_NotEnoughSplits(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1', 'category1_1234')
    self.assertEqual(avl_name, 'comp_name1')

  def testGetAVLName_TooManySplits(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1', 'category1_1234_5678_9012')
    self.assertEqual(avl_name, 'category1_1234_5678_9012')

  def testSyncAVLNameMapping_TouchedCIDs(self):
    self._AddAVLNameMapping(1, 'comp_name1')
    self._AddAVLNameMapping(2, 'comp_name2')  # To be removed.
    self._AddAVLNameMapping(3, 'comp_name3')

    touched_cids = self._manager.SyncAVLNameMapping({
        1: 'comp_name1',  # Unchanged.
        3: 'comp_name3-changed',  # Changed.
        4: 'comp_name4',  # Created.
    })

    self.assertCountEqual({2, 3, 4}, touched_cids)


if __name__ == '__main__':
  unittest.main()
