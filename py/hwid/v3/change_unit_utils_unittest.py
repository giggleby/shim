#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import re
import textwrap
from typing import Sequence
import unittest

from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import change_unit_utils
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database
from cros.factory.utils import file_utils

# Shorter identifiers.
_HWIDComponentAnalysisResult = contents_analyzer.HWIDComponentAnalysisResult
_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus
_DiffStatus = contents_analyzer.DiffStatus
_ApplyChangeUnitException = change_unit_utils.ApplyChangeUnitException
_ChangeUnit = change_unit_utils.ChangeUnit
_CompChange = change_unit_utils.CompChange
_AddEncodingCombination = change_unit_utils.AddEncodingCombination
_ImageDesc = change_unit_utils.ImageDesc
_NewImageIdToExistingEncodingPattern = (
    change_unit_utils.NewImageIdToExistingEncodingPattern)
_NewImageIdToNewEncodingPattern = (
    change_unit_utils.NewImageIdToNewEncodingPattern)
_ReplaceRules = change_unit_utils.ReplaceRules

_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')
_TEST_DATABASE_NAME = 'test-change-unit-db.yaml'
_TEST_DATABASE_PATH = os.path.join(_TEST_DATA_PATH, _TEST_DATABASE_NAME)


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
      probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO)


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
                                       change_units: Sequence[_ChangeUnit]):

    with builder.DatabaseBuilder.FromFilePath(
        _TEST_DATABASE_PATH) as db_builder:
      for change_unit in change_units:
        change_unit.Patch(db_builder)

    self.assertEqual(expected, db_builder.Build().DumpDataWithoutChecksum())

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

        extracted = change_unit_utils.ExtractChangeUnitsFromDBChanges(
            self._base_db, target_db)

        self._AssertApplyingPatchesEqualsData(target_db_content, extracted)


class CompChangeTest(ChangeUnitTestBase):

  _DIFF_ADD_COMPONENT = textwrap.dedent('''\
      ---
      +++
      @@ -98,6 +98,12 @@
             comp_1_2:
               values:
                 value: '2'
      +      new_comp#3:
      +        values:
      +          field1: value1
      +          field2: value2
      +        information:
      +          info1: val1
         comp_cls_2:
           items:
             comp_2_1:
  ''')

  _DIFF_UPDATE_COMPONENT = textwrap.dedent('''\
      ---
      +++
      @@ -54,7 +54,7 @@
             storage: []
         comp_cls_1_field:
           0:
      -      comp_cls_1: comp_1_1
      +      comp_cls_1: updated_comp
           1:
             comp_cls_1: comp_1_2
         comp_cls_23_field:
      @@ -92,9 +92,13 @@
                 hash": '0'
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
      _DIFF_UPDATE_COMPONENT,
  ]

  def testPatchCompChange_New(self):
    new_comp = _CompChange(
        _GenerateNewComponentAnalysis(3), {
            'field1': 'value1',
            'field2': 'value2'
        }, {'info1': 'val1'})

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_ADD_COMPONENT),
        [new_comp])

  def testPatchCompChange_Update(self):
    update_comp = _CompChange(
        _HWIDComponentAnalysisResult(
            comp_cls='comp_cls_1', comp_name='updated_comp',
            support_status='deprecated', is_newly_added=False,
            comp_name_info=None, seq_no=2, comp_name_with_correct_seq_no=None,
            null_values=None, diff_prev=_DiffStatus(
                unchanged=False, name_changed=True, support_status_changed=True,
                values_changed=True, prev_comp_name='comp_1_1',
                prev_support_status='supported',
                probe_value_alignment_status_changed=False,
                prev_probe_value_alignment_status=(
                    _PVAlignmentStatus.NO_PROBE_INFO)), link_avl=False,
            probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO), {
                'field1': 'value1',
                'field2': 'value2'
            }, {'info1': 'val1'})

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(self._DIFF_UPDATE_COMPONENT),
        [update_comp])

  def testPatchCompChange_UpdateFail(self):
    # No matched comp name
    update_comp = _CompChange(
        _HWIDComponentAnalysisResult(
            comp_cls='comp_cls_1', comp_name='updated_comp',
            support_status='deprecated', is_newly_added=False,
            comp_name_info=None, seq_no=2, comp_name_with_correct_seq_no=None,
            null_values=None, diff_prev=_DiffStatus(
                unchanged=False, name_changed=True, support_status_changed=True,
                values_changed=True, prev_comp_name='no-such-comp-name',
                prev_support_status='supported',
                probe_value_alignment_status_changed=False,
                prev_probe_value_alignment_status=(
                    _PVAlignmentStatus.NO_PROBE_INFO)), link_avl=False,
            probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO), {
                'field1': 'value1',
                'field2': 'value2'
            }, {'info1': 'val1'})

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, update_comp.Patch,
                        self._builder)


class AddEncodingCombinationTest(ChangeUnitTestBase):

  _DIFF_ADD_FIRST_ENCODING_COMBINATION = textwrap.dedent('''\
       ---
       +++
       @@ -64,6 +64,11 @@
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
      @@ -57,6 +58,21 @@
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

  def testPatchAddFirstEncodingCombination_Success(self):
    first_encoding = _AddEncodingCombination(True, 'new_field', 'comp_cls_2',
                                             ['comp_2_1', 'comp_2_2'], [])

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_FIRST_ENCODING_COMBINATION), [first_encoding])

  def testPatchAddFirstEncodingCombination_ExistingEncodedFieldName(self):
    first_encoding = _AddEncodingCombination(
        True, 'comp_cls_23_field', 'comp_cls_2', ['comp_2_1', 'comp_2_2'], [])

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, first_encoding.Patch,
                        self._builder)

  def testPatchAddFollowingEncodingCombination_Success(self):
    # Add more combinations and check if the bit_length was enough.
    following_encodings = [
        _AddEncodingCombination(False, 'comp_cls_1_field', 'comp_cls_1',
                                ['comp_1_2'] * i, [0]) for i in range(2, 5)
    ]

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_FOLLOWING_ENCODING_COMBINATION), following_encodings)

  def testPatchAddFollowingEncodingCombination_NoSuchEncodedFieldName(self):
    following_encoding = _AddEncodingCombination(False, 'no_such_encoded_field',
                                                 'comp_cls_2',
                                                 ['comp_2_1', 'comp_2_2'], [0])

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
                                             pattern_idx=0))

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_NEW_IMAGE_ID_TO_EXISTING_PATTERN),
        [new_image_existing_pattern])


class NewImageIdToNewEncodingPatternTest(ChangeUnitTestBase):

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
    new_image_new_pattern = _NewImageIdToNewEncodingPattern(
        image_descs=[
            _ImageDesc(3, 'DVT'),
            _ImageDesc(4, 'PVT'),
        ], bit_mapping=[
            database.PatternField('mainboard_field', 10),
            database.PatternField('cpu_field', 5),
            database.PatternField('comp_cls_1_field', 2),
        ])

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_NEW_IMAGE_ID_TO_NEW_PATTERN),
        [new_image_new_pattern])

  def testPatchNewImageToNewEncodingPattern_ImageIDAlreadyExists(self):
    new_image_new_pattern = _NewImageIdToNewEncodingPattern(
        image_descs=[
            _ImageDesc(1, 'DVT'),
            _ImageDesc(4, 'PVT'),
        ], bit_mapping=[])

    with self._builder:
      self.assertRaises(_ApplyChangeUnitException, new_image_new_pattern.Patch,
                        self._builder)


class ReplaceRulesTest(ChangeUnitTestBase):

  _DIFF_REPLACE_RULES = textwrap.dedent('''\
      ---
      +++
      @@ -115,4 +115,10 @@
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
      @@ -8,11 +8,15 @@
       image_id:
         0: PROTO
         1: EVT
      +  3: DVT
      +  4: PVT
      +  5: PVT2

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
      @@ -54,9 +68,24 @@
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
      @@ -64,6 +93,11 @@
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
      @@ -92,12 +126,21 @@
                 hash": '0'
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
      +      new_comp#3:
      +        values:
      +          field: value3
      +        information:
      +          info: val3
         comp_cls_2:
           items:
             comp_2_1:
      @@ -115,4 +158,10 @@
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


if __name__ == '__main__':
  unittest.main()
