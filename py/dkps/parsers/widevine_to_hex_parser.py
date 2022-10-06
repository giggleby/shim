# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Module to parse Widevine keybox XML file content to bytes in hex format."""

from xml.etree import cElementTree as ET

from cros.factory.dkps.widevine_utils import FormatDeviceID


def Parse(serialized_drm_key_list):
  """Parse the Widevine key XML file content to bytes in hex format.

  This function turns each Widevine key into hex string in the following format:
  (total length: 128 bytes):
    byte   1 to byte  32: DeviceID
    byte  33 to byte  48: Key
    byte  49 to byte 120: ID
    byte 121 to byte 124: Magic
    byte 125 to byte 128: CRC

  The keybox definition can be found in go/oemcrypto -> V16 -> Integration Guide
  -> Keybox Definition.  See unit test for the example output.
  """
  widevine_key_list = []

  root = ET.fromstring(serialized_drm_key_list.strip())
  for child in root.iter('Keybox'):
    widevine_key = FormatDeviceID(child.attrib['DeviceID'])
    for key in ['Key', 'ID', 'Magic', 'CRC']:
      widevine_key += child.find(key).text
    widevine_key_list.append(widevine_key)

  return widevine_key_list
