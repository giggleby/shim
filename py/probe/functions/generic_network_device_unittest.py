#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.probe import function
from cros.factory.probe.functions import generic_network_device
from cros.factory.utils.type_utils import Obj


class NetworkDevicesTest(unittest.TestCase):

  def testGetPCIPath(self):
    pci_cellular_pci_path = '/sys/devices/pci0123:45/6789:ab:cd.e'
    pci_cellular_real_path = '/sys/devices/pci0123:45/6789:ab:cd.e'
    self.assertEqual(
        generic_network_device.NetworkDevices.GetPCIPath(
            'cellular', pci_cellular_real_path), pci_cellular_pci_path)

    pci_cellular_pci_path = '/sys/devices/pci0123:45/6789:ab:cd.e'
    pci_cellular_real_path = '/sys/devices/pci0123:45/6789:ab:cd.e/wwan/wwan0'
    self.assertEqual(
        generic_network_device.NetworkDevices.GetPCIPath(
            'cellular', pci_cellular_real_path), pci_cellular_pci_path)

    pci_wifi_pci_path = '/sys/devices/pci0123:45/6789:ab:cd.f'
    pci_wifi_real_path = '/sys/devices/pci0123:45/6789:ab:cd.f'
    self.assertEqual(
        generic_network_device.NetworkDevices.GetPCIPath(
            'wifi', pci_wifi_real_path), pci_wifi_pci_path)

    pci_bad_wifi_pci_path = '/sys/devices/pci0123:45/6789:ab:cd.e'
    pci_bad_wifi_real_path = '/sys/devices/pci0123:45/6789:ab:cd.e/wwan/wwan0'
    self.assertNotEqual(
        generic_network_device.NetworkDevices.GetPCIPath(
            'wifi', pci_bad_wifi_real_path), pci_bad_wifi_pci_path)

  @mock.patch(function.__name__ + '.InterpretFunction')
  @mock.patch(generic_network_device.__name__ + '.NetworkDevices.GetDevices')
  @mock.patch(generic_network_device.__name__ + '.NetworkDevices.GetPCIPath')
  def testReadSysfsDeviceIds(self, get_pci_path_mock: mock.MagicMock,
                             get_devices: mock.MagicMock,
                             interpret_function_mock: mock.MagicMock):

    def FakeGetPCIPath(devtype, path):
      if devtype == 'wifi':
        # Assume that wlan0 and antmon0 are the same device.
        if 'wlan0' in path or 'antmon0' in path:
          return '/sys/devices/pci0123:45/1789:ab:cd.f'
        return '/sys/devices/pci0123:45/2789:ab:cd.f'
      if devtype == 'cellular':
        return '/sys/devices/pci0123:45/3789:ab:cd.f'
      return '/sys/devices/pci0123:45/4789:ab:cd.f'

    get_pci_path_mock.side_effect = FakeGetPCIPath
    get_devices.return_value = [
        Obj(devtype='wifi', path='/sys/class/net/wlan0/device'),
        Obj(devtype='wifi', path='/sys/class/net/antmon0/device'),
        Obj(devtype='wifi', path='/sys/class/net/wlan1/device'),
        Obj(devtype='cellular', path='/sys/class/net/wwan0/device'),
        Obj(devtype='ethernet', path='/sys/class/net/eth0/device'),
    ]

    def FakeProbeDevice(unused_devtype, path):
      template = {
          'bus_type': 'pci',
          'class': '0x028000',
          'device': '0x1234',
          'revision_id': '0x00',
          'subsystem_device': '0x0000',
          'vendor': '0x4321',
      }
      template.update({'device_path': path})
      return template

    def FakeInterpretFunction(data):
      return lambda: [FakeProbeDevice(list(data)[0], list(data.values())[0])]

    interpret_function_mock.side_effect = FakeInterpretFunction

    self.assertEqual(
        generic_network_device.NetworkDevices.ReadSysfsDeviceIds('wifi'), [
            FakeProbeDevice('wifi', '/sys/devices/pci0123:45/1789:ab:cd.f'),
            FakeProbeDevice('wifi', '/sys/devices/pci0123:45/2789:ab:cd.f')
        ])

    self.assertEqual(
        generic_network_device.NetworkDevices.ReadSysfsDeviceIds('cellular'),
        [FakeProbeDevice('cellular', '/sys/devices/pci0123:45/3789:ab:cd.f')])

    self.assertEqual(
        generic_network_device.NetworkDevices.ReadSysfsDeviceIds('ethernet'),
        [FakeProbeDevice('ethernet', '/sys/devices/pci0123:45/4789:ab:cd.f')])


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
