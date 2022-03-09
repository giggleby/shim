# Copyright 2021 The Chromium OS Authors. All rights reserved.
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

  def testGetAVLName_NormalMatchWithComment(self):
    self._AddAVLNameMapping(1234, 'comp_name1')
    avl_name = self._manager.GetAVLName('category1',
                                        'category1_1234_5678#hello-world')
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


if __name__ == '__main__':
  unittest.main()
