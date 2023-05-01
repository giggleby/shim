# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Common classes and values for HWID v3 framework."""

import enum


DEFAULT_PROBE_STATEMENT = 'default_probe_statement.json'
COMMON_PROBE_STATEMENT = 'common_probe_statement.json'
HEADER_BIT_LENGTH = 5
IMAGE_ID_BIT_LENGTH = HEADER_BIT_LENGTH - 1
HEADER_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
OLDEST_FRAMEWORK_VERSION = 0
# This version number is used to distinguish non-compatible syntax changes
# in HWID DB.
FRAMEWORK_VERSION = 0


class OperationMode(str, enum.Enum):
  normal = 'normal'
  rma = 'rma'
  no_check = 'no_check'

  def __str__(self):
    return self.name


class ComponentStatus(str, enum.Enum):
  supported = 'supported'
  deprecated = 'deprecated'
  unsupported = 'unsupported'
  unqualified = 'unqualified'
  duplicate = 'duplicate'

  def __str__(self):
    return self.name


class EncodingScheme(str, enum.Enum):
  base32 = 'base32'
  base8192 = 'base8192'

  def __str__(self):
    return self.name


class FirmwareComps(str, enum.Enum):
  """The list of firmware component."""

  RO_MAIN_FIRMWARE = 'ro_main_firmware'
  RO_EC_FIRMWARE = 'ro_ec_firmware'
  RO_FP_FIRMWARE = 'ro_fp_firmware'
  FIRMWARE_KEYS = 'firmware_keys'

  @classmethod
  def has_value(cls, value: str):
    return value in cls.__members__.values()

  def __str__(self):
    return self.value


class HWIDException(Exception):
  """HWID-related exception."""
