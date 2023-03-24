# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import hashlib
from typing import Mapping

from google.protobuf import text_format
import hwid_feature_requirement_pb2  # pylint: disable=import-error

from cros.factory.hwid.service.appengine import features
from cros.factory.hwid.v3 import common as v3_common
from cros.factory.hwid.v3 import database as db_module
from cros.factory.hwid.v3 import feature_compliance
from cros.factory.hwid.v3 import identity as identity_module


class HWIDFeatureMatcher(abc.ABC):
  """Represents the interface of a matcher of HWID and feature versions."""

  @abc.abstractmethod
  def GenerateHWIDFeatureRequirementPayload(self) -> str:
    """Generates the HWID feature requirement payload for factories."""

  # TODO(b/273967719): Provide the interface to generate runtime payload.

  @abc.abstractmethod
  def Match(self, hwid_string: str) -> int:
    """Matches the given HWID string to resolve the supported feature version.

    Args:
      hwid_string: The HWID string to check.

    Returns:
      If no version is supported, it returns `0`.  Otherwise it returns the
      feature version.

    Raises:
      ValueError: If the given `hwid_string` is invalid for the project.
    """


class _HWIDFeatureMatcherImpl(HWIDFeatureMatcher):
  """A seralizable HWID feature matcher implementation."""

  def __init__(self, db: db_module.Database, spec: str):
    """Initializer.

    Args:
      db: The HWID DB instance.
      spec: A `hwid_feature_requirement_pb2.FeatureRequirementSpec` message
        in prototext form.

    Raises:
      ValueError: If the given spec is invalid.
    """
    self._db = db
    self._raw_spec = spec
    try:
      self._spec = text_format.Parse(
          self._raw_spec, hwid_feature_requirement_pb2.FeatureRequirementSpec())
    except text_format.ParseError as ex:
      raise ValueError(f'Invalid raw spec: {ex}') from ex
    self._checker = feature_compliance.FeatureRequirementSpecChecker(self._spec)

  def GenerateHWIDFeatureRequirementPayload(self) -> str:
    """See base class."""
    checksum = hashlib.sha256(self._raw_spec.encode('utf-8')).hexdigest()
    header = (
        feature_compliance.FEATURE_REQUIREMENT_SPEC_CHECKSUM_ROW_PREFIX +
        checksum)
    return f'{header}\n{self._raw_spec}'

  def Match(self, hwid_string: str) -> int:
    """See base class."""
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
    return self._checker.CheckFeatureComplianceVersion(identity)


class HWIDFeatureMatcherBuilder:
  """A builder for HWID feature matchers."""

  def GenerateFeatureMatcherRawSource(
      self,
      brand_feature_specs: Mapping[str, features.BrandFeatureSpec],
  ) -> str:
    """Converts the brand feature specs to a loadable raw string.

    By passing the generated string to `CreateFeatureMatcher()`, this class
    can further create the corresponding HWID feature matcher instance.

    Args:
      brand_feature_specs: The feature spec of each brand.

    Returns:
      A raw string that can be used as the source for HWID feature matcher
      creation.
    """
    msg = hwid_feature_requirement_pb2.FeatureRequirementSpec()
    for brand, feature_spec in brand_feature_specs.items():
      brand_specific_msg = msg.brand_specs.get_or_create(brand)
      brand_specific_msg.feature_version = feature_spec.feature_version
      for hwid_requirement in feature_spec.hwid_requirement_candidates:
        profile_msg = brand_specific_msg.profiles.add(
            description=hwid_requirement.description)
        for prerequisite in hwid_requirement.bit_string_prerequisites:
          bit_length = len(prerequisite.bit_positions)
          required_values = [
              f'{required_value:0{bit_length}b}'[::-1]
              for required_value in prerequisite.required_values
          ]
          profile_msg.encoding_requirements.add(
              description=prerequisite.description,
              bit_locations=prerequisite.bit_positions,
              required_values=required_values)
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
