#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import os.path
import tempfile
import unittest
from unittest import mock

from cros.factory.probe.functions import smart_card_usb
from cros.factory.probe.functions import sysfs
from cros.factory.utils import file_utils


class SmartCardUSBFunctionTest(unittest.TestCase):

  def setUp(self):
    # The fake root dir holds files that the probe function reads data from.
    # The path prefix is deliberately designed to have a suffix "/./" so that
    # ordinary paths, no matter if it's an absolute one or not, can append
    # to it to "rebase".
    self._fake_root_prefix = os.path.join(tempfile.mkdtemp(), '.', '')

    self._real_glob = glob.glob
    self._real_readsysfs = sysfs.ReadSysfs

    patcher = mock.patch('cros.factory.probe.functions.sysfs.ReadSysfs',
                         side_effect=self._FakeReadSysfs)
    patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('glob.glob', side_effect=self._FakeGlob)
    patcher.start()
    self.addCleanup(patcher.stop)

  def _CreateFileAndParentDirs(self, pathname, data):
    file_utils.TryMakeDirs(self._PatchPath(os.path.dirname(pathname)))
    file_utils.WriteFile(self._PatchPath(pathname), data)

  def testProbeASmartCardReader(self):
    # The following files represent a smart card reader device.
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/1-1/idVendor', '1234')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/1-1/idProduct', '5678')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/1-1/1-1:1.0/bInterfaceClass', '0b')
    # The following files don't represent a smart card reader device.
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/1-2/idVendor', '1357')
    self._CreateFileAndParentDirs('/sys/bus/usb/devices/1-2/idProduct', '2468')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/1-2/1-2:1.0/bInterfaceClass', '09')
    self._CreateFileAndParentDirs(
        '/sys/bus/usb/devices/1-2/1-2:2.0/bInterfaceClass', 'xyz123')

    probe_function = smart_card_usb.SmartCardUSBFunction()
    results = probe_function.Probe()

    self.assertCountEqual(results, [{
        'idVendor': '1234',
        'idProduct': '5678',
        'bus_type': 'usb',
        'device_path': '/sys/bus/usb/devices/1-1',
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
