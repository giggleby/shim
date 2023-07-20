#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import textwrap
import unittest
from unittest import mock

import yaml

from cros.factory.hwid.service.appengine import feature_matching
from cros.factory.hwid.service.appengine import features
from cros.factory.hwid.v3 import database as db_module


_FeatureEnablementType = feature_matching.FeatureEnablementType
_FeatureEnablementStatus = feature_matching.FeatureEnablementStatus


def _BuildHWIDDBForTest(project_name: str, image_ids: features.Collection[int],
                        feature_version: str = '1') -> db_module.Database:
  image_id_part = {
      'image_id': {
          image_id: f'THE_IMAGE_ID_{image_id}'
          for image_id in image_ids
      }
  }
  pattern_part = {
      'pattern': [{
          'image_ids':
              list(image_ids),
          'encoding_scheme':
              'base8192',
          'fields': [
              {
                  'dummy_field': 8
              },
              {
                  'feature_management_flags_field': 13
              },
          ],
      }]
  }
  return db_module.Database.LoadData('\n'.join([
      textwrap.dedent(f"""\
          checksum:
          project: {project_name}
          encoding_patterns:
            0: default
          """),
      yaml.safe_dump(image_id_part),
      yaml.safe_dump(pattern_part),
      textwrap.dedent(f"""\
          encoded_fields:
            dummy_field:
              0:
                dummy_type: null
            feature_management_flags_field:
              0:
                feature_management_flags: chassis_not_branded_and_hw_incompliant
              1:
                feature_management_flags: chassis_not_branded_but_hw_compliant
              2:
                feature_management_flags: chassis_branded_and_hw_compliant
          components:
            dummy_type:
              items:
                dummy_component:
                  status: supported
                  values:
                    dummy_probe_attr: dummy_probe_value
            feature_management_flags:
              items:
                chassis_not_branded_and_hw_incompliant:
                  status: supported
                  values:
                    is_chassis_branded: '0'
                    hw_compliance_version: '0'
                chassis_not_branded_but_hw_compliant:
                  status: supported
                  values:
                    is_chassis_branded: '0'
                    hw_compliance_version: {feature_version!r}
                chassis_branded_and_hw_compliant:
                  status: supported
                  values:
                    is_chassis_branded: {feature_version!r}
                    hw_compliance_version: {feature_version!r}
          rules: []
          """),
  ]))


class HWIDFeatureMatcherBuilderTest(unittest.TestCase):

  @mock.patch('hashlib.sha256')
  def testConvertedHWIDFeatureMatcherCanGenerateFeatureRequirementPayload(
      self, mock_sha256):
    mock_sha256.return_value.hexdigest.return_value = 'the_fixed_checksum'
    db = _BuildHWIDDBForTest(project_name='UNUSEDPROJ', image_ids=[0, 1, 2])
    feature_version = 1
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='bit_string_prerequisite1-1',
                    bit_positions=[2, 4, 5], required_values=[0b001, 0b101]),
            ]),
        features.HWIDRequirement(
            description='scenario_2', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='bit_string_prerequisite2-1',
                    bit_positions=[2, 4, 5], required_values=[0b000]),
                features.HWIDBitStringRequirement(
                    description='bit_string_prerequisite2-1',
                    bit_positions=[3, 6], required_values=[0b01]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    brand_allowed_feature_enablement_types = {}
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)
    actual = matcher.GenerateHWIDFeatureRequirementPayload()

    self.assertEqual(
        actual,
        textwrap.dedent("""\
            # checksum: the_fixed_checksum
            brand_specs {
              value {
                feature_version: 1
                profiles {
                  description: "scenario_1"
                  encoding_requirements {
                    description: "bit_string_prerequisite1-1"
                    bit_locations: 2
                    bit_locations: 4
                    bit_locations: 5
                    required_values: "100"
                    required_values: "101"
                  }
                }
                profiles {
                  description: "scenario_2"
                  encoding_requirements {
                    description: "bit_string_prerequisite2-1"
                    bit_locations: 2
                    bit_locations: 4
                    bit_locations: 5
                    required_values: "000"
                  }
                  encoding_requirements {
                    description: "bit_string_prerequisite2-1"
                    bit_locations: 3
                    bit_locations: 6
                    required_values: "10"
                  }
                }
                feature_enablement_case: MIXED
              }
            }
            """))

  def testConvertedHWIDFeatureMatcherCanMatchHWIDs(self):
    feature_version = 1
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2],
                             feature_version=str(feature_version))
    brand_allowed_feature_enablement_types = {
        'ABCD': [
            _FeatureEnablementType.SOFT_BRANDED_LEGACY,
            _FeatureEnablementType.SOFT_BRANDED_WAIVER,
            _FeatureEnablementType.DISABLED,
        ],
        'WXYZ': [
            _FeatureEnablementType.HARD_BRANDED,
            _FeatureEnablementType.DISABLED,
        ],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='image_id_0_or_1',
                    bit_positions=[4, 3, 2, 1,
                                   0], required_values=[0b00000, 0b00001]),
            ]),
        features.HWIDRequirement(
            description='scenario_2', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id_2',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0b00010]),
                features.HWIDBitStringRequirement(
                    description='bit_5_6_7_has_100_or_111',
                    bit_positions=[5, 6, 7], required_values=[0b001, 0b111]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    hw_incompliant_match_result = _FeatureEnablementStatus.FromHWIncompliance()
    hw_compliant_but_disabled_match_result = _FeatureEnablementStatus(
        feature_version, _FeatureEnablementType.DISABLED)
    legacy_enabled_match_result = _FeatureEnablementStatus(
        feature_version, _FeatureEnablementType.SOFT_BRANDED_LEGACY)
    branded_enabled_match_result = _FeatureEnablementStatus(
        feature_version, _FeatureEnablementType.HARD_BRANDED)
    waiver_enabled_match_result = _FeatureEnablementStatus(
        feature_version, _FeatureEnablementType.SOFT_BRANDED_WAIVER)
    for hwid_string, expected_match_result_or_error in (
        # incorrect project
        ('NOTTHISPROJ-ABCD A2A-B47', ValueError),
        # no brand
        ('THEPROJ A2A-B47', hw_incompliant_match_result),
        # incorrect brand with no feature management flag
        ('THEPROJ-WXYZ A2A-B9W', hw_incompliant_match_result),
        # match scenario_1
        ('THEPROJ-ABCD A8A-B4T', legacy_enabled_match_result),
        # match scenario_2
        ('THEPROJ-ABCD B2A-B5L', legacy_enabled_match_result),
        # match neither scenario_1 nor scenario_2
        ('THEPROJ-ABCD C8A-B8Y', hw_incompliant_match_result),
        # match scenario_2
        ('THEPROJ-ABCD C6A-B8S', legacy_enabled_match_result),
        # match neither scenario_1 nor scenario_2, but feature management flag
        # indicates chassis has branded.
        ('THEPROJ-WXYZ C2A-A2C-B93', branded_enabled_match_result),
        # feature management flag indicates chassis has branded while scenario_1
        # is also matched
        ('THEPROJ-WXYZ A2A-A2C-B8S', branded_enabled_match_result),
        # feature management flag indicates HW compliant without branded
        # chassis, also the brand code is on the legacy list
        ('THEPROJ-ABCD C2A-A2B-B3L', waiver_enabled_match_result),
        # feature management flag indicates HW compliant without branded
        # chassis, also the brand code is not on the legacy list
        ('THEPROJ-WXYZ C2A-A2B-B72', hw_compliant_but_disabled_match_result),
    ):
      if isinstance(expected_match_result_or_error, _FeatureEnablementStatus):
        with self.subTest(hwid_string=hwid_string,
                          expected_version=expected_match_result_or_error):
          actual = matcher.Match(hwid_string)
          self.assertEqual(actual, expected_match_result_or_error)
      else:
        with self.subTest(hwid_string=hwid_string,
                          expected_error=expected_match_result_or_error):
          with self.assertRaises(expected_match_result_or_error):
            matcher.Match(hwid_string)

  def testConvertedHWIDFeatureMatcherCanMatchForOldHWIDDB(self):
    feature_version = 1
    db = db_module.Database.LoadData(
        textwrap.dedent("""\
        checksum:
        project: THEPROJ
        encoding_patterns:
          0: default
        image_id:
          0: PROTO
          1: EVT
          2: DVT
          3: PVT
          4: PVT_COMPLIANT
        pattern:
        - image_ids: [0, 1, 2, 3, 4]
          encoding_scheme: base8192
          fields:
          - dummy_field: 8
        encoded_fields:
          dummy_field:
            0:
              dummy_type: null
        components:
          dummy_type:
            items:
              dummy_component:
                status: supported
                values:
                  dummy_probe_attr: dummy_probe_value
        rules: []
        """))
    brand_allowed_feature_enablement_types = {
        'ABCD': [_FeatureEnablementType.SOFT_BRANDED_LEGACY],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id_4',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0b00100]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    hw_incompliant_match_result = _FeatureEnablementStatus.FromHWIncompliance()
    legacy_enabled_match_result = _FeatureEnablementStatus(
        feature_version, _FeatureEnablementType.SOFT_BRANDED_LEGACY)
    for hwid_string, expected_match_result_or_error in (
        # incorrect project
        ('NOTTHISPROJ-ABCD A2A-B47', ValueError),
        # no brand
        ('THEPROJ A2A-B47', hw_incompliant_match_result),
        # incorrect brand, not match scenario_1
        ('THEPROJ-WXYZ E2A-B7B', hw_incompliant_match_result),
        # incorrect brand, match scenario_1
        ('THEPROJ-WXYZ E8A-B5X', hw_incompliant_match_result),
        # correct brand, not match scenario_1
        ('THEPROJ-ABCD A8A-B4T', hw_incompliant_match_result),
        # correct brand, match scenario_1
        ('THEPROJ-ABCD E8A-B2E', legacy_enabled_match_result),
    ):
      if isinstance(expected_match_result_or_error, _FeatureEnablementStatus):
        with self.subTest(hwid_string=hwid_string,
                          expected_version=expected_match_result_or_error):
          actual = matcher.Match(hwid_string)
          self.assertEqual(actual, expected_match_result_or_error)
      else:
        with self.subTest(hwid_string=hwid_string,
                          expected_error=expected_match_result_or_error):
          with self.assertRaises(expected_match_result_or_error):
            matcher.Match(hwid_string)

  def testConvertedHWIDFeatureMatcher_GenerateLegacyPayload_Normal(self):
    feature_version = 1
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2],
                             feature_version=str(feature_version))
    brand_allowed_feature_enablement_types = {
        'ABCD': [_FeatureEnablementType.SOFT_BRANDED_LEGACY],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='image_id_0_or_1',
                    bit_positions=[4, 3, 2, 1,
                                   0], required_values=[0b00000, 0b00001]),
            ]),
        features.HWIDRequirement(
            description='scenario_2', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id_2',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0b00010]),
                features.HWIDBitStringRequirement(
                    description='bit_5_6_7_has_100_or_111',
                    bit_positions=[5, 6, 7], required_values=[0b001, 0b111]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    actual = matcher.GenerateLegacyPayload()
    self.assertEqual(
        actual,
        textwrap.dedent("""\
            feature_level: 1
            scope: SCOPE_DEVICES_0
            hwid_profiles {
              prefixes: "THEPROJ-ABCD"
              encoding_requirements {
                bit_locations: 4
                bit_locations: 3
                bit_locations: 2
                bit_locations: 1
                bit_locations: 0
                required_values: "00000"
                required_values: "10000"
              }
            }
            hwid_profiles {
              prefixes: "THEPROJ-ABCD"
              encoding_requirements {
                bit_locations: 4
                bit_locations: 3
                bit_locations: 2
                bit_locations: 1
                bit_locations: 0
                required_values: "01000"
              }
              encoding_requirements {
                bit_locations: 5
                bit_locations: 6
                bit_locations: 7
                required_values: "100"
                required_values: "111"
              }
            }
            """))

  def testConvertedHWIDFeatureMatcher_GenerateLegacyPayload_MultiLegacyBrands(
      self):
    feature_version = 1
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2],
                             feature_version=str(feature_version))
    brand_allowed_feature_enablement_types = {
        'ABCD': [_FeatureEnablementType.SOFT_BRANDED_LEGACY],
        'EFGH': [_FeatureEnablementType.SOFT_BRANDED_LEGACY],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='image_id_0_or_1',
                    bit_positions=[4, 3, 2, 1,
                                   0], required_values=[0b00000, 0b00001]),
            ]),
        features.HWIDRequirement(
            description='scenario_2', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id_2',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0b00010]),
                features.HWIDBitStringRequirement(
                    description='bit_5_6_7_has_100_or_111',
                    bit_positions=[5, 6, 7], required_values=[0b001, 0b111]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    actual = matcher.GenerateLegacyPayload()
    self.assertEqual(
        actual,
        textwrap.dedent("""\
            feature_level: 1
            scope: SCOPE_DEVICES_0
            hwid_profiles {
              prefixes: "THEPROJ-ABCD"
              prefixes: "THEPROJ-EFGH"
              encoding_requirements {
                bit_locations: 4
                bit_locations: 3
                bit_locations: 2
                bit_locations: 1
                bit_locations: 0
                required_values: "00000"
                required_values: "10000"
              }
            }
            hwid_profiles {
              prefixes: "THEPROJ-ABCD"
              prefixes: "THEPROJ-EFGH"
              encoding_requirements {
                bit_locations: 4
                bit_locations: 3
                bit_locations: 2
                bit_locations: 1
                bit_locations: 0
                required_values: "01000"
              }
              encoding_requirements {
                bit_locations: 5
                bit_locations: 6
                bit_locations: 7
                required_values: "100"
                required_values: "111"
              }
            }
            """))

  def testConvertedHWIDFeatureMatcher_GenerateLegacyPayload_NoFeature(self):
    feature_version = 0
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2],
                             feature_version=str(feature_version))
    brand_allowed_feature_enablement_types = {
        'ABCD': [_FeatureEnablementType.SOFT_BRANDED_LEGACY],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='image_id_0_or_1',
                    bit_positions=[4, 3, 2, 1,
                                   0], required_values=[0b00000, 0b00001]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    actual = matcher.GenerateLegacyPayload()
    self.assertEqual(actual, '')

  def testConvertedHWIDFeatureMatcher_GenerateLegacyPayload_PrefixOnlyForWaiver(
      self):
    feature_version = 1
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2],
                             feature_version=str(feature_version))
    brand_allowed_feature_enablement_types = {
        'ABCD': [_FeatureEnablementType.SOFT_BRANDED_WAIVER],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='image_id_0_or_1',
                    bit_positions=[4, 3, 2, 1,
                                   0], required_values=[0b00000, 0b00001]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    actual = matcher.GenerateLegacyPayload()
    self.assertEqual(
        actual,
        textwrap.dedent("""\
            feature_level: 1
            scope: SCOPE_DEVICES_0
            hwid_profiles {
              prefixes: "THEPROJ-ABCD"
              encoding_requirements {
                bit_locations: 8388608
                required_values: "1"
              }
            }
            """))

  def testConvertedHWIDFeatureMatcher_GenerateLegacyPayload_NoLegacyBrands(
      self):
    feature_version = 1
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2],
                             feature_version=str(feature_version))
    brand_allowed_feature_enablement_types = {
        'ABCD': [
            _FeatureEnablementType.DISABLED, _FeatureEnablementType.HARD_BRANDED
        ],
    }
    hwid_requirement_candidates = [
        features.HWIDRequirement(
            description='scenario_1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(
                    description='image_id_0_or_1',
                    bit_positions=[4, 3, 2, 1,
                                   0], required_values=[0b00000, 0b00001]),
            ]),
    ]

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(
        feature_version, brand_allowed_feature_enablement_types,
        hwid_requirement_candidates)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    actual = matcher.GenerateLegacyPayload()
    self.assertEqual(actual, '')


if __name__ == '__main__':
  unittest.main()
