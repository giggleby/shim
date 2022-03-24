#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.v3 import name_pattern_adapter


class NamePatternTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._name_pattern = (
        name_pattern_adapter.NamePatternAdapter().GetNamePattern('mycomp'))

  def testMatches_RegularComponent(self):
    name_info = self._name_pattern.Matches('mycomp_123')

    self.assertEqual(name_info,
                     name_pattern_adapter.NameInfo.from_comp(cid=123))

  def testMatches_RegularComponentWithQid(self):
    name_info = self._name_pattern.Matches('mycomp_123_456')

    self.assertEqual(name_info,
                     name_pattern_adapter.NameInfo.from_comp(cid=123, qid=456))

  def testMatches_RegularComponentWithSeqNo(self):
    name_info = self._name_pattern.Matches('mycomp_123#3')

    self.assertEqual(name_info,
                     name_pattern_adapter.NameInfo.from_comp(cid=123))

  def testGenerateAVLName_NoQid(self):
    name_info = name_pattern_adapter.NameInfo.from_comp(cid=123)
    avl_name = self._name_pattern.GenerateAVLName(name_info)

    self.assertEqual(avl_name, 'mycomp_123')

  def testGenerateAVLName_HasQid(self):
    name_info = name_pattern_adapter.NameInfo.from_comp(cid=123, qid=5)
    avl_name = self._name_pattern.GenerateAVLName(name_info)

    self.assertEqual(avl_name, 'mycomp_123_5')

  def testGenerateAVLName_HasSeqNo(self):
    name_info = name_pattern_adapter.NameInfo.from_comp(cid=123)
    avl_name1 = self._name_pattern.GenerateAVLName(name_info, seq='0')
    name_info = name_pattern_adapter.NameInfo.from_comp(cid=123)
    avl_name2 = self._name_pattern.GenerateAVLName(name_info, seq='3')

    self.assertEqual(avl_name1, 'mycomp_123#0')
    self.assertEqual(avl_name2, 'mycomp_123#3')

  def testGenerateAVLName_HasQidAndSeqNo(self):
    name_info = name_pattern_adapter.NameInfo.from_comp(cid=123, qid=5)
    avl_name = self._name_pattern.GenerateAVLName(name_info, seq='3')

    self.assertEqual(avl_name, 'mycomp_123_5#3')


if __name__ == '__main__':
  unittest.main()
