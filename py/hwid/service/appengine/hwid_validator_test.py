#!/usr/bin/env python3
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for HwidValidator."""

import collections
import os
import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import file_utils


TESTDATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata')

GOLDEN_MODEL_NAME = 'CHROMEBOOK'
GOLDEN_HWIDV3_DATA_BEFORE = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-before.yaml'))
GOLDEN_HWIDV3_DATA_AFTER_BAD = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-after-bad.yaml'))
GOLDEN_HWIDV3_DATA_AFTER_GOOD = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-after-good.yaml'))
SARIEN_MODEL_NAME = 'SARIEN'
SARIEN_DATA_GOOD = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'sarien-example.yaml'))
GOLDEN_HWIDV3_DATA_AFTER_DRAM_BAD = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-after-dram-bad.yaml'))
GOLDEN_HWIDV3_DATA_AFTER_VALID_NAME_PATTERN = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-after-comp-good.yaml'))
GOLDEN_HWIDV3_DATA_AFTER_INVALID_NAME_PATTERN_WITH_NOTE = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-after-comp-note-bad.yaml'))
GOLDEN_HWIDV3_DATA_AFTER_VALID_NAME_PATTERN_WITH_NOTE = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-golden-after-comp-note-good.yaml'))
GOLDEN_HWIDV3_DATA_FROM_FACTORY_BUNDLE = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-from-factory-bundle.yaml'))
GOLDEN_HWIDV3_DATA_FROM_FACTORY_BUNDLE_MODIFIED = file_utils.ReadFile(
    os.path.join(TESTDATA_PATH, 'v3-from-factory-bundle-modified.yaml'))

_ComponentNameInfo = contents_analyzer.ComponentNameInfo
_DeviceMetadata = hwid_api_messages_pb2.DeviceMetadata


@mock.patch('cros.factory.hwid.service.appengine.config.CONFIG.hwid_filesystem',
            filesystem_adapter.LocalFileSystemAdapter(TESTDATA_PATH))
class HwidValidatorTest(unittest.TestCase):
  """Test for HwidValidator."""

  def testValidateChange_withValidChange(self):
    hwid_validator.HwidValidator().ValidateChange(GOLDEN_HWIDV3_DATA_AFTER_GOOD,
                                                  GOLDEN_HWIDV3_DATA_BEFORE)

  def testValidateChange_withInvalidChange(self):
    with self.assertRaises(hwid_validator.ValidationError):
      hwid_validator.HwidValidator().ValidateChange(
          GOLDEN_HWIDV3_DATA_AFTER_BAD, GOLDEN_HWIDV3_DATA_BEFORE)

  def testValidateChange_withDeviceMetadata(self):
    device_metadata = _DeviceMetadata(
        form_factor=_DeviceMetadata.FormFactor.CONVERTIBLE)
    with self.assertRaises(hwid_validator.ValidationError):
      hwid_validator.HwidValidator().ValidateChange(
          GOLDEN_HWIDV3_DATA_AFTER_GOOD, GOLDEN_HWIDV3_DATA_BEFORE,
          device_metadata=device_metadata)

  def testValidateChange_modifiedFromFactoryBundle(self):
    with self.assertRaises(hwid_validator.ValidationError):
      hwid_validator.HwidValidator().ValidateChange(
          GOLDEN_HWIDV3_DATA_FROM_FACTORY_BUNDLE,
          GOLDEN_HWIDV3_DATA_FROM_FACTORY_BUNDLE,
          GOLDEN_HWIDV3_DATA_FROM_FACTORY_BUNDLE_MODIFIED)

  def testValidateSarien_withValidChange(self):
    hwid_validator.HwidValidator().ValidateChange(SARIEN_DATA_GOOD,
                                                  SARIEN_DATA_GOOD)

  def testValidateSarien_withGeneratePayloadFail(self):
    with self.assertRaises(hwid_validator.ValidationError):
      with mock.patch.object(hwid_validator.vpg_module,
                             'GenerateVerificationPayload',
                             return_value=self.CreateBadVPGResult()):
        hwid_validator.HwidValidator().ValidateChange(SARIEN_DATA_GOOD,
                                                      SARIEN_DATA_GOOD)

  def testValidateNonSarien_withGeneratePayloadFail(self):
    with mock.patch.object(hwid_validator.vpg_module,
                           'GenerateVerificationPayload',
                           return_value=self.CreateBadVPGResult()):
      hwid_validator.HwidValidator().ValidateChange(
          GOLDEN_HWIDV3_DATA_AFTER_GOOD, GOLDEN_HWIDV3_DATA_BEFORE)

  def testValidateDramChange(self):
    with self.assertRaises(hwid_validator.ValidationError) as ex_ctx:
      hwid_validator.HwidValidator().ValidateChange(
          GOLDEN_HWIDV3_DATA_AFTER_DRAM_BAD, GOLDEN_HWIDV3_DATA_BEFORE)
    self.assertIn("'dram_type_not_mention_size' does not contain size property",
                  set(err.message for err in ex_ctx.exception.errors))

  def testValidateComponentNameValid(self):
    hwid_validator.HwidValidator().ValidateChange(
        GOLDEN_HWIDV3_DATA_AFTER_VALID_NAME_PATTERN, GOLDEN_HWIDV3_DATA_BEFORE)

  def testValidateComponentNameInvalidWithNote(self):
    with self.assertRaises(hwid_validator.ValidationError) as ex_ctx:
      hwid_validator.HwidValidator().ValidateChange(
          GOLDEN_HWIDV3_DATA_AFTER_INVALID_NAME_PATTERN_WITH_NOTE,
          GOLDEN_HWIDV3_DATA_BEFORE)
    self.assertCountEqual([err.message for err in ex_ctx.exception.errors], [
        "Invalid component name with sequence number, please modify it from '"
        "cpu_2_3#4' to 'cpu_2_3#3'.",
        "Invalid component name with sequence number, please modify it from '"
        "cpu_2_3#non-a-number' to 'cpu_2_3#4'."
    ])

  def testValidateComponentNameValidWithNote(self):
    hwid_validator.HwidValidator().ValidateChange(
        GOLDEN_HWIDV3_DATA_AFTER_VALID_NAME_PATTERN_WITH_NOTE,
        GOLDEN_HWIDV3_DATA_BEFORE)

  @classmethod
  def CreateBadVPGResult(cls):
    ret = hwid_validator.vpg_module.VerificationPayloadGenerationResult(
        generated_file_contents={}, error_msgs=['err1', 'err2'],
        payload_hash='', primary_identifiers=collections.defaultdict(dict))
    return ret


if __name__ == '__main__':
  unittest.main()
