# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum
import functools
import hashlib
from typing import Collection, Mapping, NamedTuple, Set

import device_selection_pb2  # pylint: disable=import-error
import factory_hwid_feature_requirement_pb2  # pylint: disable=import-error
import feature_management_pb2  # pylint: disable=import-error
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

# TODO(yhong): Consider move the following constants to
#    `cros.factory.hwid.v3.common` to reduce duplications.

_FEATURE_MANAGEMENT_FLAGS_CATEGORY = 'feature_management_flags'


class _FeatureManagementFlagField(str, enum.Enum):
  """Enumerate field names of feature management flags components in HWID."""
  IS_CHASSIS_BRANDED = 'is_chassis_branded'
  HW_COMPLIANCE_VERSION = 'hw_compliance_version'


class _FeatureManagementFlagHWIDSpec(features.HWIDSpec):
  """Leverages `features.HWIDSpec` to match feature management flags."""

  def __init__(self, target_flag_field: _FeatureManagementFlagField,
               target_value: str):
    self._target_flag_field = target_flag_field
    self._target_value = target_value

  def GetName(self) -> str:
    """See base class."""
    return f'{self._target_flag_field!r}={self._target_value!r}'

  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: features.DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """See base class."""
    del dlm_db  # unused

    feature_management_flag_components = db.GetComponents(
        _FEATURE_MANAGEMENT_FLAGS_CATEGORY, include_default=False)
    satisfied_comp_names = set(
        name for name, info in feature_management_flag_components.items()
        if info.values.get(self._target_flag_field) == self._target_value)

    satisfied_encoded_values = {}
    for encoded_field in db.encoded_fields:
      for index, comp_combo in db.GetEncodedField(encoded_field).items():
        related_comps = comp_combo.get(_FEATURE_MANAGEMENT_FLAGS_CATEGORY, [])
        if any(n in satisfied_comp_names for n in related_comps):
          satisfied_encoded_values.setdefault(encoded_field, []).append(index)
    return satisfied_encoded_values


class FeatureEnablementType(enum.Enum):
  """Enumerates different ways to enable the feature."""
  DISABLED = enum.auto()
  HARD_BRANDED = enum.auto()
  SOFT_BRANDED_LEGACY = enum.auto()
  SOFT_BRANDED_WAIVER = enum.auto()


class FeatureEnablementStatus(NamedTuple):
  """A device's feature enablement type and its HW compliance version."""
  hw_compliance_version: int
  enablement_type: FeatureEnablementType

  @classmethod
  def FromHWIncompliance(cls) -> 'FeatureEnablementStatus':
    return cls(features.NO_FEATURE_VERSION, FeatureEnablementType.DISABLED)


class HWIDFeatureMatcher(abc.ABC):
  """Represents the interface of a matcher of HWID and feature versions."""

  @abc.abstractmethod
  def GenerateHWIDFeatureRequirementPayload(self) -> str:
    """Generates the HWID feature requirement payload for factories."""

  @abc.abstractmethod
  def GenerateLegacyPayload(self) -> str:
    """Generates the HWID feature requirement payload for feature management.
    """

  @abc.abstractmethod
  def Match(self, hwid_string: str) -> FeatureEnablementStatus:
    """Matches the given HWID string to resolve the feature enablement status.

    Args:
      hwid_string: The HWID string to check.

    Returns:
      It returns the named tuple of the following fields:
        1. `hw_compliance_version` records the feature version bound to the
            device.
        2. `enablement_type` refers to whether the feature is enabled or not.

    Raises:
      ValueError: If the given `hwid_string` is invalid for the project.
    """


_BrandFeatureRequirementSpec = (
    factory_hwid_feature_requirement_pb2.BrandFeatureRequirementSpec)


def _PatchDeviceFeatureSpec(spec: feature_match_pb2.DeviceFeatureSpec):
  for brand_code in spec.legacy_brands:
    permission = spec.brand_code_permissions.get_or_create(brand_code)
    permission.allow_disabled_units = True
    permission.allow_soft_branded_legacy_units = True


def _MatchByChecker(checker: feature_compliance.FeatureRequirementSpecChecker,
                    identity: identity_module.Identity) -> bool:
  return checker.CheckFeatureComplianceVersion(
      identity) > features.NO_FEATURE_VERSION


# A regular HWID string can never reach this much bits because we don't
# expect a HWID string that occupies more than 8MB.
_IMPOSSIBLE_BIT_LOCATION = 8 * 1024 * 1024


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
    # TODO(yhong): Stop migrating from the old data format once the migration
    #     has completed.
    _PatchDeviceFeatureSpec(self._spec)

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
  def _soft_branded_legacy_brand_code_set(self) -> Set[str]:
    return set(brand_code
               for brand_code, p in self._spec.brand_code_permissions.items()
               if p.allow_soft_branded_legacy_units)

  @type_utils.LazyProperty
  def _soft_branded_brand_code_set(self) -> Set[str]:
    return set(brand_code
               for brand_code, p in self._spec.brand_code_permissions.items()
               if p.allow_soft_branded_legacy_units or
               p.allow_soft_branded_waiver_units)

  @type_utils.LazyProperty
  def _hwid_feature_requirement_payload(self) -> str:
    # TODO(yhong): Populate the permission of each RLZ brand codes to the
    #     payload.
    spec_msg = factory_hwid_feature_requirement_pb2.FeatureRequirementSpec()
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

  def GenerateLegacyPayload(self) -> str:
    """See base class."""
    if self._spec.feature_version == 0:
      return ''

    db_project = self._db.project.upper()

    payload_msg = device_selection_pb2.DeviceSelection(
        feature_level=self._spec.feature_version,
        scope=feature_management_pb2.Feature.Scope.SCOPE_DEVICES_0)

    if self._soft_branded_legacy_brand_code_set:
      for hwid_requirement_candidate in self._spec.hwid_requirement_candidates:
        profile = hwid_feature_requirement_pb2.HwidProfile()
        for encoding_requirement in (
            hwid_requirement_candidate.encoding_requirements):
          profile.encoding_requirements.append(
              hwid_feature_requirement_pb2.HwidProfile.EncodingRequirement(
                  bit_locations=encoding_requirement.bit_positions,
                  required_values=encoding_requirement.required_values))
        profile.prefixes.extend(
            sorted(f'{db_project}-{brand_code}'
                   for brand_code in self._soft_branded_legacy_brand_code_set))
        payload_msg.hwid_profiles.append(profile)

    # Append non-legacy soft-branded brand codes with an impossible to match
    # encoding requirement so that libsegmentation can match with prefix
    # for the waiver scenario but will not mistakenly match with the raw HWID
    # regexp.
    non_legacy_soft_branded_brand_codes = (
        self._soft_branded_brand_code_set -
        self._soft_branded_legacy_brand_code_set)
    if non_legacy_soft_branded_brand_codes:
      profile = hwid_feature_requirement_pb2.HwidProfile()
      profile.encoding_requirements.add(
          bit_locations=[_IMPOSSIBLE_BIT_LOCATION], required_values=["1"])
      profile.prefixes.extend(
          sorted(f'{db_project}-{brand_code}'
                 for brand_code in non_legacy_soft_branded_brand_codes))
      payload_msg.hwid_profiles.append(profile)

    if not payload_msg.hwid_profiles:
      return ''

    return text_format.MessageToString(payload_msg)

  def _BuildFeatureManagementFlagChecker(
      self, target_field: _FeatureManagementFlagField
  ) -> feature_compliance.FeatureRequirementSpecChecker:
    """Builds a `FeatureRequirementSpecChecker` for the feature mngt flag field.

    Args:
      target_field: The field name in the feature management component values
        to check.

    Returns:
      A `FeatureRequirementSpecChecker` instance, which
      `CheckFeatureComplianceVersion` method returns
      `self._spec.feature_version` if and only if the HWID contains
      the feature management flag component with `target_field` value being
      `str(self._spec.feature_version)`.
    """
    hwid_requirement_resolver = features.HWIDRequirementResolver([
        _FeatureManagementFlagHWIDSpec(target_field,
                                       str(self._spec.feature_version))
    ])
    hwid_requirement_candidates = (
        hwid_requirement_resolver.DeduceHWIDRequirementCandidates(self._db, {}))

    checker_spec = factory_hwid_feature_requirement_pb2.FeatureRequirementSpec()
    default_brand_spec = checker_spec.brand_specs.get_or_create('')
    default_brand_spec.feature_version = self._spec.feature_version
    default_brand_spec.feature_enablement_case = default_brand_spec.MIXED
    for hwid_requirement_candidate in hwid_requirement_candidates:
      profile_msg = default_brand_spec.profiles.add()
      for prerequisite in hwid_requirement_candidate.bit_string_prerequisites:
        bit_length = len(prerequisite.bit_positions)
        required_values = [
            f'{required_value:0{bit_length}b}'[::-1]
            for required_value in prerequisite.required_values
        ]
        profile_msg.encoding_requirements.add(
            bit_locations=prerequisite.bit_positions,
            required_values=required_values)
    return feature_compliance.FeatureRequirementSpecChecker(checker_spec)

  @type_utils.LazyProperty
  def _chassis_is_branded_checker(
      self) -> feature_compliance.FeatureRequirementSpecChecker:
    """The checker to match the chassis branding state."""
    assert self._spec.feature_version != features.NO_FEATURE_VERSION
    return self._BuildFeatureManagementFlagChecker(
        _FeatureManagementFlagField.IS_CHASSIS_BRANDED)

  @type_utils.LazyProperty
  def _hw_compliant_checker(
      self) -> feature_compliance.FeatureRequirementSpecChecker:
    """The checker to match the HW compliance version state."""
    assert self._spec.feature_version != features.NO_FEATURE_VERSION
    return self._BuildFeatureManagementFlagChecker(
        _FeatureManagementFlagField.HW_COMPLIANCE_VERSION)

  @type_utils.LazyProperty
  def _legacy_checker(self) -> feature_compliance.FeatureRequirementSpecChecker:
    """The checker to match the feature enablement state for legacy devices."""
    assert self._spec.feature_version != features.NO_FEATURE_VERSION

    spec_msg = factory_hwid_feature_requirement_pb2.FeatureRequirementSpec()
    for brand_name in self._soft_branded_legacy_brand_code_set:
      brand_matching_spec_msg = spec_msg.brand_specs.get_or_create(brand_name)
      brand_matching_spec_msg.feature_version = self._spec.feature_version
      brand_matching_spec_msg.feature_enablement_case = (
          brand_matching_spec_msg.MIXED)
      self._ExtendHWIDProfiles(brand_matching_spec_msg,
                               self._spec.hwid_requirement_candidates)

    default_matching_spec_msg = spec_msg.brand_specs.get_or_create('')
    default_matching_spec_msg.feature_version = features.NO_FEATURE_VERSION
    default_matching_spec_msg.feature_enablement_case = (
        default_matching_spec_msg.FEATURE_MUST_NOT_ENABLED)

    return feature_compliance.FeatureRequirementSpecChecker(spec_msg)

  def _GetHWIDIdentityFromHWIDString(
      self, hwid_string: str) -> identity_module.Identity:
    image_id = identity_module.GetImageIdFromEncodedString(hwid_string)
    encoding_scheme = self._db.GetEncodingScheme(image_id)
    try:
      return identity_module.Identity.GenerateFromEncodedString(
          encoding_scheme, hwid_string)
    except v3_common.HWIDException as ex:
      raise ValueError(f'Invalid HWID: {ex}.') from ex

  def _IsHWIDStringProjectMatch(self, hwid_string: str) -> bool:
    db_project = self._db.project.upper()
    return hwid_string.startswith(f'{db_project}-') or hwid_string.startswith(
        f'{db_project} ')

  def Match(self, hwid_string: str) -> FeatureEnablementStatus:
    """See base class."""
    if not self._IsHWIDStringProjectMatch(hwid_string):
      raise ValueError('The given HWID string does not belong to the HWID DB.')

    if self._spec.feature_version == features.NO_FEATURE_VERSION:
      # It implies that the product is legacy and totally non-soft-branded.
      return FeatureEnablementStatus.FromHWIncompliance()

    hwid_identity = self._GetHWIDIdentityFromHWIDString(hwid_string)

    # Follows the same logic as OS runtime feature-level determination workflow
    # (i.e. libsegmentation) deduce whether the versioned feature is enabled or
    # not.

    build_hw_compliant_result = functools.partial(FeatureEnablementStatus,
                                                  self._spec.feature_version)

    if _MatchByChecker(self._chassis_is_branded_checker, hwid_identity):
      return build_hw_compliant_result(FeatureEnablementType.HARD_BRANDED)

    if _MatchByChecker(self._hw_compliant_checker, hwid_identity):
      if hwid_identity.brand_code in self._soft_branded_brand_code_set:
        return build_hw_compliant_result(
            FeatureEnablementType.SOFT_BRANDED_WAIVER)
      return build_hw_compliant_result(FeatureEnablementType.DISABLED)

    if _MatchByChecker(self._legacy_checker, hwid_identity):
      # Legacy and soft-branded case.
      return build_hw_compliant_result(
          FeatureEnablementType.SOFT_BRANDED_LEGACY)

    return FeatureEnablementStatus.FromHWIncompliance()


def _ToFeatureEnablementPermissionMsg(
    allowed_feature_enablement_types: Collection[FeatureEnablementType]
) -> feature_match_pb2.FeatureEnablementPermission:
  inst = feature_match_pb2.FeatureEnablementPermission()
  for a in allowed_feature_enablement_types:
    if a == FeatureEnablementType.DISABLED:
      inst.allow_disabled_units = True
    elif a == FeatureEnablementType.HARD_BRANDED:
      inst.allow_hard_branded_units = True
    elif a == FeatureEnablementType.SOFT_BRANDED_LEGACY:
      inst.allow_soft_branded_legacy_units = True
    elif a == FeatureEnablementType.SOFT_BRANDED_WAIVER:
      inst.allow_soft_branded_waiver_units = True
    else:
      raise AssertionError(f'Incomplete if-elif clause, {a!r} is not covered.')
  return inst


class HWIDFeatureMatcherBuilder:
  """A builder for HWID feature matchers."""

  def GenerateFeatureMatcherRawSource(
      self,
      feature_version: int,
      brand_allowed_feature_enablement_types: (
          Mapping[str, Collection[FeatureEnablementType]]),
      hwid_requirement_candidates: features.HWIDRequirementCandidates,
  ) -> str:
    """Converts the device feature information to a loadable raw string.

    By passing the generated string to `CreateHWIDFeatureMatcher()`, this class
    can further create the corresponding HWID feature matcher instance.

    Args:
      feature_version: The feature version of the target device.  The value is
        expected to be greater than `features.NO_FEATURE_VERSION`.
      brand_allowed_feature_enablement_types: Maps the RLZ brand code to a set
        of allowed feature enablement types.
      hwid_requirement_candidates: The HWID requirement candidates to match
        the feature.

    Returns:
      A raw string that can be used as the source for HWID feature matcher
      creation.
    """
    brand_code_permissions = {
        k: _ToFeatureEnablementPermissionMsg(v)
        for k, v in brand_allowed_feature_enablement_types.items()
    }
    msg = feature_match_pb2.DeviceFeatureSpec(
        feature_version=feature_version,
        brand_code_permissions=brand_code_permissions)
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
