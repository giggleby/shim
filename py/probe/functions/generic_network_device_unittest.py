#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.probe.functions import generic_network_device


class GenericNetworkDeviceFunctionTest(unittest.TestCase):

  @mock.patch(
      generic_network_device.__name__ + '.NetworkDevices.ReadSysfsDeviceIds')
  def testProbeEthernet(self, read_sysfs_device_ids_mock: mock.MagicMock):
    _PCI_ETHERNET = {
        'bus_type': 'pci',
        'class': '0x028000',
        'device': '0x1234',
        'revision_id': '0x00',
        'subsystem_device': '0x0000',
        'vendor': '0x4321',
        'device_path': '/sys/devices/pci0123:45/4789:ab:cd.f'
    }
    _INTERNAL_USB_ETHERNET = {
        'bus_type': 'usb',
        'class': '0x028000',
        'device': '0x1234',
        'revision_id': '0x00',
        'subsystem_device': '0x0000',
        'vendor': '0x4321',
        'device_path': '/sys/bus/usb/devices/1-2',
        'removable': 'fixed'
    }
    _EXTERNAL_USB_ETHERNET = {
        'bus_type': 'usb',
        'class': '0x028000',
        'device': '0x1234',
        'revision_id': '0x00',
        'subsystem_device': '0x0000',
        'vendor': '0x4321',
        'device_path': '/sys/bus/usb/devices/2-3',
        'removable': 'removable'
    }
    _FAKE_ETHERNET_DEVICES = [
        _PCI_ETHERNET, _INTERNAL_USB_ETHERNET, _EXTERNAL_USB_ETHERNET
    ]
    read_sysfs_device_ids_mock.return_value = _FAKE_ETHERNET_DEVICES
    result = generic_network_device.GenericNetworkDeviceFunction.ProbeEthernet()
    expected_result = [_PCI_ETHERNET, _INTERNAL_USB_ETHERNET]
    self.assertCountEqual(result, expected_result)


if __name__ == '__main__':
  unittest.main()
