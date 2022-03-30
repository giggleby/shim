#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil
import unittest

from cros.factory.umpire import common
from cros.factory.umpire.server.commands import factory_drives
from cros.factory.umpire.server import umpire_env
from cros.factory.utils import file_utils

TESTDATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'testdata')
TEST_FACTORY_DRIVE = os.path.join(TESTDATA_DIR, 'test_factory_drive.json')


class FactoryDrivesTest(unittest.TestCase):

  def setUp(self):
    self.env = umpire_env.UmpireEnvForTest()
    factory_drive_json_file = self.env.factory_drive_json_file
    shutil.copy(TEST_FACTORY_DRIVE, factory_drive_json_file)
    self.factory_drives = factory_drives.FactoryDrives(self.env)

  def tearDown(self):
    self.env.Close()

  def testQueryFactoryDrives(self):
    # Query w.sh in parent directory
    query_file = self.factory_drives.QueryFactoryDrives(None, 'w.sh')
    self.assertEqual(query_file, [('w.sh', 'some/path/w0.sh')])

    # Query all components under dir0/dir1
    query_namespace = self.factory_drives.QueryFactoryDrives('dir0/dir1', None)
    self.assertEqual(query_namespace, [('x.json', 'some/path/x2.json'),
                                       ('a.html', 'some/path/a1.html')])

    # Query not existed component
    query_error = self.factory_drives.QueryFactoryDrives(
        'dir0', 'not_existed_file')
    self.assertEqual(query_error, [])

  def testUpdateFactoryDriveComponent(self):
    test_file_path = os.path.join(self.env.base_dir, 'test.txt')
    file_utils.TouchFile(test_file_path)

    # Create new component
    component = self.factory_drives.UpdateFactoryDriveComponent(
        None, 0, 'test.txt', None, test_file_path)
    self.assertEqual(
        component, {
            'id': 3,
            'dir_id': 0,
            'name': 'test.txt',
            'revisions':
                [self.factory_drives.GetFactoryDriveDstPath(test_file_path)],
            'using_ver': 0
        })

    # Update version
    component = self.factory_drives.UpdateFactoryDriveComponent(
        0, None, 'w.sh', None, test_file_path)
    self.assertEqual(
        component, {
            'id': 0,
            'dir_id': None,
            'name': 'w.sh',
            'revisions': [
                'some/path/w0.sh',
                self.factory_drives.GetFactoryDriveDstPath(test_file_path)
            ],
            'using_ver': 1
        })

    # Update version and change version at the same time
    self.assertRaises(common.UmpireError,
                      self.factory_drives.UpdateFactoryDriveComponent, 0, None,
                      'w.sh', 1, test_file_path)

    # Changing to invalid version
    self.assertRaises(common.UmpireError,
                      self.factory_drives.UpdateFactoryDriveComponent, 0, None,
                      'w.sh', 10, None)

  def testUpdateFactoryDriveDirectory(self):
    # Create directory
    directory = self.factory_drives.UpdateFactoryDriveDirectory(None, 0, 'dir2')
    self.assertEqual(directory, {
        'id': 2,
        'name': 'dir2',
        'parent_id': 0
    })

    # Rename directory
    directory = self.factory_drives.UpdateFactoryDriveDirectory(
        1, None, 'dir1.1')
    self.assertEqual(directory, {
        'id': 1,
        'name': 'dir1.1',
        'parent_id': 0
    })


if __name__ == '__main__':
  unittest.main()
