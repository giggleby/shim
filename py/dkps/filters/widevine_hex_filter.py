# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Filter module for the Widevine keybox in hex string format."""

import logging


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
  filtered_list = []
  for widevine_key in drm_key_list:
    if len(widevine_key) != 256:
      logging.error('Keybox length incorrect: %s', widevine_key)
      continue

    if ComputeCRC(widevine_key[:248]) == widevine_key[248:]:
      filtered_list.append(widevine_key)
    else:
      logging.error('CRC verification failed on key: %s', widevine_key)

  return filtered_list
