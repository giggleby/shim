#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import os.path
import shutil
import tempfile
import unittest
from unittest import mock

from cros.factory.probe.functions import nfc_reader
from cros.factory.probe.functions import sysfs
from cros.factory.utils import file_utils


class NFCUSBFunctionTest(unittest.TestCase):

  def setUp(self):
    # The fake root dir holds files that the probe function reads data from.
    # The path prefix is deliberately designed to have a suffix "/./" so that
    # ordinary paths, no matter if it's an absolute one or not, can append
    # to it to "rebase".
    self._temp_dir = tempfile.mkdtemp()
    self._fake_root_prefix = os.path.join(self._temp_dir, '.', '')

    self._real_glob = glob.glob
    self._real_readsysfs = sysfs.ReadSysfs

    patcher = mock.patch('cros.factory.probe.functions.sysfs.ReadSysfs',
                         side_effect=self._FakeReadSysfs)
    patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('glob.glob', side_effect=self._FakeGlob)
    patcher.start()
    self.addCleanup(patcher.stop)

  def tearDown(self):
    shutil.rmtree(self._temp_dir)

  def _CreateFileAndParentDirs(self, pathname, data):
    file_utils.TryMakeDirs(self._PatchPath(os.path.dirname(pathname)))
    file_utils.WriteFile(self._PatchPath(pathname), data)

  def testProbeANfcReader(self):
    # The following files represent a NFC reader device.
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-5/idVendor', '1234')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-5/idProduct', '5678')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-5/removable', 'fixed')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/3-5/3-5:1.0/bInterfaceClass', '03')
    # The following files don't represent a NFC reader device because it's
    # removable.
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-9/idVendor', '1357')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-9/idProduct', '2468')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-9/removable',
                                  'removable')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/3-9/3-9:1.0/bInterfaceClass', '03')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/3-9/3-9:2.0/bInterfaceClass', 'xyz123')
    # The following files don't represent a NFC reader device because its
    # bInterfaceClass is not 03.
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-6/idVendor', '4321')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-6/idProduct', '8765')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/3-6/removable', 'fixed')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/3-6/3-6:1.0/bInterfaceClass', '0b')

    probe_function = nfc_reader.NFCUSBFunction()
    results = probe_function.Probe()

    self.assertCountEqual(results, [{
        'idVendor': '1234',
        'idProduct': '5678',
        'removable': 'fixed',
        'bus_type': 'usb',
        'device_path': '/sys/bus/usb/devices/3-5',
    }])

  def _FakeReadSysfs(self, dir_path, required_keys, optional_keys=None):
    return self._real_readsysfs(
        self._PatchPath(dir_path), required_keys, optional_keys=optional_keys)

  def _FakeGlob(self, pattern):
    return [
        self._UnpatchPath(p) for p in self._real_glob(self._PatchPath(pattern))
    ]

  def _PatchPath(self, path):
    return self._fake_root_prefix + path

  def _UnpatchPath(self, path):
    return path[len(self._fake_root_prefix):]


if __name__ == '__main__':
  unittest.main()
