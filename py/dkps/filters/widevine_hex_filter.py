# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Filter module for the Widevine keyboxes in hex string format."""

from cros.factory.dkps.widevine_utils import IsValidKeybox


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
      raise ValueError(f'Keybox length incorrect: {widevine_key}')

    if not IsValidKeybox(widevine_key):
      raise ValueError(f'CRC verification failed on key: {widevine_key}')

  return drm_key_list
