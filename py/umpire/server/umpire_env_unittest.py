#!/usr/bin/env python
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
import os
import shutil
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.umpire.server import resource
from cros.factory.umpire.server import umpire_env
from cros.factory.utils import file_utils


TESTDATA_DIR = os.path.join(os.path.dirname(__file__), 'testdata')
TEST_CONFIG = os.path.join(TESTDATA_DIR,
                           'minimal_empty_services_umpire.yaml')
TOOLKIT_DIR = os.path.join(TESTDATA_DIR, 'install_factory_toolkit.run')


class UmpireEnvTest(unittest.TestCase):

  def setUp(self):
    self.env = umpire_env.UmpireEnvForTest()
    self.mox = mox.Mox()

  def tearDown(self):
    self.mox.UnsetStubs()
    self.mox.VerifyAll()
    self.env.Close()

  def testLoadConfigDefault(self):
    default_path = os.path.join(self.env.base_dir, 'active_umpire.yaml')
    shutil.copy(TEST_CONFIG, default_path)

    self.env.LoadConfig()
    self.assertEqual(default_path, self.env.config_path)

  def testLoadConfigCustomPath(self):
    custom_path = os.path.join(self.env.base_dir, 'custom_config.yaml')
    shutil.copy(TEST_CONFIG, custom_path)

    self.env.LoadConfig(custom_path=custom_path)
    self.assertEqual(custom_path, self.env.config_path)

  def testActivateConfigFile(self):
    file_utils.TouchFile(self.env.active_config_file)
    config_to_activate = os.path.join(self.env.base_dir, 'to_activate.yaml')
    file_utils.TouchFile(config_to_activate)

    self.env.ActivateConfigFile(config_path=config_to_activate)
    self.assertTrue(os.path.exists(self.env.active_config_file))
    self.assertEqual(config_to_activate,
                     os.path.realpath(self.env.active_config_file))

  def testGetResourcePath(self):
    resource_path = self.env.AddConfigFromBlob(
        'hello', resource.ConfigTypeNames.umpire_config)
    resource_name = os.path.basename(resource_path)

    self.assertTrue(resource_path, self.env.GetResourcePath(resource_name))

  def testGetResourcePathNotFound(self):
    self.assertRaises(IOError, self.env.GetResourcePath, 'foobar')

    # Without check, just output resource_dir/resource_name
    self.assertEqual(os.path.join(self.env.resources_dir, 'foobar'),
                     self.env.GetResourcePath('foobar', check=False))

  def testInResource(self):
    # Prepare a resource file.
    resource_path = self.env.AddConfigFromBlob(
        'hello', resource.ConfigTypeNames.umpire_config)
    resource_name = os.path.basename(resource_path)

    # Either full path or resource filename are okay.
    self.assertTrue(self.env.InResource(resource_path))
    self.assertTrue(self.env.InResource(resource_name))

    # Filename not in resources.
    self.assertFalse(self.env.InResource('some_resource'))
    # Dirname mismatch.
    self.assertFalse(self.env.InResource(
        os.path.join('/path/not/in/res', resource_name)))


if __name__ == '__main__':
  unittest.main()
