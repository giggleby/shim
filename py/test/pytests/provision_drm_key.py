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
2. Request the Widevine keybox from the DKPS proxy server.
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

"""

import logging
import uuid
import xmlrpc.client
import zlib

from cros.factory.device import device_utils
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
          'DKPS proxy server.')
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    try:
      server_url = URLSpec.FindServerURL(self.args.proxy_server_url, self.dut)
    except ValueError as e:
      raise ValueError('Server Url not found, please check arguments.', e)

    logging.info('Proxy server URL: %s', server_url)
    self.dkps_proxy = xmlrpc.client.ServerProxy(server_url)

    self.oemcrypto_client = oemcrypto_utils.OEMCryptoClient()

  def runTest(self):
    soc_id, soc_serial = self.oemcrypto_client.GetFactoryTransportKeyMaterial()

    encrypted_keybox = self.dkps_proxy.Request(
        GetDeviceSerial(self.dut.info), soc_serial, soc_id)
    wrapped_keybox = self.oemcrypto_client.WrapFactoryKeybox(encrypted_keybox)
    wrapped_keybox += format(zlib.crc32(bytes.fromhex(wrapped_keybox)), '08x')

    self.dut.vpd.ro.Update({KEYBOX_VPD_KEY: wrapped_keybox})
