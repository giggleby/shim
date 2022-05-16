#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil
import sys
import tempfile
import textwrap
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


class UnZipCmdCheckReportNumUnittest(unittest.TestCase):
  """Test parsing output from `unzip -l {project}_factorylog_{date}.zip`."""

  @mock.patch('cros.factory.instalog.utils.process_utils.CheckOutput')
  def testSimpleUnZipReport(self, unzip_cmd_mock):
    unzip_cmd_mock.return_value = textwrap.dedent('''\
      Archive:  coachz_factorylog_20211201-1231.zip
        Length      Date    Time    Name
      ---------  ---------- -----   ----
              0  01-06-2022 16:59   nice_factorylog_20211201-1231/
              0  01-06-2022 14:10   nice_factorylog_20211201-1231/20211201/
         278824  12-01-2021 16:24   nice_factorylog_20211201-1231/20211201/GRT-AAAAAAAAAA-20211201T082433Z.rpt.xz
         246512  12-01-2021 16:24   nice_factorylog_20211201-1231/20211201/GRT-BBBBBBBBBB-20211201T082412Z.rpt.xz
         252796  12-01-2021 14:51   nice_factorylog_20211201-1231/20211201/GRT-CCCCCCCCCC-20211201T065154Z.rpt.xz
         242416  12-01-2021 23:29   nice_factorylog_20211201-1231/20211201/GRT-DDDDDDDDDD-20211201T152936Z.rpt.xz
         210252  12-01-2021 14:46   nice_factorylog_20211201-1231/20211201/GRT-EEEEEEEEEE-20211201T064612Z.rpt.xz
         274248  12-01-2021 22:12   nice_factorylog_20211201-1231/20211201/GRT-FFFFFFFFFF-20211201T141228Z.rpt.xz
      ---------                     -------
      682265096                     8 files
    ''')
    parser = output_factory_report.ReportParser('', '', '', '')
    report_num = parser._GetReportNumInZip('')  # pylint: disable=protected-access
    self.assertEqual(6, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.CheckOutput')
  def testNoReport(self, unzip_cmd_mock):
    unzip_cmd_mock.return_value = ''
    parser = output_factory_report.ReportParser('', '', '', '')
    report_num = parser._GetReportNumInZip('')  # pylint: disable=protected-access
    self.assertEqual(0, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.CheckOutput')
  def testEncounterException(self, unzip_cmd_mock):
    unzip_cmd_mock.side_effect = Exception
    parser = output_factory_report.ReportParser('', '', '', '')
    report_num = parser._GetReportNumInZip('random_path')  # pylint: disable=protected-access
    self.assertEqual(None, report_num)


class TarCmdCheckReportNumUnittest(unittest.TestCase):
  """Test parsing output from `tar tvf {project}_factorylog_{date}.tar`."""

  @mock.patch('cros.factory.instalog.utils.process_utils.CheckOutput')
  def testSimpleTarReport(self, tar_cmd_mock):
    tar_cmd_mock.return_value = textwrap.dedent('''\
      drwxr-xr-x lschyi/primarygroup 0 2022-05-19 14:54 test/
      drwxr-xr-x lschyi/primarygroup 0 2022-05-19 14:54 test/20211201/
      -rw-r--r-- lschyi/primarygroup 274248 2022-05-19 14:54 test/20211201/GRT-AAAAAAAAAA-20211201T141228Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 242416 2022-05-19 14:54 test/20211201/GRT-BBBBBBBBBB-20211201T152936Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 278824 2022-05-19 14:54 test/20211201/GRT-CCCCCCCCCC-20211201T082433Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 246512 2022-05-19 14:54 test/20211201/GRT-DDDDDDDDDD-20211201T082412Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 252796 2022-05-19 14:54 test/20211201/GRT-EEEEEEEEEE-20211201T065154Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 210252 2022-05-19 14:54 test/20211201/GRT-FFFFFFFFFF-20211201T064612Z.rpt.xz
    ''')
    parser = output_factory_report.ReportParser('', '', '', '')
    report_num = parser._GetReportNumInTar('')  # pylint: disable=protected-access
    self.assertEqual(6, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.CheckOutput')
  def testNoReport(self, tar_cmd_mock):
    tar_cmd_mock.return_value = ''
    parser = output_factory_report.ReportParser('', '', '', '')
    report_num = parser._GetReportNumInTar('')  # pylint: disable=protected-access
    self.assertEqual(0, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.CheckOutput')
  def testEncounterException(self, tar_cmd_mock):
    tar_cmd_mock.side_effect = Exception
    parser = output_factory_report.ReportParser('', '', '', '')
    report_num = parser._GetReportNumInTar('random_path')  # pylint: disable=protected-access
    self.assertEqual(None, report_num)


if __name__ == '__main__':
  unittest.main()
