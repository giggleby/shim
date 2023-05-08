# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import hashlib
import logging
import os.path
from typing import Optional

from google.protobuf import text_format

from cros.factory.hwid.v3 import identity as identity_module
from cros.factory.hwid.v3 import transformer
from cros.factory.utils import file_utils


try:
  # For HWID service testing environment.
  import hwid_feature_requirement_pb2
except ImportError:
  # For factory software environment.
  from cros.factory.proto import hwid_feature_requirement_pb2  # pylint: disable=ungrouped-imports


_BrandFeatureRequirementSpec = (
    hwid_feature_requirement_pb2.BrandFeatureRequirementSpec)
_Profile = _BrandFeatureRequirementSpec.Profile
_EncodingRequirement = _Profile.EncodingRequirement

FEATURE_INCOMPLIANT_VERSION = 0


class Checker(abc.ABC):
  """Provides functionalities to check the feature compliance version."""

  @abc.abstractmethod
  def CheckFeatureComplianceVersion(
      self, hwid_identity: identity_module.Identity) -> int:
    """Reports the feature compliance version by the given HWID.

    Args:
      hwid_identity: The HWID to check.

    Returns:
      The resolved feature version, or `FEATURE_INCOMPLIANT_VERSION` if not
      compliant.
    """

  @abc.abstractmethod
  def CheckFeatureEnablement(
      self, brand_code: str, is_feature_enabled: bool) -> bool:
    """Reports whether the feature enablement state is permitted.

    Args:
      brand_code: The brand code of the device.
      is_feature_enabled: Whether the feature is enabled.

    Returns:
      If `is_feature_enabled` is `True`, it returns `True` when the device
      of the specified `brand_code` is permitted for feature enablement.
      If `is_feature_enabled` is `False`, it returns `True` when the device
      of the specified `brand_code` is permitted for not enabling the versioned
      feature.
    """


def _GetBitOrZeroAt(bit_string: str, index: int) -> str:
  return bit_string[index] if index < len(bit_string) else '0'


class FeatureRequirementSpecChecker(Checker):
  """Checks the HWID's feature compliance version against the given spec."""

  _FEATURE_INCOMPLIANT_BRAND_SPEC = _BrandFeatureRequirementSpec(
      feature_version=FEATURE_INCOMPLIANT_VERSION, feature_enablement_case=(
          _BrandFeatureRequirementSpec.FEATURE_MUST_NOT_ENABLED))

  @classmethod
  def _ValidateFeatureRequirementSpec(
      cls, spec: hwid_feature_requirement_pb2.FeatureRequirementSpec):
    """Validates the raw feature requirement spec protobuf message.

    Args:
      spec: The spec to validate.

    Raises:
      ValueError: if the given spec is considered invalid.
    """
    for brand_name, brand_spec in spec.brand_specs.items():
      error_msg_prompt = f'Invalid spec for {brand_name or "(default brand)"}'
      feature_version = brand_spec.feature_version
      if feature_version == cls._FEATURE_INCOMPLIANT_BRAND_SPEC.feature_version:
        if brand_spec != cls._FEATURE_INCOMPLIANT_BRAND_SPEC:
          raise ValueError(f'{error_msg_prompt}: brand spec conflicts with '
                           'feature incompliant version.')
        continue

      if (brand_spec.feature_enablement_case ==
          _BrandFeatureRequirementSpec.FEATURE_ENABLEMENT_CASE_UNSPECIFIC):
        raise ValueError(
            f'{error_msg_prompt}: feature enablement case not specified.')
      for profile in brand_spec.profiles:
        for encoding_requirement in profile.encoding_requirements:
          if not encoding_requirement.bit_locations:
            raise ValueError(f'{error_msg_prompt}: zero-length bit_locations.')
          if any(
              len(required_value) != len(encoding_requirement.bit_locations)
              for required_value in encoding_requirement.required_values):
            raise ValueError(f'{error_msg_prompt}: required value bit-string '
                             'length mismatch.')

  def __init__(self, spec: hwid_feature_requirement_pb2.FeatureRequirementSpec):
    """Initializer.

    Args:
      spec: The feature requirement spec.

    Raises:
      ValueError: if the given spec is considered invalid.
    """
    self._ValidateFeatureRequirementSpec(spec)
    self._spec = spec

  def _CheckOneEncodingRequirement(self,
                                   encoding_requirement: _EncodingRequirement,
                                   bit_string: str) -> bool:
    actual_bit_string = ''.join(
        _GetBitOrZeroAt(bit_string, bit_location)
        for bit_location in encoding_requirement.bit_locations)
    if actual_bit_string not in encoding_requirement.required_values:
      logging.info(
          'Encoding requirement %r is not fulfilled (actual value: %r).',
          encoding_requirement.description, actual_bit_string)
      return False
    return True

  def _CheckOneProfile(self, profile: _Profile,
                       hwid_identity: identity_module.Identity) -> bool:
    bit_string = transformer.RemoveHWIDBinaryStringPadding(
        hwid_identity.binary_string)
    return all(
        self._CheckOneEncodingRequirement(encoding_requirement, bit_string)
        for encoding_requirement in profile.encoding_requirements)

  def _GetBrandFeatureRequirementSpec(
      self, brand_code: str) -> _BrandFeatureRequirementSpec:
    brand_spec = self._spec.brand_specs.get(brand_code)
    if brand_spec:
      logging.info('Got brand specific feature requirement spec for %r.',
                   brand_code)
      return brand_spec

    logging.info('Fall back to default feature requirement spec for %r.',
                 brand_code)
    brand_spec = self._spec.brand_specs.get('')
    if not brand_spec:
      raise ValueError(f'No default feature requirement spec for {brand_code}.')

    return brand_spec

  def CheckFeatureComplianceVersion(
      self, hwid_identity: identity_module.Identity) -> int:
    """See base class."""
    if hwid_identity.brand_code is None:
      logging.info('No brand info from HWID.')
      return FEATURE_INCOMPLIANT_VERSION

    brand_spec = self._GetBrandFeatureRequirementSpec(hwid_identity.brand_code)

    for profile in brand_spec.profiles:
      logging.info('Check if HWID meets the profile %r.', profile.description)
      if self._CheckOneProfile(profile, hwid_identity):
        return brand_spec.feature_version

    return FEATURE_INCOMPLIANT_VERSION

  def CheckFeatureEnablement(
      self, brand_code: str, is_feature_enabled: bool) -> bool:
    brand_spec = self._GetBrandFeatureRequirementSpec(brand_code)

    if is_feature_enabled:
      return brand_spec.feature_enablement_case in (
          _BrandFeatureRequirementSpec.FEATURE_MUST_ENABLED,
          _BrandFeatureRequirementSpec.MIXED)

    return brand_spec.feature_enablement_case in (
        _BrandFeatureRequirementSpec.FEATURE_MUST_NOT_ENABLED,
        _BrandFeatureRequirementSpec.MIXED)


FEATURE_REQUIREMENT_SPEC_CHECKSUM_ROW_PREFIX = '# checksum: '


def GetFeatureRequirementSpecFileName(project_name: str) -> str:
  return f'{project_name}.feature_requirement_spec.textproto'


def LoadChecker(data_dir: str, project_name: str) -> Optional[Checker]:
  """Loads the feature compliance checker from HWID data dir.

  Args:
    data_dir: Path to the HWID data directory (e.g. "/usr/local/factory/hwid").
    project_name: The project name to lookup.

  Returns:
    If the data directory provides a checker's spec, this method constructs
    the corresponding instance and return.  Otherwise it returns `None`.

  Raises:
    ValueError: if while constructing the checker instance, something goes
      wrong.
  """
  spec_pathname = os.path.join(data_dir,
                               GetFeatureRequirementSpecFileName(project_name))
  if not os.path.exists(spec_pathname):
    return None

  checksum_row, sep, msg = file_utils.ReadFile(spec_pathname).partition('\n')
  if not sep or not checksum_row.startswith(
      FEATURE_REQUIREMENT_SPEC_CHECKSUM_ROW_PREFIX):
    raise ValueError(f'No checksum in {spec_pathname}.')
  checksum = checksum_row[len(FEATURE_REQUIREMENT_SPEC_CHECKSUM_ROW_PREFIX):]
  if hashlib.sha256(msg.encode('utf-8')).hexdigest() != checksum:
    raise ValueError(f'Invalid checksum in {spec_pathname}.')

  return FeatureRequirementSpecChecker(
      text_format.Parse(msg,
                        hwid_feature_requirement_pb2.FeatureRequirementSpec()))
