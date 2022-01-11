#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.probe.functions import generic_network_device


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


if __name__ == '__main__':
  unittest.main()
