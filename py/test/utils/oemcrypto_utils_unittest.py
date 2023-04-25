#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

import dbus

from cros.factory.test.utils.oemcrypto_utils import OEMCryptoClient


class MockInterface:

  FAKE_SOC_ID = 1234
  FAKE_SOC_SERIAL = b'\xff' * 32

  def GetFactoryTransportKeyMaterial(self):
    return (dbus.UInt32(
        self.FAKE_SOC_ID), [dbus.Byte(b) for b in self.FAKE_SOC_SERIAL])

  def WrapFactoryKeybox(self, encrypted_keybox):
    del encrypted_keybox  # unused
    # The re-encrypted keybox has 176 bytes.
    return dbus.Array([dbus.Byte(b'\x7f')] * 176)


class OEMCryptoClientTest(unittest.TestCase):

  def setUp(self):
    with mock.patch('cros.factory.external.py_lib.dbus.SystemBus'), \
         mock.patch('cros.factory.external.py_lib.dbus.Interface',
                    return_value=MockInterface()):
      self.oemcrypto_client = OEMCryptoClient()

  def testGetFactoryTrasnportKeyMaterial(self):
    soc_id, soc_serial = self.oemcrypto_client.GetFactoryTransportKeyMaterial()
    self.assertIsInstance(soc_id, int)
    self.assertEqual(soc_id, 1234)
    self.assertEqual(soc_serial, 'ff' * 32)

  def testWrapFactoryKeybox(self):
    # Pass the keybox encrypted by the transport key.
    wrapped_keybox = self.oemcrypto_client.WrapFactoryKeybox('1a' * 128)
    self.assertEqual(wrapped_keybox, '7f' * 176)


if __name__ == '__main__':
  unittest.main()
