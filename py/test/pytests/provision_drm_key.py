# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Request Widevine keybox from DKPS proxy server and provision it to the VPD.

Description
-----------
This test implements the "OEM provisioning application" defined in
go/spriggins-factory-provision.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

This test does the following procedures:

1. Get the SoC serial number and SoC model ID via OEMCrypto API.
2. If `from_device_data` is `True`:
   (1) Read the Widevine keybox from the factory device data.
   (2) Verify the keybox with the checksum.
   (3) Encrypt the keybox with the transport key.
   Otherwise, request the Widevine keybox from the DKPS proxy server.
3. Pass the keybox to OEMCrypto TA to get an encrypted keybox.
4. Compute the CRC32 code of the encrypted keybox for checking the keybox
   validity in RMA.
5. Write the encrypted keybox along with the CRC32 code to VPD.

Dependency
----------
- OEMCrypto API

Examples
--------

To request the keybox from a given DKPS proxy URL::

  {
    "pytest_name": "provision_drm_key",
    "args": {
      "proxy_server_url": "http://30.20.1.47:11000"
    }
  }

To request the keybox by different domains of dut::

  {
    "pytest_name": "provision_drm_key",
    "args": {
      "proxy_server_url": {
        "30.20.0.0/16": "http://30.20.1.47:11000",
        "40.20.0.0/16": "http://40.20.1.48:11000"
      }
    }
  }

To read the keybox from the factory device data::

  {
    "pytest_name": "provision_drm_key",
    "args": {
      "from_device_data": true
    }
  }


"""

import logging
import uuid
import xmlrpc.client
import zlib

from cros.factory.device import device_utils
from cros.factory.dkps import widevine_utils
from cros.factory.test import device_data
from cros.factory.test import test_case
from cros.factory.test.utils import oemcrypto_utils
from cros.factory.test.utils.url_spec import URLSpec
from cros.factory.utils.arg_utils import Arg


KEYBOX_VPD_KEY = 'widevine_keybox'


def GetDeviceSerial(device_info):
  """Get the device serial for requesting keyboxes from DKPS.

  Use `mlb_serial_number` if possible because:
  (1) The Widevine keybox is designed to be paired with MLB.
  (2) `serial_number` won't exist in replacement_mlb mode."""
  if device_info.mlb_serial_number is not None:
    return device_info.mlb_serial_number
  if device_info.serial_number is not None:
    return device_info.serial_number
  logging.warning('No serial numbers available on the device. '
                  'Use random string to request the keybox.')
  return uuid.uuid4().hex


class ProvisionDRMKey(test_case.TestCase):

  ARGS = [
      Arg(
          'proxy_server_url', (str, dict),
          'A URL or a map from dut domain to URL, to config the URL of'
          'DKPS proxy server.', default=None),
      Arg(
          'from_device_data', bool,
          'True to read the keybox from factory device data. Otherwise request '
          'the keybox from DKPS proxy server.', default=False)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    if not self.args.from_device_data:
      server_url = URLSpec.FindServerURL(self.args.proxy_server_url, self.dut)
      if not server_url:
        raise ValueError('Server Url not found, please check arguments.')

      logging.info('Proxy server URL: %s', server_url)
      self.dkps_proxy = xmlrpc.client.ServerProxy(server_url)

    self.oemcrypto_client = oemcrypto_utils.OEMCryptoClient()

  def GetKeyboxFromDeviceData(self):

    def FromWidevineDeviceData(key):
      device_data_key = device_data.JoinKeys(device_data.KEY_FACTORY,
                                             'widevine_' + key)
      return device_data.GetDeviceData(device_data_key, throw_if_none=True)

    keybox = widevine_utils.FormatDeviceID(FromWidevineDeviceData('device_id'))
    for key in ['key', 'id', 'magic', 'crc']:
      keybox += FromWidevineDeviceData(key)

    if not widevine_utils.IsValidKeybox(keybox):
      self.FailTask('CRC verification failed. keybox: %s.' % keybox)

    return keybox

  def runTest(self):
    soc_id, soc_serial = self.oemcrypto_client.GetFactoryTransportKeyMaterial()

    if self.args.from_device_data:
      keybox = self.GetKeyboxFromDeviceData()
      transport_key = widevine_utils.TransportKeyKDF(soc_serial, soc_id)
      encrypted_keybox = widevine_utils.EncryptKeyboxWithTransportKey(
          keybox, transport_key)
    else:
      encrypted_keybox = self.dkps_proxy.Request(
          GetDeviceSerial(self.dut.info), soc_serial, soc_id)
    wrapped_keybox = self.oemcrypto_client.WrapFactoryKeybox(encrypted_keybox)
    wrapped_keybox += format(zlib.crc32(bytes.fromhex(wrapped_keybox)), '08x')

    self.dut.vpd.ro.Update({KEYBOX_VPD_KEY: wrapped_keybox})
