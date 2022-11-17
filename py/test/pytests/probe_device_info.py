# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A factory test for probe device information and update to device data.

Description
-----------
A factory test for probe device information and update to device data.

Test Procedure
--------------
This is an automated test without user interaction.

Dependency
----------
- Device Data API (``cros.factory.test.device_data``).
- Bluetooth utility (``cros.factory.test.utils.bluetooth_utils``).
- Device utility (``cros.factory.device.device_utils``).

Examples
--------
Probe Wi-Fi and Bluetooth MAC address, rw firmware version, release image
version, manufacturer date, update to device data factory section::

  {
    "pytest_name": "probe_device_info"
  }

Probe Wi-Fi and Bluetooth MAC address, rw firmware version, release image
version, manufacturer date, filter MAC address colon, update to device data
factory section::

  {
    "pytest_name": "probe_device_info",
    "label": "Probe Device Info",
    "args": {
      "filter_colon": true
    }
  }

Probe WI-FI MAC address, rw firmware version, release image version,
manufacturer date, and Bluetooth MAC address with specified manufacturer id,
update to device data factory section::

  {
    "pytest_name": "probe_device_info",
    "label": "Probe Device Info",
    "args": {
      "filter_colon": false,
      "manufacturer_id": 29
    }
  }
"""

import datetime
import logging

from cros.factory.device import device_utils
from cros.factory.test import device_data
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.test.utils import bluetooth_utils
from cros.factory.utils.arg_utils import Arg


class ProbeDeviceInfo(test_case.TestCase):
  """Probe device information and update to device data."""
  ARGS = [
      Arg('filter_colon', bool,
          'If True, the Wi-Fi and Bluetooth MAC will filter out the colon.',
          default=False),
      Arg('manufacturer_id', int,
          'Specified manufacturer id of the bluetooth hci device adapter.',
          default=None),
      Arg('is_upper', bool,
          'If True, the Wi-Fi and Bluetooth MAC are converted to uppercase.',
          default=True)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.wifi_mac_address = None
    self.bt_mac_address = None

  def runTest(self):
    mfg_date = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]
    rw_firmware_version = self.dut.CheckOutput(['crossystem', 'fwid'])
    release_image_version = self.dut.info.release_image_version
    self.wifi_mac_address = self.dut.info.wlan0_mac
    if self.args.manufacturer_id is None:
      logging.info('No bluetooth manufacturer id specified, use default value.')
    self.bt_mac_address = bluetooth_utils.BtMgmt(
        self.args.manufacturer_id).GetMac()
    logging.info('Wi-Fi MAC address: %s, Bluetooth MAC address: %s',
                 self.wifi_mac_address, self.bt_mac_address)
    if self.wifi_mac_address is None or self.bt_mac_address is None:
      self.FailTask('Test fail due to the mac address is None.')
    if self.args.filter_colon:
      self.wifi_mac_address = self.wifi_mac_address.replace(':', '')
      self.bt_mac_address = self.bt_mac_address.replace(':', '')
    if self.args.is_upper:
      self.wifi_mac_address = self.wifi_mac_address.upper()
      self.bt_mac_address = self.bt_mac_address.upper()

    device_data.UpdateDeviceData({
        'factory.wifi_mac': self.wifi_mac_address,
        'factory.bluetooth_mac': self.bt_mac_address,
        'factory.rw_fwid': rw_firmware_version,
        'factory.mfg_date': mfg_date,
        'factory.release_image_version': release_image_version
    })
    session.console.info('Device data has been updated.')
