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
To request the keybox from the DKPS proxy on the factory server::

  {
    "pytest_name": "provision_drm_key"
  }

To request the keybox from a given DKPS proxy URL::

  {
    "pytest_name": "provision_drm_key",
    "args": {
      "proxy_server_ip": "111.2.3.4",
      "proxy_server_ip": 5438
    }
  }

"""

import logging
import urllib.parse
import uuid
import xmlrpc.client
import zlib

from cros.factory.device import device_utils
from cros.factory.test import server_proxy
from cros.factory.test import test_case
from cros.factory.test.utils import oemcrypto_utils
from cros.factory.utils.arg_utils import Arg


KEYBOX_VPD_KEY = 'widevine_keybox'
UMPIRE_DKPS_PORT_OFFSET = 9


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
          'proxy_server_ip', str, 'IP address of DKPS server. Read from '
          '`server_proxy.GetServerURL()` when omitted.', default=None),
      Arg(
          'proxy_server_port', int, 'Port of DKPS server. Derive the Umpire '
          'DKPS proxy service port from `server_proxy.GetServerURL()` when '
          'omitted.', default=None)
  ]

  def setUp(self):
    proxy_server_ip = self.args.proxy_server_ip
    proxy_server_port = self.args.proxy_server_port

    if (proxy_server_ip is None) ^ (proxy_server_port is None):
      raise ValueError('`proxy_server_ip` and `proxy_server_port` should both '
                       'be provided or both be `None`.')
    if proxy_server_ip is None:
      server_url = server_proxy.GetServerURL()
      try:
        url = urllib.parse.urlparse(server_url)
        proxy_server_ip = url.hostname
        proxy_server_port = url.port + UMPIRE_DKPS_PORT_OFFSET
      except Exception:
        logging.exception(
            'Failed to parse the server URL from config: %s. You need to run'
            'SyncFactoryServer before this test to set the factory server URL.',
            server_url)
        raise

    logging.info('Proxy server URL: http://%s:%d', proxy_server_ip,
                 proxy_server_port)
    self.dkps_proxy = xmlrpc.client.ServerProxy(
        'http://%s:%d' % (proxy_server_ip, proxy_server_port))

    self.oemcrypto_client = oemcrypto_utils.OEMCryptoClient()
    self.dut = device_utils.CreateDUTInterface()

  def runTest(self):
    soc_id, soc_serial = self.oemcrypto_client.GetFactoryTransportKeyMaterial()

    encrypted_keybox = self.dkps_proxy.Request(
        GetDeviceSerial(self.dut.info), soc_serial, soc_id)
    wrapped_keybox = self.oemcrypto_client.WrapFactoryKeybox(encrypted_keybox)
    wrapped_keybox += format(zlib.crc32(bytes.fromhex(wrapped_keybox)), '08x')

    self.dut.vpd.ro.Update({KEYBOX_VPD_KEY: wrapped_keybox})
