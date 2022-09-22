#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
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

  @staticmethod
  @contextlib.contextmanager
  def _PrepareTestingFileSystemStructure(files):
    """Prepare a file system structure for testing.

    Args:
      files: a dict wit the key is a relative file path to create and values is
        the file content string.
    """
    try:
      with tempfile.TemporaryDirectory() as d:
        for name, content in files.items():
          full_path = os.path.join(d, name)
          dir_name = os.path.dirname(full_path)
          if not os.path.exists(dir_name):
            os.makedirs(dir_name)
          with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        yield d
    finally:
      pass

  def _CheckExtractedContent(self, archive, archive_member_path, expected):
    with tempfile.TemporaryDirectory() as d:
      extracted_file_name = os.path.join(d, 'extracted.txt')
      archive.Extract(archive_member_path, extracted_file_name)
      with open(extracted_file_name, encoding='utf-8') as f:
        extracted_content = f.read()
    self.assertEqual(extracted_content, expected)

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

  @mock.patch('zipfile.is_zipfile')
  def testCreateZipWith7ZArchive(self, mock_is_zip_file):
    mock_is_zip_file.return_value = False
    with tempfile.TemporaryDirectory() as d:
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), d)
    archive = output_factory_report.GetArchive(archive_path)
    self.assertIsInstance(archive, output_factory_report.ZipWith7ZArchive)

  def testZipGetNonDirFileNames(self):
    expected_files = {
        '1.txt': '',
        '2.txt': ''
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.GetArchive(archive_path) as archive:
      file_names = set(archive.GetNonDirFileNames())
    self.assertEqual(file_names, expected_files.keys())

  def testTarGetNonDirFileNames(self):
    expected_files = {
        './1.txt': '',
        './2.txt': ''
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateTarArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.GetArchive(archive_path) as archive:
      file_names = set(archive.GetNonDirFileNames())
    self.assertEqual(file_names, expected_files.keys())

  def testZipWith7ZGetNonDirFileNames(self):
    expected_files = {
        '1.txt': '',
        '2.txt': ''
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.ZipWith7ZArchive(archive_path) as archive:
      file_names = set(archive.GetNonDirFileNames())
    self.assertEqual(file_names, expected_files.keys())

  def testZipExtract(self):
    expected_files = {
        'test.txt': 'test'
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.GetArchive(archive_path) as archive:
      self._CheckExtractedContent(archive,
                                  archive.GetNonDirFileNames()[0],
                                  next(iter(expected_files.values())))

  def testTarExtract(self):
    expected_files = {
        'test.txt': 'test'
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateTarArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.GetArchive(archive_path) as archive:
      self._CheckExtractedContent(archive,
                                  archive.GetNonDirFileNames()[0],
                                  next(iter(expected_files.values())))

  def testZipWith7ZExtract(self):
    expected_files = {
        'test.txt': 'test'
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.ZipWith7ZArchive(archive_path) as archive:
      self._CheckExtractedContent(archive,
                                  archive.GetNonDirFileNames()[0],
                                  next(iter(expected_files.values())))

  def testZipWith7ZExtractDeepFile(self):
    expected_files = {
        'random_path/test.txt': 'test'
    }
    with ArchiveUnittest._PrepareTestingFileSystemStructure(
        expected_files) as path:
      os.mkdir(os.path.join(path, 'test'))
      archive_path = CreateZipArchive(os.path.join(self.test_dir, 'test'), path)

    with output_factory_report.ZipWith7ZArchive(archive_path) as archive:
      self._CheckExtractedContent(archive,
                                  archive.GetNonDirFileNames()[0],
                                  next(iter(expected_files.values())))


class ZipWith7ZUnittest(unittest.TestCase):

  @mock.patch('cros.factory.instalog.utils.process_utils.SpawnOutput')
  def testNormal7ZListOutput(self, mock_7z_cmd):
    mock_7z_cmd.return_value = textwrap.dedent('''\
      Path = sh/stub_startup.sh
      Size = 813
      Packed Size =
      Modified = 2022-07-05 16:04:03
      Attributes = A_ -rwxr-xr-x
      CRC = 24617276
      Encrypted = -
      Method = LZMA2:17
      Block = 0

      Path = sh/cutoff.sh
      Size = 813
      Packed Size =
      Modified = 2022-07-05 16:04:03
      Attributes = A_ -rwxr-xr-x
      CRC = 24617276
      Encrypted = -
      Method = LZMA2:17
      Block = 0

    ''')
    expected = set(['sh/stub_startup.sh', 'sh/cutoff.sh'])
    with output_factory_report.ZipWith7ZArchive('mock_path') as archive:
      self.assertEqual(set(archive.GetNonDirFileNames()), expected)

  # Due to version difference (version number and platform 7z version), the list
  # format may change.
  @mock.patch('cros.factory.instalog.utils.process_utils.SpawnOutput')
  def testAttributesRightAfterPath7ZListOutput(self, mock_7z_cmd):
    mock_7z_cmd.return_value = textwrap.dedent('''\
      Path = sh/stub_startup.sh
      Attributes = A_ -rwxr-xr-x
      Size = 813
      Packed Size =
      Modified = 2022-07-05 16:04:03
      CRC = 24617276
      Encrypted = -
      Method = LZMA2:17
      Block = 0

    ''')
    expected = ['sh/stub_startup.sh']
    with output_factory_report.ZipWith7ZArchive('mock_path') as archive:
      self.assertEqual(archive.GetNonDirFileNames(), expected)

  @mock.patch('cros.factory.instalog.utils.process_utils.SpawnOutput')
  def testAttributesAtLast7ZListOutput(self, mock_7z_cmd):
    mock_7z_cmd.return_value = textwrap.dedent('''\
      Path = sh/stub_startup.sh
      Size = 813
      Packed Size =
      Modified = 2022-07-05 16:04:03
      CRC = 24617276
      Encrypted = -
      Method = LZMA2:17
      Block = 0
      Attributes = A_ -rwxr-xr-x

    ''')
    expected = ['sh/stub_startup.sh']
    with output_factory_report.ZipWith7ZArchive('mock_path') as archive:
      self.assertEqual(archive.GetNonDirFileNames(), expected)


class UnZipCmdCheckReportNumUnittest(unittest.TestCase):
  """Test parsing output from `unzip -l {project}_factorylog_{date}.zip`."""

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testSimpleUnZipReport(self, unzip_cmd_mock):
    stdout = textwrap.dedent('''\
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
    unzip_cmd_mock.return_value.returncode = 0
    unzip_cmd_mock.return_value.communicate.return_value = (stdout, '')

    parser = output_factory_report.ReportParser('', '', '', 0, '')
    report_num = parser._GetReportNumInZip('')  # pylint: disable=protected-access
    self.assertEqual(6, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testEmptyZip(self, unzip_cmd_mock):
    stdout = 'Archive:  empty.zip\n'
    stderr = 'warning [empty.zip]:  zipfile is empty\n'
    unzip_cmd_mock.return_value.returncode = 1
    unzip_cmd_mock.return_value.communicate.return_value = (stdout, stderr)
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    report_num = parser._GetReportNumInZip('')  # pylint: disable=protected-access
    self.assertEqual(0, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testEncounterException(self, unzip_cmd_mock):
    unzip_cmd_mock.return_value.returncode = 9
    unzip_cmd_mock.return_value.communicate.return_value = ('', '')
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    report_num = parser._GetReportNumInZip('random_path')  # pylint: disable=protected-access
    self.assertEqual(None, report_num)


class TarCmdCheckReportNumUnittest(unittest.TestCase):
  """Test parsing output from `tar tvf {project}_factorylog_{date}.tar`."""

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testSimpleTarReport(self, tar_cmd_mock):
    stdout = textwrap.dedent('''\
      drwxr-xr-x lschyi/primarygroup 0 2022-05-19 14:54 test/
      drwxr-xr-x lschyi/primarygroup 0 2022-05-19 14:54 test/20211201/
      -rw-r--r-- lschyi/primarygroup 274248 2022-05-19 14:54 test/20211201/GRT-AAAAAAAAAA-20211201T141228Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 242416 2022-05-19 14:54 test/20211201/GRT-BBBBBBBBBB-20211201T152936Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 278824 2022-05-19 14:54 test/20211201/GRT-CCCCCCCCCC-20211201T082433Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 246512 2022-05-19 14:54 test/20211201/GRT-DDDDDDDDDD-20211201T082412Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 252796 2022-05-19 14:54 test/20211201/GRT-EEEEEEEEEE-20211201T065154Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 210252 2022-05-19 14:54 test/20211201/GRT-FFFFFFFFFF-20211201T064612Z.rpt.xz
    ''')
    tar_cmd_mock.return_value.returncode = 0
    tar_cmd_mock.return_value.communicate.return_value = (stdout, '')

    parser = output_factory_report.ReportParser('', '', '', 0, '')
    # pylint: disable=protected-access
    report_num = parser._GetReportNumInTar('', {
        'status': [],
        'message': []
    })
    # pylint: enable=protected-access
    self.assertEqual(6, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testCorruptedTarReport(self, tar_cmd_mock):
    stdout = textwrap.dedent('''\
      drwxr-xr-x lschyi/primarygroup 0 2022-05-19 14:54 test/
      drwxr-xr-x lschyi/primarygroup 0 2022-05-19 14:54 test/20211201/
      -rw-r--r-- lschyi/primarygroup 274248 2022-05-19 14:54 test/20211201/GRT-AAAAAAAAAA-20211201T141228Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 242416 2022-05-19 14:54 test/20211201/GRT-BBBBBBBBBB-20211201T152936Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 278824 2022-05-19 14:54 test/20211201/GRT-CCCCCCCCCC-20211201T082433Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 246512 2022-05-19 14:54 test/20211201/GRT-DDDDDDDDDD-20211201T082412Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 252796 2022-05-19 14:54 test/20211201/GRT-EEEEEEEEEE-20211201T065154Z.rpt.xz
      -rw-r--r-- lschyi/primarygroup 210252 2022-05-19 14:54 test/20211201/GRT-FFFFFFFFFF-20211201T064612Z.rpt.xz
    ''')

    stderr = textwrap.dedent('''\

      gzip: stdin: unexpected end of file
      tar: Unexpected EOF in archive
      tar: Error is not recoverable: exiting now
    ''')
    tar_cmd_mock.return_value.returncode = 2
    tar_cmd_mock.return_value.communicate.return_value = (stdout, stderr)

    parser = output_factory_report.ReportParser('', '', '', 0, '')
    # pylint: disable=protected-access
    report_num = parser._GetReportNumInTar('', {
        'status': [],
        'message': []
    })
    # pylint: enable=protected-access
    self.assertEqual(6, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testNoReport(self, tar_cmd_mock):
    tar_cmd_mock.return_value.returncode = 0
    tar_cmd_mock.return_value.communicate.return_value = ('', '')
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    # pylint: disable=protected-access
    report_num = parser._GetReportNumInTar('', {
        'status': [],
        'message': []
    })
    # pylint: enable=protected-access
    self.assertEqual(0, report_num)

  @mock.patch('cros.factory.instalog.utils.process_utils.Spawn')
  def testEncounterException(self, tar_cmd_mock):
    tar_cmd_mock.return_value.returncode = 2
    tar_cmd_mock.return_value.communicate.return_value = ('', '')
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    # pylint: disable=protected-access
    report_num = parser._GetReportNumInTar('random_path', {
        'status': [],
        'message': []
    })
    # pylint: enable=protected-access
    self.assertEqual(None, report_num)


class ExtractHWIDFromFactoryLogUnittest(unittest.TestCase):
  """Tests extracting HWID from factory.log."""

  HWID_LOG_TEMPLATE = b'main_generic:RunIn.Prepare.WriteHWID> [INFO] main_generic:RunIn.Prepare.WriteHWID hwid.py:217 2022-01-01 00:00:00.000 Generated HWID: '  # pylint: disable=line-too-long

  @contextlib.contextmanager
  def _CreateFactoryLogFile(self, pre_placeholder, after_placeholder):
    """Contextlib method which sets up the testing log.

    Arg:
      pre_placeholder: bytes data before testing placeholder log write in the
        testing factory log file. Can be `None` to write nothing before the
        testing placeholder.
      after_placeholder: bytes data after testing placeholder log write in the
        testing factory log file. Can be `None` to write nothing after the
        testing placeholder.

    Yields:
      A string of the factory log file path.
    """
    log_place_holder = textwrap.dedent('''\
        --- 202200101 00:00:00 Starting new Goofy session () ---
      Device ID: XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
      [INFO] goofy.py session.py:106 2022-01-01 00:00:00.000 Session (Goofy) init count = 0
      ''').encode('utf-8')

    f = tempfile.NamedTemporaryFile()
    try:
      if pre_placeholder is not None:
        f.write(pre_placeholder)
      f.write(log_place_holder)
      if after_placeholder is not None:
        f.write(after_placeholder)
      f.flush()
      yield f.name
    finally:
      f.close()

  @staticmethod
  def _CreateHWIDLogLine(hwid):
    """Creates a WriteHWID log line.

    Arg:
      hwid: string of the hwid appears in the log line.

    Returns:
      Bytes of the log line.
    """
    return ExtractHWIDFromFactoryLogUnittest.HWID_LOG_TEMPLATE + hwid.encode(
        'utf-8') + b'\n'

  def testOneMatchHWID(self):
    expected_hwid = 'GENERIC-XXXX XXX-XXX-XXX-XXX-XXX'
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    hwid_log = self._CreateHWIDLogLine(expected_hwid)
    with self._CreateFactoryLogFile(None, hwid_log) as path:
      extracted_hwid = parser._ExtractHWIDFromFactoryLog(path)  # pylint: disable=protected-access
    self.assertEqual(expected_hwid, extracted_hwid)

  def testMatchLastHWID(self):
    expected_hwid = 'GENERIC-XXXX XXX-XXX-XXX-XXX-XXX'
    mid_hwid = expected_hwid.replace('XXX', 'AAA')
    hwid_log = self._CreateHWIDLogLine(mid_hwid) + self._CreateHWIDLogLine(
        expected_hwid)

    parser = output_factory_report.ReportParser('', '', '', 0, '')
    with self._CreateFactoryLogFile(None, hwid_log) as path:
      extracted_hwid = parser._ExtractHWIDFromFactoryLog(path)  # pylint: disable=protected-access
    self.assertEqual(expected_hwid, extracted_hwid)

  def testNoHWIDMatch(self):
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    with self.assertRaises(output_factory_report.HWIDNotFoundInFactoryLogError
                          ), self._CreateFactoryLogFile(None, None) as path:
      parser._ExtractHWIDFromFactoryLog(path)  # pylint: disable=protected-access

  def testNonUTF8EncodingCharacterInLog(self):
    expected_hwid = 'GENERIC-XXXX XXX-XXX-XXX-XXX-XXX'
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    hwid_log = self._CreateHWIDLogLine(expected_hwid) + b'\xae'
    with self._CreateFactoryLogFile(b'\xae', hwid_log) as path:
      extracted_hwid = parser._ExtractHWIDFromFactoryLog(path)  # pylint: disable=protected-access
    self.assertEqual(expected_hwid, extracted_hwid)

  def testCorruptedHWIDField(self):
    parser = output_factory_report.ReportParser('', '', '', 0, '')
    hwid_log = self.HWID_LOG_TEMPLATE + 'GENERIC-XXXX'.encode('utf-8') + b'\xae'
    with self.assertRaises(output_factory_report.HWIDNotFoundInFactoryLogError
                          ), self._CreateFactoryLogFile(None, hwid_log) as path:
      parser._ExtractHWIDFromFactoryLog(path)  # pylint: disable=protected-access


if __name__ == '__main__':
  unittest.main()
