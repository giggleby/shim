#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for config."""

import os
import unittest

from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.v3 import filesystem_adapter


_TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), 'testdata', 'test_config.yaml')


class ConfigTest(unittest.TestCase):
  """Test for AppEngine config file."""

  def testFileSystemType(self):
    from cros.factory.hwid.service.appengine import config
    self.assertTrue(
        issubclass(config.CONFIG.hwid_filesystem.__class__,
                   filesystem_adapter.IFileSystemAdapter))

  def testHwidManagerType(self):
    from cros.factory.hwid.service.appengine import config
    self.assertTrue(
        issubclass(config.CONFIG.hwid_action_manager.__class__,
                   hwid_action_manager.HWIDActionManager))


if __name__ == '__main__':
  unittest.main()
