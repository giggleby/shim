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
    virtual_dimm_property: Optional[Mapping] = None,
    storage_function_property: Optional[Mapping] = None,
    display_panel_property: Optional[Mapping] = None,
    camera_property: Optional[Mapping] = None,
) -> features.DLMComponentEntry:
  return features.DLMComponentEntry(
      dlm_id=features.DLMComponentEntryID(cid, qid),
      cpu_property=cpu_property and features.CPUProperty(**cpu_property),
      virtual_dimm_property=(
          virtual_dimm_property and
          features.VirtualDIMMProperty(**virtual_dimm_property)),
      storage_function_property=(
          storage_function_property and
          features.StorageFunctionProperty(**storage_function_property)),
      display_panel_property=(
          display_panel_property and
          features.DisplayProperty(**display_panel_property)),
      camera_property=(camera_property and
                       features.CameraProperty(**camera_property)),
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


class MemoryV1SpecTest(unittest.TestCase):

  def testIncorrectFieldName(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              not_dram_field:
                0:
                  dram: dram_1
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(
            1, virtual_dimm_property={'size_in_mb': 1024 * 32}),
    ])

    actual = features.MemoryV1Spec().FindSatisfiedEncodedValues(db, dlm_db)

    self.assertFalse(actual)

  def testIncorrectFieldComponents(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              dram_field:
                0:
                  cpu: cpu_1
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(
            1, virtual_dimm_property={'size_in_mb': 1024 * 32}),
    ])

    with self.assertRaises(features.HWIDDBNotSupportError):
      features.MemoryV1Spec().FindSatisfiedEncodedValues(db, dlm_db)

  def testMatch(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              dram_field:
                0:
                  dram: dram_1  # only 4GB
                1:
                  dram: [dram_1, dram_1]  # totall 8GB
                2:
                  dram: [dram_1, dram_1, dram_2]  # totall 16GB
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(1,
                                virtual_dimm_property={'size_in_mb': 1024 * 4}),
        _BuildDLMComponentEntry(2,
                                virtual_dimm_property={'size_in_mb': 1024 * 8}),
    ])

    actual = features.MemoryV1Spec().FindSatisfiedEncodedValues(db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'dram_field': (1, 2)})

  def testMatchIgnoreNonAVLComponent(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              dram_field:
                0:
                  dram: [dram_1, dram_1, dram_unknown]
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(1,
                                virtual_dimm_property={'size_in_mb': 1024 * 4}),
    ])

    actual = features.MemoryV1Spec().FindSatisfiedEncodedValues(db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'dram_field': (0, )})


class StorageV1SpecTest(unittest.TestCase):

  def testSuccess(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              storage_field:
                0:
                  storage: []
                1:
                  storage: storage_1
                2:
                  storage: storage_2
              storage_bridge_field:
                0:
                  storage_bridge: []
                1:
                  storage_bridge: storage_bridge_2
                2:
                  storage_bridge: storage_bridge_3
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(1,
                                storage_function_property={'size_in_gb': 64}),
        _BuildDLMComponentEntry(2,
                                storage_function_property={'size_in_gb': 128}),
        _BuildDLMComponentEntry(3,
                                storage_function_property={'size_in_gb': 256}),
    ])

    actual = features.StorageV1Spec().FindSatisfiedEncodedValues(db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {
        'storage_field': (2, ),
        'storage_bridge_field': (1, 2)
    })


class DisplayPanelV1SpecTest(unittest.TestCase):

  def testNormal(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              display_panel_field:
                0:
                  display_panel: display_panel_1
                1:
                  display_panel: display_panel_2
                2:
                  display_panel: display_panel_3
                3:
                  display_panel: display_panel_4
                4:
                  display_panel: display_panel_5
        """))
    dlm_db = _BuildDLMComponentDatabase([
        # CID 1 is not found.
        _BuildDLMComponentEntry(2),
        _BuildDLMComponentEntry(
            3,
            display_panel_property={
                'panel_type': features.DisplayPanelType.TN,  # incompatible
                'horizontal_resolution': 1920,
                'vertical_resolution': 1080,
                'compatible_versions': None,
            }),
        _BuildDLMComponentEntry(
            4,
            display_panel_property={
                'panel_type': features.DisplayPanelType.OTHER,
                'horizontal_resolution': 1080,  # incompatible
                'vertical_resolution': 720,
                'compatible_versions': None,
            }),
        _BuildDLMComponentEntry(
            5,
            display_panel_property={  # compatible
                'panel_type': features.DisplayPanelType.OTHER,
                'horizontal_resolution': 192000,
                'vertical_resolution': 108000,
                'compatible_versions': None,
            }),
    ])

    actual = features.DisplayPanelV1Spec().FindSatisfiedEncodedValues(
        db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'display_panel_field': (4, )})

  def testNormalWithResolvedCompatibleVersions(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              display_panel_field:
                0:
                  display_panel: display_panel_1
                1:
                  display_panel: display_panel_2
                2:
                  display_panel: display_panel_3
                3:
                  display_panel: display_panel_4
                4:
                  display_panel: display_panel_5
        """))

    def _BuildProperty(compatible_versions: features.Collection[int]):
      return {
          'panel_type': None,
          'horizontal_resolution': None,
          'vertical_resolution': None,
          'compatible_versions': compatible_versions
      }

    dlm_db = _BuildDLMComponentDatabase([
        # CID 1 is not found.
        # CID 2 is incompatible for not being a display panel.
        _BuildDLMComponentEntry(2),
        # CID 3 is incompatible for no compatible versions.
        _BuildDLMComponentEntry(3, display_panel_property=_BuildProperty([])),
        # CID 4 is incompatible for compatible version 0.
        _BuildDLMComponentEntry(4, display_panel_property=_BuildProperty([0])),
        # CID 5 is compatible.
        _BuildDLMComponentEntry(5, display_panel_property=_BuildProperty([1])),
    ])

    actual = features.DisplayPanelV1Spec().FindSatisfiedEncodedValues(
        db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'display_panel_field': (4, )})


class CameraV1SpecTest(unittest.TestCase):

  def testNormal(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              camera_field:
                0:
                  camera: [camera_10, camera_20]
                1:
                  camera: [camera_10, camera_21]
                2:
                  camera: [camera_10, camera_22]
                3:
                  camera: camera_10
                4:
                  camera: camera_21
                5:
                  camera: camera_22
        """))
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(
            10,
            camera_property={
                'is_user_facing': False,  # incompatible
                'has_tnr': True,
                'horizontal_resolution': 1920,
                'vertical_resolution': 1080,
                'compatible_versions': None,
            }),
        _BuildDLMComponentEntry(
            20,
            camera_property={
                'is_user_facing': True,
                'has_tnr': True,
                'horizontal_resolution': 1080,  # incompatible
                'vertical_resolution': 720,
                'compatible_versions': None,
            }),
        _BuildDLMComponentEntry(
            21,
            camera_property={
                'is_user_facing': True,
                'has_tnr': False,  # incompatible
                'horizontal_resolution': 1920,
                'vertical_resolution': 1080,
                'compatible_versions': None,
            }),
        _BuildDLMComponentEntry(
            22,
            camera_property={  # compatible
                'is_user_facing': True,
                'has_tnr': True,
                'horizontal_resolution': 1920,
                'vertical_resolution': 1080,
                'compatible_versions': None,
            }),
    ])

    actual = features.CameraV1Spec().FindSatisfiedEncodedValues(db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'camera_field': (2, 5)})

  def testNormalWithResolvedCompatibleVersions(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              camera_field:
                0:
                  camera: [camera_10, camera_20]
                1:
                  camera: [camera_10, camera_21]
                2:
                  camera: [camera_10, camera_22]
                3:
                  camera: camera_10
                4:
                  camera: camera_21
                5:
                  camera: camera_22
        """))

    def _BuildProperty(compatible_versions: features.Collection[int]):
      return {
          'is_user_facing': None,
          'has_tnr': None,
          'horizontal_resolution': None,
          'vertical_resolution': None,
          'compatible_versions': compatible_versions,
      }

    # Only CID 22 is compatible for having the target version in the compatible
    # version list.
    dlm_db = _BuildDLMComponentDatabase([
        _BuildDLMComponentEntry(10, camera_property=_BuildProperty([])),
        _BuildDLMComponentEntry(20, camera_property=_BuildProperty([0])),
        _BuildDLMComponentEntry(21, camera_property=_BuildProperty([0])),
        _BuildDLMComponentEntry(22, camera_property=_BuildProperty([0, 1])),
    ])

    actual = features.CameraV1Spec().FindSatisfiedEncodedValues(db, dlm_db)
    comparable_actual = {k: tuple(sorted(v))
                         for k, v in actual.items()}

    self.assertDictEqual(comparable_actual, {'camera_field': (2, 5)})


class BrandFeatureSpecResolverTest(unittest.TestCase):

  def testNoBrandFeatureVersion(self):
    db = _BuildDatabaseForTest('encoded_fields: {}')
    brand_feature_versions = {}
    dlm_db = _BuildDLMComponentDatabase([])
    resolver = features.BrandFeatureSpecResolver(
        {1: features.HWIDRequirementResolver([])})

    actual = resolver.DeduceBrandFeatureSpec(db, brand_feature_versions, dlm_db)

    self.assertFalse(actual)

  def testBrandFeatureVersion0(self):
    db = _BuildDatabaseForTest('encoded_fields: {}')
    brand_feature_versions = {
        'ZZCA': 0
    }
    dlm_db = _BuildDLMComponentDatabase([])
    resolver = features.BrandFeatureSpecResolver(
        {1: features.HWIDRequirementResolver([])})

    actual = resolver.DeduceBrandFeatureSpec(db, brand_feature_versions, dlm_db)

    self.assertFalse(actual)

  def testBrandFeatureVersionNotSupported(self):
    db = _BuildDatabaseForTest('encoded_fields: {}')
    brand_feature_versions = {
        'ZZCA': 99
    }
    dlm_db = _BuildDLMComponentDatabase([])
    resolver = features.BrandFeatureSpecResolver(
        {1: features.HWIDRequirementResolver([])})

    with self.assertRaises(ValueError):
      resolver.DeduceBrandFeatureSpec(db, brand_feature_versions, dlm_db)

  def testSuccess(self):
    db = _BuildDatabaseForTest(
        textwrap.dedent("""\
            encoded_fields:
              field1:
                0:
                  type1: name1
                1:
                  type1: name2
        """), pattern_section=textwrap.dedent("""\
            pattern:
            - image_ids: [0]
              encoding_scheme: base8192
              fields:
              - field1: 1
            """))
    dlm_db = _BuildDLMComponentDatabase([])
    stub_hwid_spec_for_v1 = _StubHWIDSpec('the_stub_spec1', db, dlm_db,
                                          {'field1': [0]})
    stub_hwid_spec_for_v2 = _StubHWIDSpec('the_stub_spec2', db, dlm_db,
                                          {'field1': [1]})
    brand_feature_versions = {
        'ZZCA': 1,
        'ZZCB': 2
    }
    resolver = features.BrandFeatureSpecResolver({
        1: features.HWIDRequirementResolver([stub_hwid_spec_for_v1]),
        2: features.HWIDRequirementResolver([stub_hwid_spec_for_v2])
    })

    actual = resolver.DeduceBrandFeatureSpec(db, brand_feature_versions, dlm_db)

    comparable_actual = {
        brand: features.BrandFeatureSpec(
            brand=elem.brand, feature_version=elem.feature_version,
            hwid_requirement_candidates=tuple(
                _ToComparableHWIDRequirements(
                    elem.hwid_requirement_candidates)))
        for brand, elem in actual.items()
    }

    self.assertEqual(
        comparable_actual, {
            'ZZCA':
                features.BrandFeatureSpec(
                    brand='ZZCA', feature_version=1,
                    hwid_requirement_candidates=(features.HWIDRequirement(
                        description='pattern_idx=0', bit_string_prerequisites=(
                            features.HWIDBitStringRequirement(
                                description='image_id',
                                bit_positions=(4, 3, 2, 1, 0),
                                required_values=(0, )),
                            features.HWIDBitStringRequirement(
                                description=(
                                    'the_stub_spec1,encoded_field=field1'),
                                bit_positions=(5, ), required_values=(0, )),
                        )), )),
            'ZZCB':
                features.BrandFeatureSpec(
                    brand='ZZCB', feature_version=2,
                    hwid_requirement_candidates=(features.HWIDRequirement(
                        description='pattern_idx=0', bit_string_prerequisites=(
                            features.HWIDBitStringRequirement(
                                description='image_id',
                                bit_positions=(4, 3, 2, 1, 0),
                                required_values=(0, )),
                            features.HWIDBitStringRequirement(
                                description=(
                                    'the_stub_spec2,encoded_field=field1'),
                                bit_positions=(5, ), required_values=(1, )),
                        )), )),
        })


if __name__ == '__main__':
  unittest.main()
