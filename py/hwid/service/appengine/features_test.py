#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import itertools
import textwrap
from typing import Collection, Mapping, Optional
import unittest

import yaml

from cros.factory.hwid.service.appengine import features
from cros.factory.hwid.v3 import database as db_module
from cros.factory.utils import type_utils


def _BuildDLMComponentEntry(
    cid: int,
    qid: Optional[int] = None,
    cpu_property: Optional[Mapping] = None,
) -> features.DLMComponentEntry:
  return features.DLMComponentEntry(
      dlm_id=features.DLMComponentEntryID(cid, qid),
      cpu_property=cpu_property and features.CPUProperty(**cpu_property),
  )


def _BuildDLMComponentDatabase(
    entries: features.Collection[features.DLMComponentEntry]
) -> features.DLMComponentDatabase:
  return {entry.dlm_id: entry
          for entry in entries}


def _BuildDatabaseForTest(
    encoded_fields_section: str,
    pattern_section: Optional[str] = None) -> db_module.Database:
  """Builds a valid HWID DB instance from minimum hints.

  Args:
    encoded_fields_section: The encoded fields section in the HWID DB.
    pattern_section: The pattern section in the HWID DB, or `None` to generate a
      dummy one that allocates no bits.

  Returns:
    A HWID DB instance.
  """
  if pattern_section is None:
    pattern_section = textwrap.dedent("""\
        pattern:
        - image_ids: [0]
          encoding_scheme: base8192
          fields: []
        """)
  all_image_ids = list(
      itertools.chain.from_iterable(
          inst['image_ids']
          for inst in yaml.safe_load(pattern_section)['pattern']))
  image_id_part = {
      'image_id': {
          image_id: f'THE_IMAGE_ID_{image_id}'
          for image_id in all_image_ids
      }
  }

  encoded_fields_data_object = (
      yaml.safe_load(encoded_fields_section)['encoded_fields'])

  component_part = {
      'components': {}
  }
  for comp_combo in itertools.chain.from_iterable(
      map(lambda a: a.values(), encoded_fields_data_object.values())):
    for comp_type, comp_name_or_comp_names in comp_combo.items():
      component_part['components'].setdefault(comp_type, {'items': {}})
      for comp_name in type_utils.MakeList(comp_name_or_comp_names):
        component_part['components'][comp_type]['items'].setdefault(
            comp_name, {
                'status': 'supported',
                'values': {
                    'unused_key': f'unused_unique_value_{comp_name}'
                }
            })
  db_text = '\n'.join([
      textwrap.dedent("""\
          checksum:
          project: UNUSED_NAME
          encoding_patterns:
            0: default"""),
      yaml.safe_dump(image_id_part), pattern_section, encoded_fields_section,
      yaml.safe_dump(component_part), 'rules: []'
  ])
  return db_module.Database.LoadData(db_text)


class _StubHWIDSpec(features.HWIDSpec):

  def __init__(self, name: str, db: db_module.Database,
               dlm_db: features.DLMComponentDatabase,
               encoded_values: Mapping[str, Collection[int]]):
    self._name = name
    self._db = db
    self._dlm_db = dlm_db
    self._encoded_values = encoded_values

  def GetName(self):
    return self._name

  def FindSatisfiedEncodedValues(self, db, dlm_db):
    if db == self._db and dlm_db == self._dlm_db:
      return self._encoded_values
    return {}


def _ToComparableHWIDBitStringRequirement(
    inst: features.HWIDBitStringRequirement
) -> features.HWIDBitStringRequirement:
  return features.HWIDBitStringRequirement(
      description=inst.description, bit_positions=tuple(inst.bit_positions),
      required_values=tuple(sorted(inst.required_values)))


def _ToComparableHWIDRequirement(
    source: features.HWIDRequirement) -> features.HWIDRequirement:
  return features.HWIDRequirement(
      description=source.description, bit_string_prerequisites=tuple(
          sorted(
              _ToComparableHWIDBitStringRequirement(r)
              for r in source.bit_string_prerequisites)))


def _ToComparableHWIDRequirements(
    sources: features.Collection[features.HWIDRequirement]
) -> features.Collection[features.HWIDRequirement]:
  return list(map(_ToComparableHWIDRequirement, sources))


class HWIDRequirementResolverTest(unittest.TestCase):

  def testSingleSpecNotMatch(self):
    # arrange, with a regular HWID DB, a regular DLM component database
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: comp_name_1
                1:
                  comp_type1: comp_name_2
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 1
            """))
    dlm_db = {}
    # and with the underlying HWID spec reports no matched fields
    hwid_spec = _StubHWIDSpec('unused_spec_name', db, dlm_db, {})

    # act
    resolver = features.HWIDRequirementResolver([hwid_spec])
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that now HWID requirement candidates are returned
    self.assertCountEqual(actual, [])

  def testSingleSpecMatch(self):
    # arrange, with an one-field HWID DB
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: []
                1:
                  comp_type1: comp_name1
                2:
                  comp_type1: comp_name2
                3:
                  comp_type1: comp_name3
                4:
                  comp_type1: comp_name4
                5:
                  comp_type1: comp_name5
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 2
              - field1: 1
            """))
    # and with a regular DLM component database
    dlm_db = {}
    # and with the underlying HWID spec reports some encoded field values are
    # matched
    # When, field1 value is 1, 3, 5, the bit strings in HWID correspondingly are
    # `<image_id_bits>01 0`, `<image_id_bits>11 0`, `<image_id_bits>01 1`.
    hwid_spec = _StubHWIDSpec('the_stub_spec', db, dlm_db,
                              {'field1': [1, 3, 5]})

    # act
    resolver = features.HWIDRequirementResolver([hwid_spec])
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that the generated HWID requirement candidates correctly record
    # the bit values.
    expected_field1_bit_positions = [5, 6, 7]
    expected_field1_values = [
        int(bit_string[::-1], 2) for bit_string in ('010', '110', '011')]
    expect = [
        features.HWIDRequirement(
            description='pattern_idx=0', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec,encoded_field=field1',
                    bit_positions=expected_field1_bit_positions,
                    required_values=expected_field1_values),
            ]),
    ]
    self.assertCountEqual(
        _ToComparableHWIDRequirements(actual),
        _ToComparableHWIDRequirements(expect))

  def testSingleSpecMatchDifferentFields(self):
    # arrange, with a HWID DB with two fields
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: 'comp_name0'
                1:
                  comp_type1: 'comp_name1'
              field2:
                0:
                  comp_type2: 'comp_name2'
                1:
                  comp_type2: 'comp_name3'
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 4
              - field2: 4
            """))
    # and with a regular DLM component database
    dlm_db = {}
    # and with the underlying HWID spec reports value matches from both fields
    hwid_spec = _StubHWIDSpec('the_stub_spec', db, dlm_db, {
        'field1': [0],
        'field2': [1],
    })

    # act
    resolver = features.HWIDRequirementResolver([hwid_spec])
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that the returned HWID requirements capture both the field value
    # matches
    expect = [
        features.HWIDRequirement(
            description=(
                'pattern_idx=0,variant=(the_stub_spec,encoded_field=field1)'),
            bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec,encoded_field=field1',
                    bit_positions=[5, 6, 7, 8], required_values=[0b0000]),
            ]),
        features.HWIDRequirement(
            description=(
                'pattern_idx=0,variant=(the_stub_spec,encoded_field=field2)'),
            bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec,encoded_field=field2',
                    bit_positions=[9, 10, 11, 12], required_values=[0b1000]),
            ]),
    ]
    self.assertCountEqual(
        _ToComparableHWIDRequirements(actual),
        _ToComparableHWIDRequirements(expect))

  def testSingleSpecMatchButNotInPattern(self):
    # arrange, with a HWID DB with a field not exist in the encoded pattern
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: []
                1:
                  comp_type1: 'comp_name1'
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields: []
            """))
    # and with a regular DLM component database
    dlm_db = {}
    # and with the underlying HWID spec reports a value match of the field
    hwid_spec = _StubHWIDSpec('the_stub_spec', db, dlm_db, {'field1': [0]})

    # act
    resolver = features.HWIDRequirementResolver([hwid_spec])
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that the returned no HWID requirement candidates
    expect = []
    self.assertCountEqual(
        _ToComparableHWIDRequirements(actual),
        _ToComparableHWIDRequirements(expect))

  def testSingleSpecMatchFieldValue0AndNoBitAllocationInPattern(self):
    # arrange, with a HWID DB with a field occupies 0 bits in an encoded pattern
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: []
                1:
                  comp_type1: 'comp_name1'
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 0
            - image_ids: [1]  # This additional pattern makes the generated HWID
                              # DB valid.
              encoding_scheme: base8192
              fields:
              - field1: 1
            """))
    # and with a regular DLM component database
    dlm_db = {}
    # and with the underlying HWID spec reports matched encoded value being 0
    hwid_spec = _StubHWIDSpec('the_stub_spec', db, dlm_db, {'field1': [0]})

    # act
    resolver = features.HWIDRequirementResolver([hwid_spec])
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that the returned HWID requirement candidates don't check the
    # bit values of that field because the condition will always fulfilled.
    expect = features.HWIDRequirement(
        description='pattern_idx=0', bit_string_prerequisites=[
            features.HWIDBitStringRequirement(description='image_id',
                                              bit_positions=[4, 3, 2, 1, 0],
                                              required_values=[0]),
        ])
    self.assertIn(
        _ToComparableHWIDRequirement(expect),
        _ToComparableHWIDRequirements(actual))

  def testSingleSpecMatchFieldValueNAndNoEnoughBitAllocationInPattern(self):
    # arrange, with a HWID DB with a field occupies insufficient bits in an
    # encoded pattern
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: []
                1:
                  comp_type1: 'comp_name1'
                2:
                  comp_type1: 'comp_name2'
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 1
            - image_ids: [1]  # This additional pattern makes the generated HWID
                              # DB valid.
              encoding_scheme: base8192
              fields:
              - field1: 2
            """))
    # and with a regular DLM component database
    dlm_db = {}
    # and with the underlying HWID spec reports matched encoded value being the
    # maximum one
    hwid_spec = _StubHWIDSpec('the_stub_spec', db, dlm_db, {'field1': [2]})

    # act
    resolver = features.HWIDRequirementResolver([hwid_spec])
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that no HWID requirement candidates are returned because no HWID
    # strings can fulfill the conditions.
    self.assertEqual(len(actual), 1)

  def testMultipleSpecMatchInMultiPattern(self):
    # arrange, with a HWID DB with multiple fields and multiple encoded patterns
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  comp_type1: []
                1:
                  comp_type1: 'comp_name1'
              field2:
                0:
                  comp_type2: []
                1:
                  comp_type2: 'comp_name2'
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 1
              - field2: 1
            - image_ids: [1, 2]
              encoding_scheme: base8192
              fields:
              - field1: 2
              - field2: 2
            - image_ids: [3]
              encoding_scheme: base8192
              fields:
              - field1: 2  # No bits for field2, so it should not be matched.
            """))
    # and with a regular DLM component database
    dlm_db = {}
    # and with the underlying HWID specs return required encoded values
    # of both fields.
    hwid_specs = [
        _StubHWIDSpec('the_stub_spec1', db, dlm_db, {'field1': [0]}),
        _StubHWIDSpec('the_stub_spec2', db, dlm_db, {'field2': [1]}),
    ]

    # act
    resolver = features.HWIDRequirementResolver(hwid_specs)
    actual = resolver.DeduceHWIDRequirementCandidates(db, dlm_db)

    # assert that the returned HWID requirement candidates combine the
    # conditions correctly
    expect = [
        features.HWIDRequirement(
            description='pattern_idx=0', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[0]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec1,encoded_field=field1',
                    bit_positions=[5], required_values=[0b0]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec2,encoded_field=field2',
                    bit_positions=[6], required_values=[0b1]),
            ]),
        features.HWIDRequirement(
            description='pattern_idx=1', bit_string_prerequisites=[
                features.HWIDBitStringRequirement(description='image_id',
                                                  bit_positions=[4, 3, 2, 1, 0],
                                                  required_values=[1, 2]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec1,encoded_field=field1',
                    bit_positions=[5, 6], required_values=[0b00]),
                features.HWIDBitStringRequirement(
                    description='the_stub_spec2,encoded_field=field2',
                    bit_positions=[7, 8], required_values=[0b10]),
            ]),
    ]
    self.assertCountEqual(
        _ToComparableHWIDRequirements(actual),
        _ToComparableHWIDRequirements(expect))


class CPUV1SpecTest(unittest.TestCase):

  def testNormal(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              cpu_field:
                0:
                  cpu: cpu_1
                1:
                  cpu: cpu_2
                2:
                  cpu: cpu_3
                3:
                  cpu: cpu_4
                4:
                  cpu: cpu_3#2
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(2),
        _BuildDLMComponentEntry(3, cpu_property={'compatible_versions': [1,
                                                                         2]}),
        _BuildDLMComponentEntry(4, cpu_property={'compatible_versions': [2,
                                                                         3]}),
    ])

    actual = features.CPUV1Spec().FindSatisfiedEncodedValues(db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'cpu_field': (2, 4)})


if __name__ == '__main__':
  unittest.main()
