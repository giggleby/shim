# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Validator for HWID configs."""

from typing import List

from cros.factory.hwid.service.appengine import config
from cros.factory.hwid.service.appengine import verification_payload_generator as vpg_module
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database


ErrorCode = contents_analyzer.ErrorCode
Error = contents_analyzer.Error


class ValidationError(Exception):
  """An exception class that indicates validation failures."""

  def __init__(self, errors: List[Error]):
    super().__init__(str(errors))
    self.errors = errors


class HwidValidator:
  """Validates HWID configs."""

  def Validate(self, hwid_config_contents):
    """Validates a HWID config.

    Uses strict validation (i.e. includes checksum validation).

    Args:
      hwid_config_contents: the current HWID config as a string.
    """
    expected_checksum = database.Database.ChecksumForText(hwid_config_contents)

    contents_analyzer_inst = contents_analyzer.ContentsAnalyzer(
        hwid_config_contents, expected_checksum, None)
    report = contents_analyzer_inst.ValidateIntegrity()
    if report.errors:
      raise ValidationError(report.errors)

  def ValidateChange(self, hwid_config_contents, prev_hwid_config_contents,
                     prev_hwid_config_contents_with_bundle_uuid=None):
    """Validates a HWID config change.

    This method validates the current config (strict, i.e. including its
    checksum), the previous config (non strict, i.e. no checksum validation)
    and the change itself (e.g. bitfields may only be appended at the end, not
    inserted in the middle).

    Args:
      hwid_config_contents: the current HWID config as a string.
      prev_hwid_config_contents: the previous HWID config as a string.
      prev_hwid_config_contents_with_bundle_uuid: the previous HWID config with
        bundle_uuid as a string.
    """
    expected_checksum = database.Database.ChecksumForText(hwid_config_contents)
    analyzer = contents_analyzer.ContentsAnalyzer(
        hwid_config_contents, expected_checksum, prev_hwid_config_contents)

    report_of_change = analyzer.ValidateChange()
    if report_of_change.errors:
      raise ValidationError(report_of_change.errors)

    report_of_integrity = analyzer.ValidateIntegrity()
    if report_of_integrity.errors:
      raise ValidationError(report_of_integrity.errors)

    if prev_hwid_config_contents_with_bundle_uuid:
      analyzer_of_firmware = contents_analyzer.ContentsAnalyzer(
          hwid_config_contents, None,
          prev_hwid_config_contents_with_bundle_uuid)
      report_of_firmware = analyzer_of_firmware.ValidateFirmwareComponents()
      if report_of_firmware.errors:
        raise ValidationError(report_of_firmware.errors)

    db = analyzer.curr_db_instance
    vpg_target = config.CONFIG.vpg_targets.get(db.project)
    if vpg_target:
      errors = vpg_module.GenerateVerificationPayload(
          [(db, vpg_target)]).error_msgs
      if errors:
        raise ValidationError(
            [Error(ErrorCode.CONTENTS_ERROR, err) for err in errors])
