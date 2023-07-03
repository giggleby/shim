#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import re
import textwrap
from typing import Iterable, Mapping, MutableMapping, NamedTuple, Optional, Sequence, Tuple
import unittest

from cros.factory.hwid.service.appengine import change_unit_utils
from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import rule as v3_rule
from cros.factory.utils import file_utils


# Shorter identifiers.
_HWIDComponentAnalysisResult = contents_analyzer.HWIDComponentAnalysisResult
_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus
_DiffStatus = contents_analyzer.DiffStatus
_ComponentNameInfo = contents_analyzer.ComponentNameInfo
_ApplyChangeUnitException = change_unit_utils.ApplyChangeUnitException
_SplitChangeUnitException = change_unit_utils.SplitChangeUnitException
_ChangeUnit = change_unit_utils.ChangeUnit
_CompChange = change_unit_utils.CompChange
_AddEncodingCombination = change_unit_utils.AddEncodingCombination
_ImageDesc = change_unit_utils.ImageDesc
_NewImageIdToExistingEncodingPattern = (
    change_unit_utils.NewImageIdToExistingEncodingPattern)
_AssignBitMappingToEncodingPattern = (
    change_unit_utils.AssignBitMappingToEncodingPattern)
_RenameImages = change_unit_utils.RenameImages
_ReplaceRules = change_unit_utils.ReplaceRules
_ChangeUnitManager = change_unit_utils.ChangeUnitManager
_ApprovalStatus = change_unit_utils.ApprovalStatus
_ChangeSplitResult = change_unit_utils.ChangeSplitResult

_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')
_TEST_DATABASE_NAME = 'test_change_unit_db.yaml'
_TEST_INITIAL_DB_NAME = 'test_database_initial.yaml'
_TEST_DATABASE_PATH = os.path.join(_TEST_DATA_PATH, _TEST_DATABASE_NAME)
_TEST_INITIAL_DB_PATH = os.path.join(_TEST_DATA_PATH, _TEST_INITIAL_DB_NAME)


def _ApplyUnifiedDiff(src: str, diff: str) -> str:
  src_lines = src.splitlines(keepends=True)
  src_next_line_no = 0
  result_lines = []
  for diff_line in diff.splitlines(keepends=True)[2:]:
    hunk_header = re.fullmatch(r'@@\s+-(\d+)(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@',
                               diff_line.rstrip())
    if hunk_header:
      hunk_begin_line_no = int(hunk_header.group(1)) - 1
      while src_next_line_no < hunk_begin_line_no:
        result_lines.append(src_lines[src_next_line_no])
        src_next_line_no += 1
      continue
    if diff_line[0] in (' ', '\n'):
      result_lines.append(src_lines[src_next_line_no])
      src_next_line_no += 1
    elif diff_line[0] == '-':
      src_next_line_no += 1
    elif diff_line[0] == '+':
      result_lines.append(diff_line[1:])
  return ''.join(result_lines + src_lines[src_next_line_no:])


def _GenerateNewComponentAnalysis(seq_no: int, comp_cls: str = 'comp_cls_1',
                                  comp_name_prefix: str = 'new_comp'):
  return _HWIDComponentAnalysisResult(
      comp_cls=comp_cls, comp_name=f'{comp_name_prefix}#{seq_no}',
      support_status='supported', is_newly_added=True, comp_name_info=None,
      seq_no=seq_no, comp_name_with_correct_seq_no=None, null_values=None,
      diff_prev=None, link_avl=False,
      probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO,
      skip_avl_check=False)


def _BuildHWIDComponentAnalysisResultWithDefaults(
    comp_cls: str, comp_name: str, seq_no: int,
    comp_info: database.ComponentInfo, is_newly_added: bool = False,
    comp_name_info: Optional[_ComponentNameInfo] = None,
    comp_name_with_correct_seq_no: Optional[str] = None,
    probe_value_alignment_status: _PVAlignmentStatus = (
        _PVAlignmentStatus.NO_PROBE_INFO), converter_changed: bool = False,
    diff_prev: Optional[_DiffStatus] = None, skip_avl_check: bool = False):

  null_values = comp_info.value_is_none
  support_status = comp_info.status
  if is_newly_added:
    if diff_prev:
      raise ValueError('Newly added component must not have DiffStatus.')
  else:
    if diff_prev is None:
      diff_prev = _DiffStatus(
          unchanged=True, name_changed=False, support_status_changed=False,
          values_changed=False, prev_comp_name=comp_name,
          prev_support_status=support_status,
          probe_value_alignment_status_changed=False,
          prev_probe_value_alignment_status=probe_value_alignment_status,
          converter_changed=converter_changed)
  return _HWIDComponentAnalysisResult(
      comp_cls=comp_cls, comp_name=comp_name, seq_no=seq_no,
      support_status=support_status, is_newly_added=is_newly_added,
      link_avl=bool(comp_name_info), comp_name_info=comp_name_info,
      comp_name_with_correct_seq_no=comp_name_with_correct_seq_no,
      null_values=null_values,
      probe_value_alignment_status=probe_value_alignment_status,
      diff_prev=diff_prev, skip_avl_check=skip_avl_check)


def _CollectHashMappingOfCombinations(
    db: database.Database, fields: Mapping[int, Mapping[str, Sequence[str]]]
) -> Mapping[int, Tuple[str, ...]]:
  ret: MutableMapping[int, Tuple[str, ...]] = {}
  for idx, item in fields.items():
    ret[idx] = tuple(
        db.GetComponents(comp_cls)[comp_name].comp_hash
        for comp_cls, comp_names in item.items()
        for comp_name in comp_names)
  return ret


def _RelaxedDBEqual(db1: database.Database, db2: database.Database) -> bool:
  """Performs relaxed database.Database.__eq__.

  This method performs an order-irrelavant comparison of encoded fields and
  components.  Note that the first combination (default comp) of each encoded
  field should still be the same.
  """

  if db1.project != db2.project:
    return False
  if db1.raw_encoding_patterns != db2.raw_encoding_patterns:
    return False
  if db1.raw_image_id != db2.raw_image_id:
    return False
  if db1.raw_pattern != db2.raw_pattern:
    return False
  if sorted(db1.encoded_fields) != sorted(db2.encoded_fields):
    return False
  for field_name in db1.encoded_fields:
    comb_list1 = db1.raw_encoded_fields.GetField(field_name)
    comb_list2 = db2.raw_encoded_fields.GetField(field_name)
    comb_hash1 = _CollectHashMappingOfCombinations(db1, comb_list1)
    comb_hash2 = _CollectHashMappingOfCombinations(db2, comb_list2)
    if comb_hash1[0] != comb_hash2[0]:
      return False
    if set(comb_hash1.values()) != set(comb_hash2.values()):
      return False
  comp_classes1 = db1.GetComponentClasses()
  comp_classes2 = db2.GetComponentClasses()
  if comp_classes1 != comp_classes2:
    return False
  for comp_cls in comp_classes1:
    comp_hashes1 = set(
        comp.comp_hash for comp in db1.GetComponents(comp_cls).values())
    comp_hashes2 = set(
        comp.comp_hash for comp in db2.GetComponents(comp_cls).values())
    if comp_hashes1 != comp_hashes2:
      return False
  if db1.raw_rules != db2.raw_rules:
    return False
  if db1.framework_version != db2.framework_version:
    return False
  return True


class ChangeUnitTestBase(unittest.TestCase):

  _DIFFS: Sequence[str] = []

  def setUp(self):
    super().setUp()
    self._base_db_content = file_utils.ReadFile(_TEST_DATABASE_PATH)
    self._base_db = database.Database.LoadData(self._base_db_content)
    self._builder = builder.DatabaseBuilder.FromFilePath(_TEST_DATABASE_PATH)

  def _LoadDBContentWithDiffPatched(self, diff: str) -> str:
    return _ApplyUnifiedDiff(self._base_db_content, diff)

  def _AssertApplyingPatchesEqualsData(self, expected: str,
                                       change_units: Iterable[_ChangeUnit]):

    with builder.DatabaseBuilder.FromFilePath(
        _TEST_DATABASE_PATH) as db_builder:
      for change_unit in change_units:
        change_unit.Patch(db_builder)

    self.assertEqual(expected,
                     db_builder.Build().DumpDataWithoutChecksum(internal=True))

  def testApplyPatchesExtractedFromDiff(self):
    """Shared implementation to verify change unit extraction and patch.

    To enable this test case, subclass should fill-in the test data to the
    class property `_DIFFS`.
    """

    if not self._DIFFS:
      raise self.skipTest('No test data.')

    for i, diff in enumerate(self._DIFFS):
      with self.subTest(diff_test_data_index=i):
        target_db_content = self._LoadDBContentWithDiffPatched(diff)
        target_db = database.Database.LoadData(target_db_content)

        change_unit_manager = _ChangeUnitManager(self._base_db, target_db)
        extracted = change_unit_manager.GetChangeUnits().values()

        self._AssertApplyingPatchesEqualsData(target_db_content, extracted)


class CompChangeTest(ChangeUnitTestBase):

  _DIFF_ADD_COMPONENT = textwrap.dedent('''\
      ---
      +++
      @@ -97,6 +97,12 @@
             comp_1_2:
               values:
                 value: '2'
      +      new_comp:
      +        values:
      +          field1: value1
      +          field2: value2
      +        information:
      +          info1: val1
         comp_cls_2:
           items:
             comp_2_1:
  ''')
  _DIFF_ADD_COMPONENT_INTERNAL = textwrap.dedent('''\
      ---
      +++
      @@ -97,6 +97,15 @@
             comp_1_2:
               values:
                 value: '2'
      +      new_comp:
      +        values: !link_avl
      +          converter: identifier1
      +          original_values:
      +            field1: value1
      +            field2: value2
      +          probe_value_matched: true
      +        information:
      +          info1: val1
         comp_cls_2:
           items:
             comp_2_1:
  ''')

  _DIFF_UPDATE_COMPONENT = textwrap.dedent('''\
      ---
      +++
      @@ -53,7 +53,7 @@
             storage: []
         comp_cls_1_field:
           0:
      -      comp_cls_1: comp_1_1
      +      comp_cls_1: updated_comp
           1:
             comp_cls_1: comp_1_2
         comp_cls_23_field:
      @@ -91,9 +91,13 @@
                 hash: '0'
         comp_cls_1:
           items:
      -      comp_1_1:
      +      updated_comp:
      +        status: deprecated
               values:
      -          value: '1'
      +          field1: value1
      +          field2: value2
      +        information:
      +          info1: val1
             comp_1_2:
               values:
                 value: '2'
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_ADD_COMPONENT,
      _DIFF_ADD_COMPONENT_INTERNAL,
      _DIFF_UPDATE_COMPONENT,
  ]

  def testPatchCompChange_New(self):
    comp_info = database.ComponentInfo({
        'field1': 'value1',
        'field2': 'value2'
    }, 'supported', {'info1': 'val1'})
    new_comp = _CompChange(
        _GenerateNewComponentAnalysis(3), comp_info.values,
        comp_info.information, comp_info.comp_hash)

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_ADD_COMPONENT),
        [new_comp])

  def testPatchCompChange_NewInternal(self):
    comp_info = database.ComponentInfo(
        v3_rule.AVLProbeValue(
            identifier='identifier1',
            probe_value_matched=True,
            values={
                'field1': 'value1',
                'field2': 'value2'
            },
        ), 'supported', {'info1': 'val1'})
    new_comp = _CompChange(
        _GenerateNewComponentAnalysis(3), comp_info.values,
        comp_info.information, comp_info.comp_hash)

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_ADD_COMPONENT_INTERNAL),
        [new_comp])

  def testPatchCompChange_Update(self):
    comp_info = database.ComponentInfo({
        'field1': 'value1',
        'field2': 'value2'
    }, 'deprecated', {'info1': 'val1'})
    update_comp = _CompChange(
        _BuildHWIDComponentAnalysisResultWithDefaults(
            comp_cls='comp_cls_1', comp_name='updated_comp', seq_no=2,
            comp_info=comp_info, diff_prev=_DiffStatus(
                unchanged=False, name_changed=True, support_status_changed=True,
                values_changed=True, prev_comp_name='comp_1_1',
                prev_support_status='supported',
                probe_value_alignment_status_changed=False,
                prev_probe_value_alignment_status=(
                    _PVAlignmentStatus.NO_PROBE_INFO),
                converter_changed=False)), comp_info.values,
        comp_info.information, comp_info.comp_hash)

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_UPDATE_COMPONENT),
        [update_comp])

  def testPatchCompChange_UpdateFail(self):
    # No matched comp name
    comp_info = database.ComponentInfo({
        'field1': 'value1',
        'field2': 'value2'
    }, 'deprecated', {'info1': 'val1'})
    update_comp = _CompChange(
        _BuildHWIDComponentAnalysisResultWithDefaults(
            comp_cls='comp_cls_1', comp_name='updated_comp', seq_no=2,
            comp_info=comp_info, diff_prev=_DiffStatus(
                unchanged=False, name_changed=True, support_status_changed=True,
                values_changed=True, prev_comp_name='no-such-comp-name',
                prev_support_status='supported',
                probe_value_alignment_status_changed=False,
                prev_probe_value_alignment_status=(
                    _PVAlignmentStatus.NO_PROBE_INFO),
                converter_changed=False)), comp_info.values,
        comp_info.information, comp_info.comp_hash)

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, update_comp.Patch,
                        self._builder)


class AddEncodingCombinationTest(ChangeUnitTestBase):

  _DIFF_ADD_FIRST_ENCODING_COMBINATION = textwrap.dedent('''\
       ---
       +++
       @@ -63,6 +63,11 @@
            1:
              comp_cls_2: comp_2_2
              comp_cls_3: comp_3_2
       +  new_field:
       +    0:
       +      comp_cls_2:
       +      - comp_2_1
       +      - comp_2_2

        components:
          mainboard:
  ''')
  _DIFF_ADD_FOLLOWING_ENCODING_COMBINATION = textwrap.dedent('''\
      ---
      +++
      @@ -25,6 +25,7 @@
         - ro_main_firmware_field: 1
         - comp_cls_1_field: 2
         - comp_cls_23_field: 2
      +  - comp_cls_1_field: 1

       encoded_fields:
         chassis_field:
      @@ -56,6 +57,21 @@
             comp_cls_1: comp_1_1
           1:
             comp_cls_1: comp_1_2
      +    2:
      +      comp_cls_1:
      +      - comp_1_2
      +      - comp_1_2
      +    3:
      +      comp_cls_1:
      +      - comp_1_2
      +      - comp_1_2
      +      - comp_1_2
      +    4:
      +      comp_cls_1:
      +      - comp_1_2
      +      - comp_1_2
      +      - comp_1_2
      +      - comp_1_2
         comp_cls_23_field:
           0:
             comp_cls_2: comp_2_1
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_ADD_FIRST_ENCODING_COMBINATION,
      _DIFF_ADD_FOLLOWING_ENCODING_COMBINATION,
  ]

  def setUp(self):
    super().setUp()
    self._comp_2_1_hash = database.ComponentInfo(values={
        'value': '1'
    }, status='supported').comp_hash
    self._comp_2_2_hash = database.ComponentInfo(values={
        'value': '2'
    }, status='supported').comp_hash
    self._comp_1_2_hash = database.ComponentInfo(values={
        'value': '2'
    }, status='supported').comp_hash
    # The following comp info are unused in this test, just dummy ones.
    self._comp_1_2_info = _GenerateNewComponentAnalysis(1)
    self._comp_2_1_info = _GenerateNewComponentAnalysis(2)
    self._comp_2_2_info = _GenerateNewComponentAnalysis(3)

  def testPatchAddFirstEncodingCombination_Success(self):
    first_encoding = _AddEncodingCombination(
        is_first=True, encoded_field_name='new_field', comp_cls='comp_cls_2',
        comp_hashes=[
            self._comp_2_1_hash,
            self._comp_2_2_hash,
        ], pattern_idxes=[], comp_analyses=[
            self._comp_2_1_info,
            self._comp_2_2_info,
        ])

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_FIRST_ENCODING_COMBINATION), [first_encoding])

  def testPatchAddFirstEncodingCombination_ExistingEncodedFieldName(self):
    first_encoding = _AddEncodingCombination(
        is_first=True, encoded_field_name='comp_cls_23_field',
        comp_cls='comp_cls_2', comp_hashes=[
            self._comp_2_1_hash,
            self._comp_2_2_hash,
        ], pattern_idxes=[], comp_analyses=[
            self._comp_2_1_info,
            self._comp_2_2_info,
        ])

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, first_encoding.Patch,
                        self._builder)

  def testPatchAddFollowingEncodingCombination_Success(self):
    # Add more combinations and check if the bit_length was enough.
    following_encodings = [
        _AddEncodingCombination(
            is_first=False, encoded_field_name='comp_cls_1_field',
            comp_cls='comp_cls_1', comp_hashes=[self._comp_1_2_hash] * i,
            pattern_idxes=[0], comp_analyses=[self._comp_1_2_info] * i)
        for i in range(2, 5)
    ]

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_FOLLOWING_ENCODING_COMBINATION), following_encodings)

  def testPatchAddFollowingEncodingCombination_NoSuchEncodedFieldName(self):
    following_encoding = _AddEncodingCombination(
        is_first=False, encoded_field_name='no_such_encoded_field',
        comp_cls='comp_cls_2',
        comp_hashes=[self._comp_2_1_hash,
                     self._comp_2_2_hash], pattern_idxes=[0], comp_analyses=[
                         self._comp_2_1_info,
                         self._comp_2_2_info,
                     ])

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, following_encoding.Patch,
                        self._builder)


class NewImageIdToExistingEncodingPatternTest(ChangeUnitTestBase):

  _DIFF_ADD_NEW_IMAGE_ID_TO_EXISTING_PATTERN = textwrap.dedent('''\
      ---
      +++
      @@ -8,11 +8,13 @@
       image_id:
         0: PROTO
         1: EVT
      +  3: DVT

       pattern:
       - image_ids:
         - 0
         - 1
      +  - 3
         encoding_scheme: base8192
         fields:
         - mainboard_field: 3
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_ADD_NEW_IMAGE_ID_TO_EXISTING_PATTERN,
  ]

  def testPatchNewImageToExistingEncodingPattern_Success(self):
    new_image_existing_pattern = (
        _NewImageIdToExistingEncodingPattern(image_name='DVT', image_id=3,
                                             pattern_idx=0, last=False))

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_NEW_IMAGE_ID_TO_EXISTING_PATTERN),
        [new_image_existing_pattern])


class AssignBitMappingToEncodingPatternTest(ChangeUnitTestBase):

  _DIFF_ADD_NEW_IMAGE_ID_TO_NEW_PATTERN = textwrap.dedent('''\
      ---
      +++
      @@ -8,6 +8,8 @@
       image_id:
         0: PROTO
         1: EVT
      +  3: DVT
      +  4: PVT

       pattern:
       - image_ids:
      @@ -25,6 +27,14 @@
         - ro_main_firmware_field: 1
         - comp_cls_1_field: 2
         - comp_cls_23_field: 2
      +- image_ids:
      +  - 3
      +  - 4
      +  encoding_scheme: base8192
      +  fields:
      +  - mainboard_field: 10
      +  - cpu_field: 5
      +  - comp_cls_1_field: 2

       encoded_fields:
         chassis_field:
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_ADD_NEW_IMAGE_ID_TO_NEW_PATTERN,
  ]

  def testPatchNewImageToNewEncodingPattern_Success(self):
    new_image_new_pattern = _AssignBitMappingToEncodingPattern(
        image_descs=[
            _ImageDesc(3, 'DVT'),
            _ImageDesc(4, 'PVT'),
        ], bit_mapping=[
            database.PatternField('mainboard_field', 10),
            database.PatternField('cpu_field', 5),
            database.PatternField('comp_cls_1_field', 2),
        ], contains_last=True)

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_NEW_IMAGE_ID_TO_NEW_PATTERN),
        [new_image_new_pattern])

  def testPatchNewImageToNewEncodingPattern_ImageIDAlreadyExists(self):
    new_image_new_pattern = _AssignBitMappingToEncodingPattern(
        image_descs=[
            _ImageDesc(1, 'DVT'),
            _ImageDesc(4, 'PVT'),
        ], bit_mapping=[], contains_last=True)

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, new_image_new_pattern.Patch,
                        self._builder)


class RenameImagesTest(ChangeUnitTestBase):

  _DIFF_RENAME_IMAGES = textwrap.dedent('''\
      ---
      +++
      @@ -6,8 +6,8 @@
         0: default

       image_id:
      -  0: PROTO
      -  1: EVT
      +  0: NEW_IMAGE_NAME0
      +  1: NEW_IMAGE_NAME1

       pattern:
       - image_ids:
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_RENAME_IMAGES,
  ]

  def testRenameImages_Success(self):

    rename_images = _RenameImages({
        0: 'NEW_IMAGE_NAME0',
        1: 'NEW_IMAGE_NAME1',
    })

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_RENAME_IMAGES),
        [rename_images])

  def testRenameImages_PatchFail(self):

    rename_images = _RenameImages({
        1: 'NEW_IMAGE_NAME1',
        2: 'NEW_IMAGE_NAME2',  # No such image id.
    })

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, rename_images.Patch,
                        self._builder)


class ReplaceRulesTest(ChangeUnitTestBase):

  _DIFF_REPLACE_RULES = textwrap.dedent('''\
      ---
      +++
      @@ -114,4 +114,10 @@
               values:
                 value: '2'

      -rules: []
      +rules:
      +- name: device_info.image_id
      +  evaluate: SetImageId('PVT')
      +- name: device_info.antenna
      +  evaluate: SetComponent('antenna', 'vendor1')
      +- name: device_info.pcb_vendor
      +  evaluate: SetComponent('pcb_vendor', 'vendor2')
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_REPLACE_RULES,
  ]

  def testPatchReplaceRules_Success(self):
    replace_rules = _ReplaceRules([{
        'name': 'device_info.image_id',
        'evaluate': "SetImageId('PVT')"
    }, {
        'name': 'device_info.antenna',
        'evaluate': "SetComponent('antenna', 'vendor1')"
    }, {
        'name': 'device_info.pcb_vendor',
        'evaluate': "SetComponent('pcb_vendor', 'vendor2')"
    }])

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_REPLACE_RULES),
        [replace_rules])


class MixedChangeUnitTest(ChangeUnitTestBase):

  _DIFF_VARIOUS_CHANGES = textwrap.dedent('''\
      ---
      +++
      @@ -6,13 +6,17 @@
         0: default

       image_id:
      -  0: PROTO
      -  1: EVT
      +  0: PVT2
      +  1: PVT
      +  3: DVT
      +  4: EVT
      +  5: PROTO

       pattern:
       - image_ids:
         - 0
         - 1
      +  - 5
         encoding_scheme: base8192
         fields:
         - mainboard_field: 3
      @@ -25,6 +29,16 @@
         - ro_main_firmware_field: 1
         - comp_cls_1_field: 2
         - comp_cls_23_field: 2
      +  - comp_cls_1_field: 1
      +- image_ids:
      +  - 3
      +  - 4
      +  encoding_scheme: base8192
      +  fields:
      +  - mainboard_field: 10
      +  - cpu_field: 5
      +  - comp_cls_1_field: 2
      +  - new_field: 0

       encoded_fields:
         chassis_field:
      @@ -53,9 +67,24 @@
             storage: []
         comp_cls_1_field:
           0:
      -      comp_cls_1: comp_1_1
      +      comp_cls_1: updated_comp
           1:
             comp_cls_1: comp_1_2
      +    2:
      +      comp_cls_1:
      +      - comp_1_2
      +      - comp_1_2
      +    3:
      +      comp_cls_1:
      +      - comp_1_2
      +      - comp_1_2
      +      - comp_1_2
      +    4:
      +      comp_cls_1:
      +      - comp_1_2
      +      - comp_1_2
      +      - comp_1_2
      +      - comp_1_2
         comp_cls_23_field:
           0:
             comp_cls_2: comp_2_1
      @@ -63,6 +92,11 @@
           1:
             comp_cls_2: comp_2_2
             comp_cls_3: comp_3_2
      +  new_field:
      +    0:
      +      comp_cls_2:
      +      - comp_2_1
      +      - comp_2_2

       components:
         mainboard:
      @@ -91,12 +125,21 @@
                 hash: '0'
         comp_cls_1:
           items:
      -      comp_1_1:
      +      updated_comp:
      +        status: deprecated
               values:
      -          value: '1'
      +          field1: value1
      +          field2: value2
      +        information:
      +          info1: val1
             comp_1_2:
               values:
                 value: '2'
      +      new_comp:
      +        values:
      +          field: value3
      +        information:
      +          info: val3
         comp_cls_2:
           items:
             comp_2_1:
      @@ -114,4 +157,10 @@
               values:
                 value: '2'

      -rules: []
      +rules:
      +- name: device_info.image_id
      +  evaluate: SetImageId('PVT')
      +- name: device_info.antenna
      +  evaluate: SetComponent('antenna', 'vendor1')
      +- name: device_info.pcb_vendor
      +  evaluate: SetComponent('pcb_vendor', 'vendor2')
  ''')

  _DIFFS: Sequence[str] = [
      _DIFF_VARIOUS_CHANGES,
  ]

  def testComponentRenameCollision(self):
    # Add a new component comp_1_2 and rename existing comp_1_2 to comp_1_3.
    comp_info_1 = database.ComponentInfo({'value': '3'}, 'supported')
    comp_info_2 = database.ComponentInfo({'value': '2'}, 'deprecated')
    comp_1_1_analysis = _BuildHWIDComponentAnalysisResultWithDefaults(
        comp_cls='comp_cls_1', comp_name='comp_1_1', seq_no=1,
        comp_info=comp_info_1)
    comp_1_2_analysis = _BuildHWIDComponentAnalysisResultWithDefaults(
        comp_cls='comp_cls_1', comp_name='comp_1_2', seq_no=3,
        comp_info=comp_info_1, is_newly_added=True)
    comp_1_3_analysis = _BuildHWIDComponentAnalysisResultWithDefaults(
        comp_cls='comp_cls_1', comp_name='comp_1_3', seq_no=2,
        comp_info=comp_info_2, diff_prev=_DiffStatus(
            unchanged=False, name_changed=True, support_status_changed=True,
            values_changed=True, prev_comp_name='comp_1_2',
            prev_support_status='supported',
            probe_value_alignment_status_changed=False,
            prev_probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO,
            converter_changed=False))
    comp_change_cus = [
        _CompChange(  # Add component.
            analysis_result=comp_1_2_analysis, probe_values=comp_info_1.values,
            information=comp_info_1.information,
            comp_hash=comp_info_1.comp_hash),
        _CompChange(  # Rename component.
            analysis_result=comp_1_3_analysis, probe_values=comp_info_2.values,
            information=comp_info_2.information,
            comp_hash=comp_info_2.comp_hash),
    ]
    comp_1_1_hash = database.ComponentInfo(values={
        'value': '1'
    }, status='supported').comp_hash
    comp_1_3_hash = database.ComponentInfo(values={
        'value': '2'
    }, status='deprecated').comp_hash
    comp_1_2_hash = database.ComponentInfo(values={
        'value': '3'
    }, status='supported').comp_hash
    add_comb_cus = [
        _AddEncodingCombination(
            is_first=True, encoded_field_name='new_comp_cls_1_field',
            comp_cls='comp_cls_1', comp_hashes=[comp_1_1_hash, comp_1_2_hash],
            pattern_idxes=[0], comp_analyses=[
                comp_1_1_analysis,
                comp_1_2_analysis,
            ]),
        _AddEncodingCombination(
            is_first=False, encoded_field_name='new_comp_cls_1_field',
            comp_cls='comp_cls_1', comp_hashes=[comp_1_1_hash, comp_1_3_hash],
            pattern_idxes=[0], comp_analyses=[
                comp_1_1_analysis,
                comp_1_3_analysis,
            ]),
    ]
    expected_diff = textwrap.dedent('''\
        ---
        +++
        @@ -25,6 +25,8 @@
           - ro_main_firmware_field: 1
           - comp_cls_1_field: 2
           - comp_cls_23_field: 2
        +  - new_comp_cls_1_field: 0
        +  - new_comp_cls_1_field: 1

         encoded_fields:
           chassis_field:
        @@ -55,7 +57,7 @@
             0:
               comp_cls_1: comp_1_1
             1:
        -      comp_cls_1: comp_1_2
        +      comp_cls_1: comp_1_3
           comp_cls_23_field:
             0:
               comp_cls_2: comp_2_1
        @@ -63,6 +65,15 @@
             1:
               comp_cls_2: comp_2_2
               comp_cls_3: comp_3_2
        +  new_comp_cls_1_field:
        +    0:
        +      comp_cls_1:
        +      - comp_1_1
        +      - comp_1_2#3
        +    1:
        +      comp_cls_1:
        +      - comp_1_1
        +      - comp_1_3

         components:
           mainboard:
        @@ -94,9 +105,13 @@
               comp_1_1:
                 values:
                   value: '1'
        -      comp_1_2:
        +      comp_1_3:
        +        status: deprecated
                 values:
                   value: '2'
        +      comp_1_2#3:
        +        values:
        +          value: '3'
           comp_cls_2:
             items:
               comp_2_1:
    ''')

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(expected_diff),
        comp_change_cus + add_comb_cus)


class ChangeUnitManagerTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._base_db_content = file_utils.ReadFile(_TEST_DATABASE_PATH)
    self._base_db = database.Database.LoadData(self._base_db_content)
    self.maxDiff = None

  def testDependencyGraph(self):
    new_db_content = _ApplyUnifiedDiff(
        self._base_db_content,
        textwrap.dedent('''\
            ---
            +++
            @@ -8,11 +8,17 @@
             image_id:
               0: PROTO
            -  1: EVT
            +  1: EVT_OLD
            +  2: EVT
            +  3: PHASE_NO_NEW_PATTERN_1
            +  4: PHASE_NO_NEW_PATTERN_2
            +  5: PHASE_NEW_PATTERN_1
            +  6: PHASE_NEW_PATTERN_2

             pattern:
             - image_ids:
               - 0
               - 1
            +  - 2
               encoding_scheme: base8192
               fields:
               - mainboard_field: 3
            @@ -25,6 +31,23 @@
               - ro_main_firmware_field: 1
               - comp_cls_1_field: 2
               - comp_cls_23_field: 2
            +  - new_field: 1
            +  - new_field: 1
            +- image_ids:
            +  - 3
            +  - 4
            +  encoding_scheme: base8192
            +  fields:
            +  - cpu_field: 5
            +  - comp_cls_1_field: 2
            +  - ro_main_firmware_field: 1
            +- image_ids:
            +  - 5
            +  - 6
            +  encoding_scheme: base8192
            +  fields:
            +  - comp_cls_1_field: 2
            +  - new_field: 2

             encoded_fields:
               chassis_field:
            @@ -53,7 +76,7 @@
                   storage: []
               comp_cls_1_field:
                 0:
            -      comp_cls_1: comp_1_1
            +      comp_cls_1: comp_1_1_renamed
                 1:
                   comp_cls_1: comp_1_2
               comp_cls_23_field:
            @@ -63,6 +86,17 @@
                 1:
                   comp_cls_2: comp_2_2
                   comp_cls_3: comp_3_2
            +  new_field:
            +    0:
            +      comp_cls_1: new_comp
            +    1:
            +      comp_cls_1:
            +      - comp_1_1_renamed
            +      - comp_1_2
            +    2:
            +      comp_cls_1:
            +      - new_comp
            +      - new_comp

             components:
               mainboard:
            @@ -91,12 +125,16 @@
                       hash: '0'
               comp_cls_1:
                 items:
            -      comp_1_1:
            +      comp_1_1_renamed:
                     values:
                       value: '1'
                   comp_1_2:
            +        status: unsupported
                     values:
                       value: '2'
            +      new_comp:
            +        values:
            +          value: '3'
               comp_cls_2:
                 items:
                   comp_2_1:
    '''))

    manager = _ChangeUnitManager(self._base_db,
                                 database.Database.LoadData(new_db_content))

    graph = manager.ExportDependencyGraph()

    self.assertDictEqual(
        {
            'AddEncodingCombination:new_field(first)-comp_cls_1:new_comp': {
                # Following combinations depends on the first.
                ('AddEncodingCombination:new_field-comp_cls_1:'
                 'comp_1_1_renamed,comp_1_2'),
                # Following combinations depends on the first.
                'AddEncodingCombination:new_field-comp_cls_1:new_comp,new_comp',
                # new_field is included in this image
                'AssignBitMappingToEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)'
            },
            # Not depended by other change units.
            ('AddEncodingCombination:new_field-comp_cls_1:'
             'comp_1_1_renamed,comp_1_2'):
                set(),
            # Not depended by other change units.
            'AddEncodingCombination:new_field-comp_cls_1:new_comp,new_comp':
                set(),
            # Component renamed is depended by combination addition.
            'CompChange:comp_cls_1:comp_1_1_renamed': {
                ('AddEncodingCombination:new_field-comp_cls_1:'
                 'comp_1_1_renamed,comp_1_2')
            },
            # Not depended by other change units (status change only).
            'CompChange:comp_cls_1:comp_1_2':
                set(),
            'CompChange:comp_cls_1:new_comp(new)': {
                # new_comp is mentioned at these combinations.
                'AddEncodingCombination:new_field(first)-comp_cls_1:new_comp',
                'AddEncodingCombination:new_field-comp_cls_1:new_comp,new_comp'
            },
            'NewImageIdToExistingEncodingPattern:EVT(2)': {
                # Change units containing the last image id depends on other
                # image id additions.
                'AssignBitMappingToEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)'
            },
            # Not depended by other change units.
            'AssignBitMappingToEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)':
                set(),
            'AssignBitMappingToEncodingPattern:PHASE_NO_NEW_PATTERN_1(3)': {
                # Change units containing the last image id depend on other
                # image id additions.
                'AssignBitMappingToEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)'
            },
            'RenameImages': {
                # Change units of adding new images depend on rename images.
                ('AssignBitMappingToEncodingPattern:'
                 'PHASE_NEW_PATTERN_1(5)(last)'),
                # Change units of adding new images depend on rename images.
                'AssignBitMappingToEncodingPattern:PHASE_NO_NEW_PATTERN_1(3)',
                # Change units of adding new images depend on rename images.
                'NewImageIdToExistingEncodingPattern:EVT(2)',
            },
        },
        graph)

  def testInternalStateNotChanged(self):
    new_encoded_field_db_content = _ApplyUnifiedDiff(
        self._base_db_content,
        textwrap.dedent('''\
            ---
            +++
            @@ -63,6 +63,11 @@
                 1:
                   comp_cls_2: comp_2_2
                   comp_cls_3: comp_3_2
            +  new_field:
            +    0:
            +      comp_cls_2:
            +      - comp_2_1
            +      - comp_2_2

             components:
               mainboard:
        '''))
    db_with_new_comp_field = database.Database.LoadData(
        new_encoded_field_db_content)

    _ChangeUnitManager(self._base_db, db_with_new_comp_field)

    self.assertCountEqual(
        {'comp_cls_2'}, db_with_new_comp_field.GetComponentClasses('new_field'))

  def testApprovalStatus(self):

    new_db_content = _ApplyUnifiedDiff(
        self._base_db_content,
        textwrap.dedent('''\
            ---
            +++
            @@ -63,6 +63,9 @@
                 1:
                   comp_cls_2: comp_2_2
                   comp_cls_3: comp_3_2
            +  new_field:
            +    0:
            +      comp_cls_1: new_comp

             components:
               mainboard:
            @@ -97,6 +100,9 @@
                   comp_1_2:
                     values:
                       value: '2'
            +      new_comp:
            +        values:
            +          value: '3'
               comp_cls_2:
                 items:
                   comp_2_1:
        '''))

    db_with_comp_only = database.Database.LoadData(
        _ApplyUnifiedDiff(
            self._base_db_content,
            textwrap.dedent('''\
                ---
                +++
                @@ -97,6 +97,9 @@
                       comp_1_2:
                         values:
                           value: '2'
                +      new_comp:
                +        values:
                +          value: '3'
                   comp_cls_2:
                     items:
                       comp_2_1:
            ''')))

    db_with_comp_and_encoded_fields = database.Database.LoadData(new_db_content)

    comp_change_repr = 'CompChange:comp_cls_1:new_comp(new)'
    add_combination_repr = (
        'AddEncodingCombination:new_field(first)-comp_cls_1:new_comp')

    class _TestDataset(NamedTuple):
      change_status: Mapping[str, _ApprovalStatus]
      expected_result: _ChangeSplitResult

    # As the identities are generated by uuid.uuid4(), the identities of
    # expected split result are filled with the repr's and updated later.
    test_datasets = [
        _TestDataset(
            change_status={
                comp_change_repr: _ApprovalStatus.AUTO_APPROVED,
                add_combination_repr: _ApprovalStatus.AUTO_APPROVED,
            }, expected_result=_ChangeSplitResult(
                auto_mergeable_db=db_with_comp_and_encoded_fields,
                auto_mergeable_change_unit_identities=[
                    comp_change_repr, add_combination_repr
                ], review_required_db=db_with_comp_and_encoded_fields,
                review_required_change_unit_identities=[])),
        _TestDataset(
            change_status={
                comp_change_repr: _ApprovalStatus.AUTO_APPROVED,
                add_combination_repr: _ApprovalStatus.MANUAL_REVIEW_REQUIRED,
            }, expected_result=_ChangeSplitResult(
                auto_mergeable_db=db_with_comp_only,
                auto_mergeable_change_unit_identities=[comp_change_repr],
                review_required_db=db_with_comp_and_encoded_fields,
                review_required_change_unit_identities=[add_combination_repr])),
        _TestDataset(
            change_status={
                comp_change_repr: _ApprovalStatus.MANUAL_REVIEW_REQUIRED,
                add_combination_repr: _ApprovalStatus.AUTO_APPROVED,
            }, expected_result=_ChangeSplitResult(
                auto_mergeable_db=self._base_db,
                auto_mergeable_change_unit_identities=[],
                review_required_db=db_with_comp_and_encoded_fields,
                review_required_change_unit_identities=[
                    comp_change_repr, add_combination_repr
                ])),
        _TestDataset(
            change_status={
                comp_change_repr: _ApprovalStatus.MANUAL_REVIEW_REQUIRED,
                add_combination_repr: _ApprovalStatus.MANUAL_REVIEW_REQUIRED,
            }, expected_result=_ChangeSplitResult(
                auto_mergeable_db=self._base_db,
                auto_mergeable_change_unit_identities=[],
                review_required_db=db_with_comp_and_encoded_fields,
                review_required_change_unit_identities=[
                    comp_change_repr, add_combination_repr
                ])),
    ]

    for test_dataset in test_datasets:
      with self.subTest(f'with approal status: {test_dataset.change_status!r}'):
        manager = _ChangeUnitManager(self._base_db,
                                     database.Database.LoadData(new_db_content))
        identity_map = {}
        for identity, change_unit in manager.GetChangeUnits().items():
          identity_map[repr(change_unit)] = identity

        expected_split_result = test_dataset.expected_result
        # Use identity_map to update the identifiers in expected_split_result.
        expected_split_result = expected_split_result._replace(
            auto_mergeable_change_unit_identities=[
                identity_map[repr_str] for repr_str in
                expected_split_result.auto_mergeable_change_unit_identities
            ], review_required_change_unit_identities=[
                identity_map[repr_str] for repr_str in
                expected_split_result.review_required_change_unit_identities
            ])

        manager.SetApprovalStatus({
            identity_map[comp_change_repr]:
                test_dataset.change_status[comp_change_repr],
            identity_map[add_combination_repr]:
                test_dataset.change_status[add_combination_repr],
        })
        change_split_result = manager.SplitChange()

        self.assertEqual(expected_split_result, change_split_result)

  def testPatchInitialDB(self):
    # Arrange.
    initial_db_content = file_utils.ReadFile(_TEST_INITIAL_DB_PATH)
    initial_db = database.Database.LoadData(initial_db_content)
    patched_db_content = _ApplyUnifiedDiff(
        initial_db_content,
        textwrap.dedent('''\
            ---
            +++
            @@ -7,17 +7,151 @@

             image_id:
               0: PROTO
            +  1: EVT

             pattern:
             - image_ids:
               - 0
            +  - 1
               encoding_scheme: base8192
            -  fields: []
            +  fields:
            +  - mainboard_field: 3
            +  - region_field: 5
            +  - dram_field: 5
            +  - cpu_field: 3
            +  - storage_field: 5
            +  - ro_main_firmware_field: 5
            +  - battery_field: 0
            +  - display_panel_field: 0
            +  - display_panel_field: 1
            +  - wireless_field: 1

             encoded_fields:
               region_field: !region_field []
            +  battery_field:
            +    0:
            +      battery: battery_1
            +  cpu_field:
            +    0:
            +      cpu: cpu_1
            +  display_panel_field:
            +    0:
            +      display_panel: display_panel_1
            +    1:
            +      display_panel: display_panel_2
            +  dram_field:
            +    0:
            +      dram:
            +      - dram_1
            +      - dram_2
            +      - dram_3
            +      - dram_4
            +  mainboard_field:
            +    0:
            +      mainboard: rev0
            +  ro_main_firmware_field:
            +    0:
            +      ro_main_firmware: ro_main_firmware_1
            +  storage_field:
            +    0:
            +      storage: storage_1
            +  wireless_field:
            +    0:
            +      wireless: wireless_1

             components:
               region: !region_component
            +  battery:
            +    items:
            +      battery_1:
            +        status: unqualified
            +        values:
            +          manufacturer: MANF_ID
            +          model_name: MD_NAME
            +          technology: OOI0
            +  mainboard:
            +    items:
            +      rev0:
            +        status: unqualified
            +        values:
            +          version: rev0
            +  cpu:
            +    items:
            +      cpu_1:
            +        status: unqualified
            +        values:
            +          cores: '4'
            +          model: Genuine Intel(R) 0000
            +  display_panel:
            +    items:
            +      display_panel_1:
            +        status: unqualified
            +        values:
            +          height: '901'
            +          product_id: '1234'
            +          vendor: ABC
            +          width: '5678'
            +      display_panel_2:
            +        status: unqualified
            +        values:
            +          height: '123'
            +          product_id: '4567'
            +          vendor: DEF
            +          width: '890'
            +  dram:
            +    items:
            +      dram_1:
            +        status: unqualified
            +        values:
            +          part: PART1
            +          size: '2048'
            +          slot: '0'
            +      dram_2:
            +        status: unqualified
            +        values:
            +          part: PART2
            +          size: '2048'
            +          slot: '1'
            +      dram_3:
            +        status: unqualified
            +        values:
            +          part: PART3
            +          size: '2048'
            +          slot: '2'
            +      dram_4:
            +        status: unqualified
            +        values:
            +          part: PART4
            +          size: '2048'
            +          slot: '3'
            +  storage:
            +    items:
            +      storage_1:
            +        status: unqualified
            +        values:
            +          mmc_hwrev: '0x0'
            +          mmc_manfid: '0x000001'
            +          mmc_name: MMC_NAME
            +          mmc_oemid: '0x0002'
            +          mmc_prv: '0x3'
            +          sectors: '12345678'
            +          size: '12345678'
            +          type: MMC
            +  ro_main_firmware:
            +    items:
            +      ro_main_firmware_1:
            +        status: unqualified
            +        values:
            +          hash: hash_value
            +          version: CHROMEBOOK.12345.0.0
            +  wireless:
            +    items:
            +      wireless_1:
            +        status: unqualified
            +        values:
            +          device: '0x1234'
            +          revision_id: '0x00'
            +          subsystem_device: '0x5678'
            +          vendor: '0x90ab'

             rules: []
        '''))
    patched_db = database.Database.LoadData(patched_db_content)

    # Act.
    manager = _ChangeUnitManager(initial_db, patched_db)
    change_units = manager.GetChangeUnits()
    manager.SetApprovalStatus({
        identity: _ApprovalStatus.MANUAL_REVIEW_REQUIRED
        for identity in change_units
    })
    split_result = manager.SplitChange()

    # Assert.
    self.assertTrue(
        _RelaxedDBEqual(patched_db, split_result.review_required_db))

  def testSplitChangeFail_RemoveImage(self):
    new_db_content = _ApplyUnifiedDiff(
        self._base_db_content,
        textwrap.dedent('''\
            ---
            +++
            @@ -7,12 +7,10 @@

             image_id:
               0: PROTO
            -  1: EVT

             pattern:
             - image_ids:
               - 0
            -  - 1
               encoding_scheme: base8192
               fields:
               - mainboard_field: 3
    '''))

    self.assertRaisesRegex(
        _SplitChangeUnitException,
        r'Image IDs are removed: {1}',
        _ChangeUnitManager,
        self._base_db,
        database.Database.LoadData(new_db_content),
    )


if __name__ == '__main__':
  unittest.main()
