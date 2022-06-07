#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# mock gcs_utils so that this test can run in chroot.
sys.modules['cros.factory.instalog.utils.gcs_utils'] = mock.Mock()

from cros.factory.instalog.plugins import output_factory_report  # pylint: disable=wrong-import-position


def CreateZipArchive(archive_name, dir_to_archive):
  return shutil.make_archive(archive_name, 'zip', dir_to_archive)


def CreateTarArchive(archive_name, dir_to_archive):
  return shutil.make_archive(archive_name, 'tar', dir_to_archive)


class ArchiveUnittest(unittest.TestCase):
  """Test |Archive| interface."""

  @classmethod
  def setUpClass(cls):
    cls.test_dir = tempfile.mkdtemp()

  @classmethod
  def tearDownClass(cls):
    shutil.rmtree(cls.test_dir)

  def testCreateTarArchive(self):
    with tempfile.TemporaryDirectory() as d:
      archive_path = CreateTarArchive(os.path.join(self.test_dir, 'test'), d)
    archive = output_factory_report.GetArchive(archive_path)
    self.assertIsInstance(archive, output_factory_report.TarArchive)

  def testCreateZipArchive(self):
    with tempfile.TemporaryDirectory() as d:
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), d)
    archive = output_factory_report.GetArchive(archive_path)
    self.assertIsInstance(archive, output_factory_report.ZipArchive)

  def testZipGetNonDirFileNames(self):
    expected_file_names = {'1.txt', '2.txt'}
    with tempfile.TemporaryDirectory() as d:
      for name in expected_file_names:
        with open(os.path.join(d, name), 'w', encoding="utf-8") as f:
          f.write('test')
      os.mkdir(os.path.join(d, 'test'))
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), d)

    with output_factory_report.GetArchive(archive_path) as archive:
      file_names = set(archive.GetNonDirFileNames())
    self.assertEqual(file_names, expected_file_names)

  def testTarGetNonDirFileNames(self):
    expected_file_names = {'./1.txt', './2.txt'}
    with tempfile.TemporaryDirectory() as d:
      for name in expected_file_names:
        with open(os.path.join(d, name), 'w', encoding="utf-8") as f:
          f.write('test')
      os.mkdir(os.path.join(d, 'test'))
      archive_path = CreateTarArchive(os.path.join(self.test_dir, 'test'), d)

    with output_factory_report.GetArchive(archive_path) as archive:
      file_names = set(archive.GetNonDirFileNames())
    self.assertEqual(file_names, expected_file_names)

  def testZipExtract(self):
    file_name = 'test.txt'
    content = 'test'
    with tempfile.TemporaryDirectory() as d:
      with open(os.path.join(d, file_name), 'w', encoding="utf-8") as f:
        f.write(content)
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), d)

    with output_factory_report.GetArchive(archive_path) as archive:
      with tempfile.TemporaryDirectory() as d:
        extracted_file_name = os.path.join(d, 'extracted.txt')
        archive.Extract(archive.GetNonDirFileNames()[0], extracted_file_name)
        with open(extracted_file_name, encoding="utf-8") as f:
          extracted_content = f.read()
    self.assertEqual(extracted_content, content)

  def testTarExtract(self):
    file_name = 'test.txt'
    content = 'test'
    with tempfile.TemporaryDirectory() as d:
      with open(os.path.join(d, file_name), 'w', encoding="utf-8") as f:
        f.write(content)
      archive_path = CreateTarArchive(os.path.join(self.test_dir, 'test'), d)

    with output_factory_report.GetArchive(archive_path) as archive:
      with tempfile.TemporaryDirectory() as d:
        extracted_file_name = os.path.join(d, 'extracted.txt')
        archive.Extract(archive.GetNonDirFileNames()[0], extracted_file_name)
        with open(extracted_file_name, encoding="utf-8") as f:
          extracted_content = f.read()
    self.assertEqual(extracted_content, content)


if __name__ == '__main__':
  unittest.main()
