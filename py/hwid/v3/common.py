# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Common classes and values for HWID v3 framework."""

from cros.factory.utils import type_utils


DEFAULT_PROBE_STATEMENT = 'default_probe_statement.json'
HEADER_BIT_LENGTH = 5
IMAGE_ID_BIT_LENGTH = HEADER_BIT_LENGTH - 1
HEADER_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
OPERATION_MODE = type_utils.Enum(
    ['normal', 'rma', 'no_check', 'marketplace_mlb'])
COMPONENT_STATUS = type_utils.Enum(['supported', 'deprecated',
                                    'unsupported', 'unqualified',
                                    'duplicate'])
ENCODING_SCHEME = type_utils.Enum(['base32', 'base8192'])

OLDEST_FRAMEWORK_VERSION = 0
# This version number is used to distinguish non-compatible syntax changes
# in HWID DB.
FRAMEWORK_VERSION = 0


class HWIDException(Exception):
  """HWID-related exception."""
