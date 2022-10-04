#!/usr/bin/env python3
# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import unittest
from unittest import mock

from cros.factory.device import storage


class StorageDictTest(unittest.TestCase):
  """Unittest for DUT storage Dict APIs."""

  def setUp(self):
    self.dut = mock.MagicMock()
    self.storage = storage.Storage(self.dut)
    self.dict_file_path = '/path/to/dict/file'
    self.storage.GetDictFilePath = lambda: self.dict_file_path

  def testLoadDictFileNotExists(self):
    self.dut.path.exists = mock.Mock(return_value=False)

    self.assertEqual({}, self.storage.LoadDict())

    self.dut.path.exists.assert_called_with(self.dict_file_path)

  def testLoadDictFileExists(self):
    data = {'k1': 'v1', 'k2': 123}
    self.dut.path.exists = mock.Mock(return_value=True)
    self.dut.ReadFile = mock.Mock(return_value=json.dumps(data))

    self.assertEqual(data, self.storage.LoadDict())

    self.dut.path.exists.assert_called_with(self.dict_file_path)
    self.dut.ReadFile.assert_called_with(self.dict_file_path)

  def testLoadDictInvalidJSONFormat(self):
    self.dut.path.exists = mock.Mock(return_value=True)
    self.dut.ReadFile = mock.Mock(return_value='!@#$%^&*()[]{}')

    self.assertEqual({}, self.storage.LoadDict())

    self.dut.path.exists.assert_called_with(self.dict_file_path)
    self.dut.ReadFile.assert_called_with(self.dict_file_path)

  def testLoadDictNotDictionary(self):
    data = [('k1', 'v1'), ('k2', 123)]
    self.dut.path.exists = mock.Mock(return_value=True)
    self.dut.ReadFile = mock.Mock(return_value=json.dumps(data))

    self.assertEqual({}, self.storage.LoadDict())

    self.dut.path.exists.assert_called_with(self.dict_file_path)
    self.dut.ReadFile.assert_called_with(self.dict_file_path)

  def testSaveDictNotDictionary(self):
    data = [('k1', 'v1'), ('k2', 123)]
    with self.assertRaises(AssertionError):
      self.storage.SaveDict(data)

  def testSaveDictIgnoreNonStringKeys(self):
    data = {1: 'int', '1': 'str', 2: 'int', 3.5: 'float'}
    saved_data = {'1': 'str'}
    saved_string = json.dumps(saved_data, sort_keys=True)
    dict_file_dirname = '/path/to/dir'

    self.dut.path.dirname = mock.Mock(return_value=dict_file_dirname)

    self.assertEqual(self.storage.SaveDict(data), saved_data)

    self.dut.CheckCall.assert_called_with(['mkdir', '-p', dict_file_dirname])
    self.dut.path.dirname.assert_called_with(self.dict_file_path)
    self.dut.WriteFile.assert_called_with(self.dict_file_path, saved_string)

  def testUpdateDict(self):
    data = {'a': 'b', 'c': 'd'}
    update = {'c': 'x', 'k': 'v'}
    updated_data = {'a': 'b', 'c': 'x', 'k': 'v'}
    return_value = 'MOCKED_RETURN_VALUE'

    self.storage.LoadDict = mock.Mock(return_value=data)
    self.storage.SaveDict = mock.Mock(return_value=return_value)

    self.assertEqual(return_value,
                     self.storage.UpdateDict(update))

    self.storage.LoadDict.assert_called_with()
    self.storage.SaveDict.assert_called_with(updated_data)

  def testDeleteDictKeyExists(self):
    data = {'a': 'b', 'c': 'd'}
    updated_data = {'c': 'd'}
    return_value = 'MOCKED_RETURN_VALUE'

    self.storage.LoadDict = mock.Mock(return_value=data)
    self.storage.SaveDict = mock.Mock(return_value=return_value)

    self.assertEqual(updated_data, self.storage.DeleteDict('a'))

    self.storage.LoadDict.assert_called_with()
    self.storage.SaveDict.assert_called_with(updated_data)

  def testDeleteDictKeyNotExists(self):
    data = {'a': 'b', 'c': 'd'}
    return_value = 'MOCKED_RETURN_VALUE'

    self.storage.LoadDict = mock.Mock(return_value=data)
    self.storage.SaveDict = mock.Mock(return_value=return_value)

    self.assertEqual(data, self.storage.DeleteDict('k'))

    self.storage.LoadDict.assert_called_with()
    self.storage.SaveDict.assert_not_called()


class StorageDevicePathTest(unittest.TestCase):

  def setUp(self):
    self.dut = mock.MagicMock()
    self.storage = storage.Storage(self.dut)

  def testEMMCStorage(self):
    mount_point = ['/usr/share/oem', '/dev/mmcblk0p8']
    self.storage.GetMountPoint = mock.Mock(return_value=mount_point)
    dev = self.storage.GetMainStorageDevice()
    part1_dev = self.storage.GetMainStorageDevice(partition=1)

    self.assertEqual(dev, '/dev/mmcblk0')
    self.assertEqual(part1_dev, '/dev/mmcblk0p1')

  def testUFSStorage(self):
    mount_point = ['/usr/share/oem', '/dev/sda8']
    self.storage.GetMountPoint = mock.Mock(return_value=mount_point)
    dev = self.storage.GetMainStorageDevice()
    part1_dev = self.storage.GetMainStorageDevice(partition=1)

    self.assertEqual(dev, '/dev/sda')
    self.assertEqual(part1_dev, '/dev/sda1')


class MainStorageTypeTest(unittest.TestCase):

  def setUp(self):
    self.dut = mock.MagicMock()
    self.storage = storage.Storage(self.dut)
    self.storage.GetMainStorageDevice = mock.MagicMock()

  def testNVMe(self):
    self.dut.path.basename.return_value = 'nvme0n1'
    self.assertEqual(storage.MainStorageType.NVME,
                     self.storage.GetMainStorageType())

  def testEMMC(self):
    self.dut.path.basename.return_value = 'mmcblk0'
    self.dut.path.realpath.return_value = (
        '/sys/devices/pci0000:00/0000:00:1a.0/mmc_host/mmc1/mmc1:0001')
    self.dut.ReadFile.return_value = 'MMC'
    self.assertEqual(storage.MainStorageType.MMC,
                     self.storage.GetMainStorageType())

  def testUSB(self):
    self.dut.path.basename.return_value = 'sda'
    self.dut.path.realpath.return_value = (
        '/sys/devices/pci0000:00/0000:00:14.0/usb4/4-1/4-1:1.0/host1'
        '/target1:0:0/1:0:0:0')
    self.assertEqual(storage.MainStorageType.USB,
                     self.storage.GetMainStorageType())

  def testUFS(self):
    self.dut.path.basename.return_value = 'sda'
    self.dut.path.realpath.return_value = (
        '/sys/devices/pci0000:00/0000:00:12.7/host0/ufs0:0:0/0:0:0:0')
    self.assertEqual(storage.MainStorageType.UFS,
                     self.storage.GetMainStorageType())

  def testUFSDriver(self):
    self.dut.path.basename.return_value = 'sda'
    self.dut.path.realpath.side_effect = [
        '/sys/devices/pci0000:00/0000:00:12.7/host0/target0:0:0/0:0:0:0',
        '/sys/devices/pci0000:00/0000:00:12.7/host0/target0:0:0/0:0:0:0/driver',
        '/sys/bus/pci/drivers/ufshcd'
    ]
    self.assertEqual(storage.MainStorageType.UFS,
                     self.storage.GetMainStorageType())

  def testOther(self):
    self.dut.path.basename.return_value = 'sda'
    self.dut.path.realpath.return_value = (
        '/sys/devices/pci0000:00/0000:00:12.7/host0/other0:0:0/0:0:0:0')
    self.assertEqual(storage.MainStorageType.OTHER,
                     self.storage.GetMainStorageType())


if __name__ == '__main__':
  unittest.main()
