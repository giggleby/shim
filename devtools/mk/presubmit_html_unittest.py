#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

import presubmit_html


class IsQuirkModeTest(unittest.TestCase):

  @mock.patch.object(presubmit_html.pathlib, 'Path', autospec=True)
  def testNoDoctypeHTML_IsQuirkMode(self, mock_path):
    mock_path.open.return_value.__enter__.return_value.read.return_value = (
        '<html></html>')

    self.assertTrue(presubmit_html.IsQuirkMode(mock_path))

  @mock.patch.object(presubmit_html.pathlib, 'Path', autospec=True)
  def testHasDoctype_IsNotQuirkMode(self, mock_path):
    mock_path.open.return_value.__enter__.return_value.read.return_value = (
        '<!DOCTYPE html><html></html>')

    self.assertFalse(presubmit_html.IsQuirkMode(mock_path))

  @mock.patch.object(presubmit_html.pathlib, 'Path', autospec=True)
  def testNoDoctypeNonHTML_IsNotQuirkMode(self, mock_path):
    mock_path.open.return_value.__enter__.return_value.read.return_value = (
        '<test-template></test-template>')

    self.assertFalse(presubmit_html.IsQuirkMode(mock_path))


if __name__ == '__main__':
  unittest.main()
