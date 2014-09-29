#!/usr/bin/env python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Unittest for file_utils.py."""


import mock
import os
import re
import tempfile
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn


class MountDeviceAndReadFileTest(unittest.TestCase):
  """Unittest for MountDeviceAndReadFile."""
  def setUp(self):
    # Creates a temp file and create file system on it as a mock device.
    self.device = tempfile.NamedTemporaryFile(prefix='MountDeviceAndReadFile')
    Spawn(['truncate', '-s', '1M', self.device.name], log=True, check_call=True)
    Spawn(['/sbin/mkfs', '-F', '-t', 'ext3', self.device.name],
          log=True, check_call=True)

    # Creates a file with some content on the device.
    mount_point = tempfile.mkdtemp(prefix='MountDeviceAndReadFileSetup')
    Spawn(['mount', self.device.name, mount_point], sudo=True, check_call=True,
          log=True)
    self.content = 'file content'
    self.file_name = 'file'
    with open(os.path.join(mount_point, self.file_name), 'w') as f:
      f.write(self.content)
    Spawn(['umount', '-l', mount_point], sudo=True, check_call=True, log=True)

  def tearDown(self):
    self.device.close()

  def testMountDeviceAndReadFile(self):
    self.assertEqual(self.content,
        file_utils.MountDeviceAndReadFile(self.device.name, self.file_name))

  def testMountDeviceAndReadFileWrongFile(self):
    with self.assertRaises(IOError):
      file_utils.MountDeviceAndReadFile(self.device.name, 'no_file')

  def testMountDeviceAndReadFileWrongDevice(self):
    with self.assertRaises(Exception):
      file_utils.MountDeviceAndReadFile('no_device', self.file_name)


class UnopenedTemporaryFileTest(unittest.TestCase):
  """Unittest for UnopenedTemporaryFile."""
  def testUnopenedTemporaryFile(self):
    with file_utils.UnopenedTemporaryFile(
        prefix='prefix', suffix='suffix') as x:
      self.assertTrue(os.path.exists(x))
      self.assertEquals(0, os.path.getsize(x))
      assert re.match('prefix.+suffix', os.path.basename(x))
      self.assertEquals(tempfile.gettempdir(), os.path.dirname(x))
    self.assertFalse(os.path.exists(x))

class ReadLinesTest(unittest.TestCase):
  """Unittest for ReadLines."""
  def testNormalFile(self):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write('line 1\nline 2\n')
    tmp.close()
    try:
      lines = file_utils.ReadLines(tmp.name)
      self.assertEquals(len(lines), 2)
      self.assertEquals(lines[0], 'line 1\n')
      self.assertEquals(lines[1], 'line 2\n')
    finally:
      os.unlink(tmp.name)

  def testEmptyFile(self):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    try:
      lines = file_utils.ReadLines(tmp.name)
      self.assertTrue(isinstance(lines, list))
      self.assertEquals(len(lines), 0)
    finally:
      os.unlink(tmp.name)

  def testNonExistFile(self):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    os.unlink(tmp.name)

    lines = file_utils.ReadLines(tmp.name)
    self.assertTrue(lines is None)

class TempDirectoryTest(unittest.TestCase):
  """Unittest for TempDirectory."""
  def runTest(self):
    with file_utils.TempDirectory(prefix='abc') as d:
      self.assertTrue(os.path.basename(d).startswith('abc'))
      self.assertTrue(os.path.isdir(d))
    self.assertFalse(os.path.exists(d))


class CopyFileSkipBytesTest(unittest.TestCase):
  """Unittest for CopyFileSkipBytes."""
  def setUp(self):
    self.in_file = None
    self.out_file = None

  def tearDown(self):
    if self.in_file:
      os.unlink(self.in_file.name)
    if self.out_file:
      os.unlink(self.out_file.name)

  def PrepareFile(self, in_file_content, out_file_content):
    self.in_file = tempfile.NamedTemporaryFile(delete=False)
    if in_file_content:
      self.in_file.write(in_file_content)
    self.in_file.close()
    self.out_file = tempfile.NamedTemporaryFile(delete=False)
    if out_file_content:
      self.out_file.write(out_file_content)
    self.out_file.close()

  def testNormal(self):
    self.PrepareFile('1234567890', '')
    file_utils.CopyFileSkipBytes(self.in_file.name, self.out_file.name, 3)
    with open(self.out_file.name, 'r') as o:
      result = o.read()
      self.assertEquals(result, '4567890')

  def testSkipTooMany(self):
    self.PrepareFile('1234567890', '')
    # Skip too many bytes.
    self.assertRaises(ValueError, file_utils.CopyFileSkipBytes,
                      self.in_file.name, self.out_file.name, 100)
    with open(self.out_file.name, 'r') as o:
      self.assertEquals(len(o.read()), 0)

  def testNoInput(self):
    self.PrepareFile('abc', '')
    self.assertRaises(OSError, file_utils.CopyFileSkipBytes,
                      'no_input', self.out_file.name, 1)

  def testOverrideOutput(self):
    self.PrepareFile('1234567890', 'abcde')
    file_utils.CopyFileSkipBytes(self.in_file.name, self.out_file.name, 3)
    with open(self.out_file.name, 'r') as o:
      result = o.read()
      self.assertEquals(result, '4567890')

  def testSkipLargeFile(self):
    # 10000 bytes input.
    self.PrepareFile('1234567890' * 1000, '')
    file_utils.CopyFileSkipBytes(self.in_file.name, self.out_file.name, 5)
    with open(self.out_file.name, 'r') as o:
      result = o.read()
      self.assertEquals(len(result), 10000 - 5)
      self.assertTrue(result.startswith('67890'))


class ExtractFileTest(unittest.TestCase):
  """Unit tests for ExtractFile."""
  @mock.patch.object(file_utils, 'Spawn', return_value=True)
  def testExtractZip(self, mock_spawn):
    file_utils.ExtractFile('foo.zip', 'foo_dir')
    mock_spawn.assert_called_with(['unzip', '-o', 'foo.zip', '-d', 'foo_dir'],
                                  log=True, check_call=True)

    file_utils.ExtractFile('foo.zip', 'foo_dir', only_extracts=['bar', 'buz'])
    mock_spawn.assert_called_with(['unzip', '-o', 'foo.zip', '-d', 'foo_dir',
                                   'bar', 'buz'], log=True, check_call=True)

    file_utils.ExtractFile('foo.zip', 'foo_dir', only_extracts=['bar', 'buz'],
                           overwrite=False)
    mock_spawn.assert_called_with(['unzip', 'foo.zip', '-d', 'foo_dir',
                                   'bar', 'buz'], log=True, check_call=True)

  @mock.patch.object(file_utils, 'Spawn', return_value=True)
  def testExtractTar(self, mock_spawn):
    file_utils.ExtractFile('foo.tar.gz', 'foo_dir')
    mock_spawn.assert_called_with(['tar', '-xvvf', 'foo.tar.gz', '-C',
                                   'foo_dir'], log=True, check_call=True)

    file_utils.ExtractFile('foo.tbz2', 'foo_dir', only_extracts=['bar', 'buz'])
    mock_spawn.assert_called_with(['tar', '-xvvf', 'foo.tbz2', '-C', 'foo_dir',
                                   'bar', 'buz'], log=True, check_call=True)

    file_utils.ExtractFile('foo.tar.xz', 'foo_dir', only_extracts='bar',
                           overwrite=False)
    mock_spawn.assert_called_with(['tar', '-xvvf', '--keep-old-files',
                                   'foo.tar.xz', '-C', 'foo_dir', 'bar'],
                                  log=True, check_call=True)



class ReadWriteFileTest(unittest.TestCase):
  def runTest(self):
    with file_utils.UnopenedTemporaryFile() as tmp:
      data = 'abc\n\0'
      file_utils.WriteFile(tmp, data)
      self.assertEquals(data, file_utils.ReadFile(tmp))


class GlobSingleFileTest(unittest.TestCase):
  def runTest(self):
    with file_utils.TempDirectory() as d:
      for f in ('a', 'b'):
        file_utils.TouchFile(os.path.join(d, f))

      self.assertEquals(
          os.path.join(d, 'a'),
          file_utils.GlobSingleFile(os.path.join(d, '[a]')))
      self.assertRaisesRegexp(
          ValueError,
          r"Expected one match for .+/\* but got "
          r"\['.+/(a|b)', '.+/(a|b)'\]",
          file_utils.GlobSingleFile, os.path.join(d, '*'))
      self.assertRaisesRegexp(
          ValueError,
          r"Expected one match for .+/nomatch but got \[\]",
          file_utils.GlobSingleFile, os.path.join(d, 'nomatch'))



if __name__ == '__main__':
  unittest.main()
