#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for config."""

import os
import unittest

from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module


_TEST_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'testdata', 'test_config.yaml')


class ConfigTest(unittest.TestCase):
  """Test for AppEngine config file."""

  # pylint: disable=protected-access

  def testConfigSwitchingDev(self):
    # Have to patch os.enviorn before importing config module
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'unknown project id'
    from cros.factory.hwid.service.appengine.data import config_data
    self.assertEqual('dev', config_data._Config(_TEST_CONFIG_PATH).env)

  def testConfigSwitchingProd(self):
    # Have to patch os.enviorn before importing config module
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'prod-project-name'
    from cros.factory.hwid.service.appengine.data import config_data
    self.assertEqual('prod', config_data._Config(_TEST_CONFIG_PATH).env)

  def testVpgTargets(self):
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'staging-project-name'
    from cros.factory.hwid.service.appengine.data import config_data
    config = config_data._Config(_TEST_CONFIG_PATH)
    self.assertEqual(
        config.vpg_targets['BAR'],
        vpg_config_module.VerificationPayloadGeneratorConfig.Create(
            ignore_error=['stylus'], waived_comp_categories=['display_panel']))


if __name__ == '__main__':
  unittest.main()
