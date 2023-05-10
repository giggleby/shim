# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import hashlib

from google.protobuf import text_format
import hwid_feature_requirement_pb2  # pylint: disable=import-error

from cros.factory.hwid.service.appengine import features
from cros.factory.hwid.service.appengine.proto import feature_match_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import common as v3_common
from cros.factory.hwid.v3 import database as db_module
from cros.factory.hwid.v3 import feature_compliance
from cros.factory.hwid.v3 import identity as identity_module
from cros.factory.utils import type_utils


Collection = features.Collection


class HWIDFeatureMatcher(abc.ABC):
  """Represents the interface of a matcher of HWID and feature versions."""

  @abc.abstractmethod
  def GenerateHWIDFeatureRequirementPayload(self) -> str:
    """Generates the HWID feature requirement payload for factories."""

  # TODO(b/273967719): Provide the interface to generate runtime payload.

  @abc.abstractmethod
  def Match(self, hwid_string: str) -> int:
    """Matches the given HWID string to resolve the enabled feature version.

    Args:
      hwid_string: The HWID string to check.

    Returns:
      If no version is enabled, it returns `0`.  Otherwise it returns the
      feature version.

    Raises:
      ValueError: If the given `hwid_string` is invalid for the project.
    """


_BrandFeatureRequirementSpec = (
    hwid_feature_requirement_pb2.BrandFeatureRequirementSpec)


class _HWIDFeatureMatcherImpl(HWIDFeatureMatcher):
  """A seralizable HWID feature matcher implementation."""

  def __init__(self, db: db_module.Database, spec: str):
    """Initializer.

    Args:
      db: The HWID DB instance.
      spec: A `feature_match_pb2.DeviceFeatureSpec` message in prototext form.

    Raises:
      ValueError: If the given spec is invalid.
    """
    self._db = db
    try:
      self._spec = text_format.Parse(spec,
                                     feature_match_pb2.DeviceFeatureSpec())
    except text_format.ParseError as ex:
      raise ValueError(f'Invalid raw spec: {ex}') from ex

  def _ExtendHWIDProfiles(
      self, brand_feature_spec: _BrandFeatureRequirementSpec,
      hwid_requirement_candidates: features.HWIDRequirementCandidates):
    for hwid_requirement_candidate in hwid_requirement_candidates:
      profile_msg = brand_feature_spec.profiles.add(
          description=hwid_requirement_candidate.description)
      for encoding_requirement in (
          hwid_requirement_candidate.encoding_requirements):
        profile_msg.encoding_requirements.add(
            description=encoding_requirement.description,
            bit_locations=encoding_requirement.bit_positions,
            required_values=encoding_requirement.required_values)

  @type_utils.LazyProperty
  def _hwid_feature_requirement_payload(self) -> str:
    spec_msg = hwid_feature_requirement_pb2.FeatureRequirementSpec()
    brand_spec_msg = spec_msg.brand_specs.get_or_create('')
    brand_spec_msg.feature_version = self._spec.feature_version
    brand_spec_msg.feature_enablement_case = (
        brand_spec_msg.FEATURE_MUST_NOT_ENABLED if self._spec.feature_version
        == features.NO_FEATURE_VERSION else brand_spec_msg.MIXED)
    self._ExtendHWIDProfiles(brand_spec_msg,
                             self._spec.hwid_requirement_candidates)
    spec_text = text_format.MessageToString(spec_msg)

    checksum = hashlib.sha256(spec_text.encode('utf-8')).hexdigest()
    header = (
        feature_compliance.FEATURE_REQUIREMENT_SPEC_CHECKSUM_ROW_PREFIX +
        checksum)
    return f'{header}\n{spec_text}'

  def GenerateHWIDFeatureRequirementPayload(self) -> str:
    """See base class."""
    return self._hwid_feature_requirement_payload

  @type_utils.LazyProperty
  def _match_checker(self) -> feature_compliance.FeatureRequirementSpecChecker:
    """The checker to match the feature enablement state."""
    assert self._spec.feature_version != features.NO_FEATURE_VERSION

    spec_msg = hwid_feature_requirement_pb2.FeatureRequirementSpec()
    for brand_name in self._spec.legacy_brands:
      brand_matching_spec_msg = spec_msg.brand_specs.get_or_create(brand_name)
      brand_matching_spec_msg.feature_version = self._spec.feature_version
      brand_matching_spec_msg.feature_enablement_case = (
          brand_matching_spec_msg.MIXED)
      self._ExtendHWIDProfiles(brand_matching_spec_msg,
                               self._spec.hwid_requirement_candidates)

    # TODO(yhong): Use the brand specific spec to match (0, N) GSC flag.
    # TODO(yhong): Use the default brand spec to match (N, N) GSC flag.

    default_matching_spec_msg = spec_msg.brand_specs.get_or_create('')
    default_matching_spec_msg.feature_version = features.NO_FEATURE_VERSION
    default_matching_spec_msg.feature_enablement_case = (
        default_matching_spec_msg.FEATURE_MUST_NOT_ENABLED)

    return feature_compliance.FeatureRequirementSpecChecker(spec_msg)

  def Match(self, hwid_string: str) -> int:
    """See base class."""
    if self._spec.feature_version == features.NO_FEATURE_VERSION:
      return features.NO_FEATURE_VERSION

    db_project = self._db.project.upper()
    if (not hwid_string.startswith(f'{db_project}-') and
        not hwid_string.startswith(f'{db_project} ')):
      raise ValueError('The given HWID string does not belong to the HWID DB.')

    image_id = identity_module.GetImageIdFromEncodedString(hwid_string)
    encoding_scheme = self._db.GetEncodingScheme(image_id)
    try:
      identity = identity_module.Identity.GenerateFromEncodedString(
          encoding_scheme, hwid_string)
    except v3_common.HWIDException as ex:
      raise ValueError(f'Invalid HWID: {ex}.') from ex
    return self._match_checker.CheckFeatureComplianceVersion(identity)


class HWIDFeatureMatcherBuilder:
  """A builder for HWID feature matchers."""

  def GenerateFeatureMatcherRawSource(
      self,
      feature_version: int,
      legacy_brands: Collection[str],
      hwid_requirement_candidates: features.HWIDRequirementCandidates,
  ) -> str:
    """Converts the device feature information to a loadable raw string.

    By passing the generated string to `CreateHWIDFeatureMatcher()`, this class
    can further create the corresponding HWID feature matcher instance.

    Args:
      feature_version: The feature version of the target device.  The value is
        expected to be greater than `features.NO_FEATURE_VERSION`.
      legacy_brands: Brand names of legacy products.
      hwid_requirement_candidates: The HWID requirement candidates to match
        the feature.

    Returns:
      A raw string that can be used as the source for HWID feature matcher
      creation.
    """
    msg = feature_match_pb2.DeviceFeatureSpec(feature_version=feature_version,
                                              legacy_brands=legacy_brands)
    for hwid_requirement_candidate in hwid_requirement_candidates:
      hwid_requirement_candidate_msg = msg.hwid_requirement_candidates.add(
          description=hwid_requirement_candidate.description)
      for prerequisite in hwid_requirement_candidate.bit_string_prerequisites:
        bit_length = len(prerequisite.bit_positions)
        required_values = [
            f'{required_value:0{bit_length}b}'[::-1]
            for required_value in prerequisite.required_values
        ]
        hwid_requirement_candidate_msg.encoding_requirements.add(
            description=prerequisite.description,
            bit_positions=prerequisite.bit_positions,
            required_values=required_values)
    return text_format.MessageToString(msg)

  def GenerateNoneFeatureMatcherRawSource(self) -> str:
    """Generates the raw source of the matcher that always matches nothing.

    Returns:
      A raw string that can be used as the source for HWID feature matcher
      creation.
    """
    msg = feature_match_pb2.DeviceFeatureSpec(
        feature_version=features.NO_FEATURE_VERSION)
    return text_format.MessageToString(msg)

  def CreateHWIDFeatureMatcher(self, db: db_module.Database,
                               source: str) -> HWIDFeatureMatcher:
    """Creates a HWID feature matcher instance from the given data source.

    Args:
      db: The HWID DB instance.
      source: The loadable string that is expected to be generated by
        `GenerateFeatureMatcherRawSource()`.

    Returns:
      The created instance.

    Raises:
      ValueError: If the given source is invalid.
    """
    return _HWIDFeatureMatcherImpl(db, source)
