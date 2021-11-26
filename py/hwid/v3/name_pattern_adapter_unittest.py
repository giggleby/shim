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

  def testGenerateAVLName_NoQid(self):
    avl_name1 = self._name_pattern.GenerateAVLName(123)
    avl_name2 = self._name_pattern.GenerateAVLName(123, 0)

    self.assertEqual(avl_name1, 'mycomp_123')
    self.assertEqual(avl_name2, 'mycomp_123')

  def testGenerateAVLName_HasQid(self):
    avl_name = self._name_pattern.GenerateAVLName(123, 5)

    self.assertEqual(avl_name, 'mycomp_123_5')

  def testGenerateAVLName_HasSeqNo(self):
    avl_name1 = self._name_pattern.GenerateAVLName(123, seq_no=0)
    avl_name2 = self._name_pattern.GenerateAVLName(123, seq_no=3)

    self.assertEqual(avl_name1, 'mycomp_123#0')
    self.assertEqual(avl_name2, 'mycomp_123#3')

  def testGenerateAVLName_HasQidAndSeqNo(self):
    avl_name = self._name_pattern.GenerateAVLName(123, 5, seq_no=3)

    self.assertEqual(avl_name, 'mycomp_123_5#3')


if __name__ == '__main__':
  unittest.main()
