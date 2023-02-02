# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine.data import avl_metadata_util
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import rule as v3_rule


class AVLMetadataManagerTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._ndb_connector = ndbc_module.NDBConnector()
    self._manager = avl_metadata_util.AVLMetadataManager(self._ndb_connector)

  def tearDown(self):
    super().tearDown()
    self._manager.CleanAllForTest()

  def testSkipAVLCheck_FieldNameIsNotName(self):
    self._manager.UpdateAudioCodecBlocklist([
        'kernel_name1',
        'kernel_name2',
    ])

    comp1 = database.ComponentInfo({'kernel_name': 'kernel_name1'}, 'supported')
    comp2 = database.ComponentInfo({'kernel_name': 'kernel_name2'}, 'supported')
    comp3 = database.ComponentInfo({'kernel_name': 'kernel_name3'}, 'supported')
    self.assertFalse(self._manager.SkipAVLCheck('audio_codec', comp1))
    self.assertFalse(self._manager.SkipAVLCheck('audio_codec', comp2))
    self.assertFalse(self._manager.SkipAVLCheck('audio_codec', comp3))

  def testSkipAVLCheck_CompClsIsNotAudioCodec(self):
    self._manager.UpdateAudioCodecBlocklist([
        'kernel_name1',
        'kernel_name2',
    ])

    comp1 = database.ComponentInfo({'name': 'kernel_name1'}, 'supported')
    comp2 = database.ComponentInfo({'name': 'kernel_name2'}, 'supported')
    comp3 = database.ComponentInfo({'name': 'kernel_name3'}, 'supported')
    self.assertFalse(self._manager.SkipAVLCheck('battery', comp1))
    self.assertFalse(self._manager.SkipAVLCheck('battery', comp2))
    self.assertFalse(self._manager.SkipAVLCheck('battery', comp3))

  def testSkipAVLCheck_CompClsIsAudioCodec(self):
    self._manager.UpdateAudioCodecBlocklist([
        'kernel_name1',
        'kernel_name2',
    ])

    comp1 = database.ComponentInfo({'name': 'kernel_name1'}, 'supported')
    comp2 = database.ComponentInfo({'name': 'kernel_name2'}, 'supported')
    comp3 = database.ComponentInfo({'name': 'kernel_name3'}, 'supported')
    self.assertTrue(self._manager.SkipAVLCheck('audio_codec', comp1))
    self.assertTrue(self._manager.SkipAVLCheck('audio_codec', comp2))
    self.assertFalse(self._manager.SkipAVLCheck('audio_codec', comp3))

  def testSkipAVLCheck_MultipleUpdates(self):
    self._manager.UpdateAudioCodecBlocklist([
        'kernel_name1',
        'kernel_name2',
        'kernel_name3',
    ])
    self._manager.UpdateAudioCodecBlocklist([
        'kernel_name1',
        'kernel_name2',
    ])

    comp1 = database.ComponentInfo({'name': 'kernel_name1'}, 'supported')
    comp2 = database.ComponentInfo({'name': 'kernel_name2'}, 'supported')
    comp3 = database.ComponentInfo({'name': 'kernel_name3'}, 'supported')
    self.assertTrue(self._manager.SkipAVLCheck('audio_codec', comp1))
    self.assertTrue(self._manager.SkipAVLCheck('audio_codec', comp2))
    self.assertFalse(self._manager.SkipAVLCheck('audio_codec', comp3))

  def testSkipAVLCheck_SkipNonStr(self):
    self._manager.UpdateAudioCodecBlocklist([
        'kernel_name1',
        'kernel_name2',
    ])
    comp_with_re = database.ComponentInfo(
        {'name': v3_rule.Value(r'^kernel_name\d$', is_re=True)}, 'supported')
    self.assertFalse(self._manager.SkipAVLCheck('audio_codec', comp_with_re))


if __name__ == '__main__':
  unittest.main()
