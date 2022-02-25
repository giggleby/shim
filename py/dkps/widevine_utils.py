# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Utility functions for Widevine keybox provisioning"""

import hashlib

from Crypto.Cipher import AES
import crcmod.predefined


def TransportKeyKDF(soc_serial: str, soc_id: int):
  """Generate 128-bit transport key from 32-bit soc_id and 256-bit soc_serial.

  Args:
    soc_serial: SoC serial in hex string format.
    soc_id: SoC model ID.

  Returns:
    The derived transport key in bytes format.
  """

  soc_serial = bytes.fromhex(soc_serial)
  soc_id = soc_id.to_bytes(4, 'little')

  return hashlib.sha256(soc_id + soc_serial).digest()[:16]


def EncryptKeyboxWithTransportKey(keybox: str, transport_key: bytes):
  """Encrypt the keybox with the given transport key.

  This implements the encryption step documented in
  go/spriggins-factory-provision.

  Args:
    keybox: The Widevine keybox in hex string format.
    transport_key: The AES128 key in bytes format.

  Returns:
    The encrypted keybox in hex string format.
  """
  cipher = AES.new(transport_key, AES.MODE_CBC, b'\0' * 16)
  return cipher.encrypt(bytes.fromhex(keybox)).hex()


def _ComputeCRC(data: str):
  """Compute the CRC32 checksum with crc-32-mpeg function.

  Args:
    data: Data in hex string.

  Returns:
    The CRC32 checksum in a 8-character-long hex string.
  """
  crc32_func = crcmod.predefined.mkCrcFun('crc-32-mpeg')
  return format(crc32_func(bytes.fromhex(data)), '08x')


def IsValidKeybox(keybox: str):
  """Verify the CRC32 checksum in the keybox.

  Args:
    keybox: the Widevine keybox in hex string format.

  Returns:
    `True` if the checksum is verified, otherwise `False`.
  """
  return _ComputeCRC(keybox[:248]) == keybox[248:]


def FormatDeviceID(device_id: str):
  """Encode device ID to hex string, and pad it to 32 bytes with NULL bytes."""
  device_id = device_id.encode('ascii').hex()
  device_id = device_id.ljust(64, '0')
  return device_id
