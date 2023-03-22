#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for config."""

import os
import unittest

from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module
from cros.factory.hwid.v3 import filesystem_adapter


_TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), 'testdata', 'test_config.yaml')


class ConfigTest(unittest.TestCase):
  """Test for AppEngine config file."""
  # pylint: disable=protected-access

  def testConfigSwitchingDev(self):
    # Have to patch os.enviorn before importing config module
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'unknown project id'
    from cros.factory.hwid.service.appengine import config
    self.assertEqual('dev', config._Config(_TEST_CONFIG_PATH).env)

  def testConfigSwitchingProd(self):
    # Have to patch os.enviorn before importing config module
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'prod-project-name'
    from cros.factory.hwid.service.appengine import config
    self.assertEqual('prod', config._Config(_TEST_CONFIG_PATH).env)

  def testFileSystemType(self):
    from cros.factory.hwid.service.appengine import config
    self.assertTrue(
        issubclass(config.CONFIG.hwid_filesystem.__class__,
                   filesystem_adapter.FileSystemAdapter))

  def testHwidManagerType(self):
    from cros.factory.hwid.service.appengine import config
    self.assertTrue(
        issubclass(config.CONFIG.hwid_action_manager.__class__,
                   hwid_action_manager.HWIDActionManager))

  def testVpgTargets(self):
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'staging-project-name'
    from cros.factory.hwid.service.appengine import config
    _config = config._Config(_TEST_CONFIG_PATH)
    self.assertEqual(
        _config.vpg_targets['BAR'],
        vpg_config_module.VerificationPayloadGeneratorConfig.Create(
            ignore_error=['stylus'], waived_comp_categories=['display_panel']))


if __name__ == '__main__':
  unittest.main()
