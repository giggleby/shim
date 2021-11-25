# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Filter module for the Widevine keyboxes in hex string format."""


def ComputeCRC(data):
  # TODO(treapking): Currently the chroot environment doesn't have crcmod
  # installed by default, so we have to import it here to run the unit test in
  # chroot. We should create a docker instance and run factory-server-related
  # unit tests in the future.
  # pylint: disable=import-error
  import crcmod.predefined
  crc32_func = crcmod.predefined.mkCrcFun('crc-32-mpeg')
  return format(crc32_func(bytes.fromhex(data)), '08x')


def Filter(drm_key_list):
  """Filter function for Widevine keyboxes in hex string format

  Although this function is named as `Filter`, it's actually a verifier that
  checks the length and the CRC checksum of the keyboxes and raises an error
  when an invalid keybox is found. We raise the exception immediately, rather
  than filter out invalid keyboxes, because we don't think it is reasonable to
  accept a partially correct XML keybox file.

  Args:
    drm_key_list: The Widevine keyboxes list in hex string format.

  Returns:
    The original key list if no invalid keybox is found.

  Raises:
    ValueError if one of the keyboxes is invalid."""
  for widevine_key in drm_key_list:
    if len(widevine_key) != 256:
      raise ValueError('Keybox length incorrect: %s' % widevine_key)

    if ComputeCRC(widevine_key[:248]) != widevine_key[248:]:
      raise ValueError('CRC verification failed on key: %s' % widevine_key)

  return drm_key_list
