#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.utils.url_spec import URLSpec


class URLSpecTest(unittest.TestCase):

  def setUp(self):

    def MockCallOutput(command):
      self.assertListEqual(['ip', 'addr', 'show', 'to'], command[:-1])
      return 1 if command[-1].startswith('matched_domain') else 0

    self.dut = mock.Mock()
    self.dut.CallOutput = MockCallOutput

  def testSingleURL(self):
    url = 'http://123.45.67.89:3456'

    actual = URLSpec.FindServerURL(url, self.dut)

    self.assertEqual(actual, 'http://123.45.67.89:3456')

  def testURLSpec(self):
    urlSpec = {
        'another_domain': 'unused_url',
        "default": "will_be_ignored",
        'matched_domain': 'server_url',
    }

    actual = URLSpec.FindServerURL(urlSpec, self.dut)

    self.assertEqual(actual, 'server_url')

  def testMultimatchedDomains(self):
    urlSpec = {
        "matched_domain/16": "will_be_ignored",
        "matched_domain/24": "server_url",
    }

    actual = URLSpec.FindServerURL(urlSpec, self.dut)

    self.assertEqual(actual, 'server_url')

  def testDefault(self):
    urlSpec = {
        "default": "server_url",
    }

    actual = URLSpec.FindServerURL(urlSpec, self.dut)

    self.assertEqual(actual, 'server_url')

  def testInvalidFormat(self):
    for param in [None, ['url'], {}, {
        'matched_domain': ''
    }]:
      with self.subTest(param=param):
        actual = URLSpec.FindServerURL(param, self.dut)
        self.assertEqual(actual, '')


if __name__ == '__main__':
  unittest.main()
