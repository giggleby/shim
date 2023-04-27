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


def _BuildHWIDDBForTest(
    project_name: str,
    image_ids: features.Collection[int]) -> db_module.Database:
  image_id_part = {
      'image_id': {
          image_id: f'THE_IMAGE_ID_{image_id}'
          for image_id in image_ids
      }
  }
  pattern_part = {
      'pattern': [{
          'image_ids': list(image_ids),
          'encoding_scheme': 'base8192',
          'fields': [{
              'dummy_field': 100
          }],
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
      textwrap.dedent("""\
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
          """),
  ]))


class HWIDFeatureMatcherBuilderTest(unittest.TestCase):

  @mock.patch('hashlib.sha256')
  def testConvertedHWIDFeatureMatcherCanGenerateFeatureRequirementPayload(
      self, mock_sha256):
    mock_sha256.return_value.hexdigest.return_value = 'the_fixed_checksum'
    db = _BuildHWIDDBForTest(project_name='UNUSEDPROJ', image_ids=[0, 1, 2])
    brand_feature_specs = {
        'ABCD':
            features.BrandFeatureSpec(
                brand='ABCD', feature_version=1, hwid_requirement_candidates=[
                    features.HWIDRequirement(
                        description='scenario_1', bit_string_prerequisites=[
                            features.HWIDBitStringRequirement(
                                description='bit_string_prerequisite1-1',
                                bit_positions=[2, 4, 5],
                                required_values=[0b001, 0b101]),
                        ]),
                    features.HWIDRequirement(
                        description='scenario_2', bit_string_prerequisites=[
                            features.HWIDBitStringRequirement(
                                description='bit_string_prerequisite2-1',
                                bit_positions=[2, 4,
                                               5], required_values=[0b000]),
                            features.HWIDBitStringRequirement(
                                description='bit_string_prerequisite2-1',
                                bit_positions=[3, 6], required_values=[0b01]),
                        ]),
                ]),
    }

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(brand_feature_specs)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)
    actual = matcher.GenerateHWIDFeatureRequirementPayload()

    self.assertEqual(
        actual,
        textwrap.dedent("""\
            # checksum: the_fixed_checksum
            brand_specs {
              key: "ABCD"
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
    db = _BuildHWIDDBForTest(project_name='THEPROJ', image_ids=[0, 1, 2])
    brand_feature_specs = {
        'ABCD':
            features.BrandFeatureSpec(
                brand='ABCD', feature_version=1, hwid_requirement_candidates=[
                    features.HWIDRequirement(
                        description='scenario_1', bit_string_prerequisites=[
                            features.HWIDBitStringRequirement(
                                description='image_id_0_or_1',
                                bit_positions=[4, 3, 2, 1, 0],
                                required_values=[0b00000, 0b00001]),
                        ]),
                    features.HWIDRequirement(
                        description='scenario_2', bit_string_prerequisites=[
                            features.HWIDBitStringRequirement(
                                description='image_id_2',
                                bit_positions=[4, 3, 2, 1,
                                               0], required_values=[0b00010]),
                            features.HWIDBitStringRequirement(
                                description='bit_5_6_7_has_100_or_111',
                                bit_positions=[5, 6, 7],
                                required_values=[0b001, 0b111]),
                        ]),
                ]),
    }

    builder = feature_matching.HWIDFeatureMatcherBuilder()
    source = builder.GenerateFeatureMatcherRawSource(brand_feature_specs)
    matcher = builder.CreateHWIDFeatureMatcher(db, source)

    for hwid_string, expected_version_or_error in (
        ('NOTTHISPROJ-ABCD A2A-B47', ValueError),
        ('THEPROJ A2A-B47', 0),
        ('THEPROJ-ABCD A8A-B4T', 1),  # match scenario_1
        ('THEPROJ-ABCD B2A-B5L', 1),  # match scenario_1
        ('THEPROJ-ABCD C8A-B8Y', 0),  # not match bit_5_6_7_has_100_or_111
        ('THEPROJ-ABCD C6A-B8S', 1),  # match scenario_2
    ):
      if isinstance(expected_version_or_error, int):
        with self.subTest(hwid_string=hwid_string,
                          expected_version=expected_version_or_error):
          actual = matcher.Match(hwid_string)
          self.assertEqual(actual, expected_version_or_error)
      else:
        with self.subTest(hwid_string=hwid_string,
                          expected_error=expected_version_or_error):
          with self.assertRaises(expected_version_or_error):
            matcher.Match(hwid_string)


if __name__ == '__main__':
  unittest.main()
