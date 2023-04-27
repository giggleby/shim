#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import tempfile
import textwrap
import unittest
from unittest import mock

from google.protobuf import text_format

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import feature_compliance
from cros.factory.hwid.v3 import identity as identity_module
from cros.factory.proto import hwid_feature_requirement_pb2
from cros.factory.utils import file_utils


def _CreateHWIDIdentityForTest(brand_code: str,
                               bit_string: str) -> identity_module.Identity:
  return identity_module.Identity(
      common.EncodingScheme.base8192, 'UNUSED_PROJ_NAME', int(bit_string[0]),
      int(bit_string[1:5], 2), bit_string[5:] + '1', brand_code=brand_code)


class FeatureRequirementSpecCheckerTest(unittest.TestCase):

  def testCheckFeatureComplianceVersion_NoSpecForBrand(self):
    hwid_identity = _CreateHWIDIdentityForTest('AABB', '0000000000')

    checker = feature_compliance.FeatureRequirementSpecChecker(
        hwid_feature_requirement_pb2.FeatureRequirementSpec())

    with self.assertRaises(ValueError):
      checker.CheckFeatureComplianceVersion(hwid_identity)

  def testCheckFeatureComplianceVersion_MatchNoProfile(self):
    hwid_identity = _CreateHWIDIdentityForTest('AABB', '0011001000')
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: "AABB"
            value: {
                feature_version: 3
                profiles: {
                    encoding_requirements: {
                        bit_locations: 2
                        bit_locations: 3
                        bit_locations: 5
                        required_values: "111"
                    }
                }
                feature_enablement_case: MIXED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    actual_value = checker.CheckFeatureComplianceVersion(hwid_identity)

    self.assertEqual(actual_value, 0)

  def testCheckFeatureComplianceVersion_MatchOneProfile(self):
    hwid_identity = _CreateHWIDIdentityForTest('AABB', '0011001000')
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: "AABB"
            value: {
                feature_version: 3
                profiles: {
                    encoding_requirements: {
                        bit_locations: 2
                        bit_locations: 3
                        bit_locations: 5
                        required_values: "000"
                        required_values: "100"
                        required_values: "010"
                        required_values: "110"
                    }
                    encoding_requirements: {
                        bit_locations: 6
                        required_values: "1"
                    }
                }
                feature_enablement_case: MIXED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    actual_value = checker.CheckFeatureComplianceVersion(hwid_identity)

    self.assertEqual(actual_value, 3)

  def testCheckFeatureComplianceVersion_MatchOneProfileInDefaultSpec(self):
    hwid_identity = _CreateHWIDIdentityForTest('AABB', '0011001000')
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: ""
            value: {
                feature_version: 3
                profiles: {
                    encoding_requirements: {
                        bit_locations: 2
                        bit_locations: 3
                        bit_locations: 5
                        required_values: "000"
                        required_values: "100"
                        required_values: "010"
                        required_values: "110"
                    }
                    encoding_requirements: {
                        bit_locations: 6
                        required_values: "1"
                    }
                }
                feature_enablement_case: MIXED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    actual_value = checker.CheckFeatureComplianceVersion(hwid_identity)

    self.assertEqual(actual_value, 3)

  def testCheckFeatureEnablement_NoBrandInfo(self):
    spec = hwid_feature_requirement_pb2.FeatureRequirementSpec()

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)

    with self.assertRaises(ValueError):
      checker.CheckFeatureEnablement('ABCD', True)

    with self.assertRaises(ValueError):
      checker.CheckFeatureEnablement('ABCD', False)

  def testCheckFeatureEnablement_FeatureMustEnabled(self):
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: "AABB"
            value: {
                feature_version: 3  # Unused.
                profiles: {  # Unused.
                    encoding_requirements: {
                        bit_locations: 6
                        required_values: "1"
                    }
                }
                feature_enablement_case: FEATURE_MUST_ENABLED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    permit_to_enable = checker.CheckFeatureEnablement('AABB', True)
    permit_to_not_enable = checker.CheckFeatureEnablement('AABB', False)

    self.assertTrue(permit_to_enable)
    self.assertFalse(permit_to_not_enable)

  def testCheckFeatureEnablement_FeatureMustNotEnabled(self):
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: "AABB"
            value: {
                feature_version: 3  # Unused.
                profiles: {  # Unused.
                    encoding_requirements: {
                        bit_locations: 6
                        required_values: "1"
                    }
                }
                feature_enablement_case: FEATURE_MUST_NOT_ENABLED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    permit_to_enable = checker.CheckFeatureEnablement('AABB', True)
    permit_to_not_enable = checker.CheckFeatureEnablement('AABB', False)

    self.assertFalse(permit_to_enable)
    self.assertTrue(permit_to_not_enable)

  def testCheckFeatureEnablement_FeatureMayOrMayNotEnable(self):
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: "AABB"
            value: {
                feature_version: 3  # Unused.
                profiles: {  # Unused.
                    encoding_requirements: {
                        bit_locations: 6
                        required_values: "1"
                    }
                }
                feature_enablement_case: MIXED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    permit_to_enable = checker.CheckFeatureEnablement('AABB', True)
    permit_to_not_enable = checker.CheckFeatureEnablement('AABB', False)

    self.assertTrue(permit_to_enable)
    self.assertTrue(permit_to_not_enable)

  def testCheckFeatureEnablement_UseDefaultSpec(self):
    spec = text_format.Parse(
        textwrap.dedent('''\
        brand_specs: {
            key: ""
            value: {
                feature_version: 3  # Unused.
                profiles: {  # Unused.
                    encoding_requirements: {
                        bit_locations: 6
                        required_values: "1"
                    }
                }
                feature_enablement_case: MIXED
            }
        }'''), hwid_feature_requirement_pb2.FeatureRequirementSpec())

    checker = feature_compliance.FeatureRequirementSpecChecker(spec)
    permit_to_enable = checker.CheckFeatureEnablement('AABB', True)
    permit_to_not_enable = checker.CheckFeatureEnablement('AABB', False)

    self.assertTrue(permit_to_enable)
    self.assertTrue(permit_to_not_enable)


class LoadCheckerTest(unittest.TestCase):

  def setUp(self):
    self.hwid_data_path = tempfile.mkdtemp()

  def testNoSpecFile(self):
    loaded_checker = feature_compliance.LoadChecker(self.hwid_data_path,
                                                    'unused_proj_name')

    self.assertIsNone(loaded_checker)

  def testInvalidChecksumRow(self):
    payload = textwrap.dedent('''\
        # ???checksum??: there are some unexpected chars.
        unused rest part.
        ''')
    file_utils.WriteFile(
        os.path.join(self.hwid_data_path,
                     'ABC.feature_requirement_spec.textproto'), payload)

    with self.assertRaises(ValueError):
      feature_compliance.LoadChecker(self.hwid_data_path, 'ABC')

  @mock.patch('hashlib.sha256')
  def testInvalidChecksum(self, mock_sha256):
    mock_sha256.return_value.hexdigest.return_value = 'locally_derived_checksum'
    payload = textwrap.dedent('''\
        # checksum: this_is_the_checksum_in_payload
        unused rest part.
        ''')
    file_utils.WriteFile(
        os.path.join(self.hwid_data_path,
                     'ABC.feature_requirement_spec.textproto'), payload)

    with self.assertRaises(ValueError):
      feature_compliance.LoadChecker(self.hwid_data_path, 'ABC')

  @mock.patch('hashlib.sha256')
  def testSuccess(self, mock_sha256):
    mock_sha256.return_value.hexdigest.return_value = 'the_checksum'
    payload = textwrap.dedent('''\
        # checksum: the_checksum
        brand_specs: {
            key: "AABB"
            value: {
                feature_version: 3
                profiles: {
                    encoding_requirements: {
                        bit_locations: 2
                        bit_locations: 3
                        bit_locations: 5
                        required_values: "111"
                    }
                }
                feature_enablement_case: MIXED
            }
        }''')
    file_utils.WriteFile(
        os.path.join(self.hwid_data_path,
                     'ABC.feature_requirement_spec.textproto'), payload)

    checker = feature_compliance.LoadChecker(self.hwid_data_path, 'ABC')

    self.assertIsNotNone(checker)


if __name__ == '__main__':
  unittest.main()
