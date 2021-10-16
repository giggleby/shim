# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Wrapper for cdm-oemcrypto dbus interface.

Currently the dbus interface is only supported on the AMD platform for
Spriggins project. See go/spriggins-factory-provision for more details.
"""

from cros.factory.external import dbus


class OEMCryptoClient:
  SERVICE_NAME = 'org.chromium.CdmFactoryDaemon'
  PATH = '/org/chromium/CdmFactoryDaemon'
  INTERFACE = 'org.chromium.CdmFactoryDaemon'

  def __init__(self):
    bus = dbus.SystemBus()
    obj = bus.get_object(self.SERVICE_NAME, self.PATH)
    self._interface = dbus.Interface(obj, self.INTERFACE)

  def GetFactoryTransportKeyMaterial(self) -> (int, str):
    """Get SoC model ID and SoC serial number from OEMCrypto API

    Returns:
      A tuple of (soc_id, soc_serial). soc_serial is returned in hex string
      format.
    """
    soc_id, soc_serial = self._interface.GetFactoryTransportKeyMaterial()
    soc_id = int(soc_id)
    soc_serial = bytes(soc_serial).hex()
    return soc_id, soc_serial

  def WrapFactoryKeybox(self, encrypted_keybox: str) -> str:
    """Pass the encrypted keybox to OEMCrypto daemon to re-encrypted the keybox.

    This API expects a keybox encrypted with the transport key. When keybox is
    given, the API decrypts the keybox, re-encrypts it with a device-unique key,
    and returns the keybox.

    Args:
      encrypted_keybox: The encrypted keybox in hex string format.

    Returns:
      The re-encrypted keybox in hex string format.
    """
    keybox_for_dbus = dbus.Array(
        [dbus.Byte(b) for b in bytes.fromhex(encrypted_keybox)], signature='y')
    return bytes(self._interface.WrapFactoryKeybox(keybox_for_dbus)).hex()
