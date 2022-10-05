#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import re
import textwrap
from typing import Iterable, Mapping, NamedTuple, Optional, Sequence
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
_ComponentNameInfo = contents_analyzer.ComponentNameInfo
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
_ChangeUnitManager = change_unit_utils.ChangeUnitManager
_ApprovalStatus = change_unit_utils.ApprovalStatus
_ChangeSplitResult = change_unit_utils.ChangeSplitResult

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


def _BuildHWIDComponentAnalysisResultWithDefaults(
    comp_cls: str, comp_name: str, seq_no: int,
    comp_info: database.ComponentInfo, is_newly_added: bool = False,
    comp_name_info: Optional[_ComponentNameInfo] = None,
    comp_name_with_correct_seq_no: Optional[str] = None,
    probe_value_alignment_status: _PVAlignmentStatus = (
        _PVAlignmentStatus.NO_PROBE_INFO),
    diff_prev: Optional[_DiffStatus] = None):

  null_values = comp_info.values is None
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
          prev_probe_value_alignment_status=probe_value_alignment_status)
  return _HWIDComponentAnalysisResult(
      comp_cls=comp_cls, comp_name=comp_name, seq_no=seq_no,
      support_status=support_status, is_newly_added=is_newly_added,
      link_avl=bool(comp_name_info), comp_name_info=comp_name_info,
      comp_name_with_correct_seq_no=comp_name_with_correct_seq_no,
      null_values=null_values,
      probe_value_alignment_status=probe_value_alignment_status,
      diff_prev=diff_prev)


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
      @@ -98,6 +98,12 @@
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
                    _PVAlignmentStatus.NO_PROBE_INFO))), comp_info.values,
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
                    _PVAlignmentStatus.NO_PROBE_INFO))), comp_info.values,
        comp_info.information, comp_info.comp_hash)

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
        ], contains_last=True)

    self._AssertApplyingPatchesEqualsData(
        self._LoadDBContentWithDiffPatched(
            self._DIFF_ADD_NEW_IMAGE_ID_TO_NEW_PATTERN),
        [new_image_new_pattern])

  def testPatchNewImageToNewEncodingPattern_ImageIDAlreadyExists(self):
    new_image_new_pattern = _NewImageIdToNewEncodingPattern(
        image_descs=[
            _ImageDesc(1, 'DVT'),
            _ImageDesc(4, 'PVT'),
        ], bit_mapping=[], contains_last=True)

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
      +      new_comp:
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
            prev_probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO))
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
        @@ -25,6 +25,7 @@
           - ro_main_firmware_field: 1
           - comp_cls_1_field: 2
           - comp_cls_23_field: 2
        +  - new_comp_cls_1_field: 1

         encoded_fields:
           chassis_field:
        @@ -56,7 +57,7 @@
             0:
               comp_cls_1: comp_1_1
             1:
        -      comp_cls_1: comp_1_2
        +      comp_cls_1: comp_1_3
           comp_cls_23_field:
             0:
               comp_cls_2: comp_2_1
        @@ -64,6 +65,15 @@
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
        @@ -95,9 +105,13 @@
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
               1: EVT
            +  2: NEW_PHASE
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
            @@ -54,7 +77,7 @@
                   storage: []
               comp_cls_1_field:
                 0:
            -      comp_cls_1: comp_1_1
            +      comp_cls_1: comp_1_1_renamed
                 1:
                   comp_cls_1: comp_1_2
               comp_cls_23_field:
            @@ -64,6 +87,17 @@
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
            @@ -92,12 +126,16 @@
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
                'NewImageIdToNewEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)'
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
            'NewImageIdToExistingEncodingPattern:NEW_PHASE(2)': {
                # Change units containing the last image id depends on other
                # image id additions.
                'NewImageIdToNewEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)'
            },
            # Not depended by other change units.
            'NewImageIdToNewEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)':
                set(),
            'NewImageIdToNewEncodingPattern:PHASE_NO_NEW_PATTERN_1(3)': {
                # change units containing the last image id depend on other
                # image id additions.
                'NewImageIdToNewEncodingPattern:PHASE_NEW_PATTERN_1(5)(last)'
            },
        },
        graph)

  def testInternalStateNotChanged(self):
    new_encoded_field_db_content = _ApplyUnifiedDiff(
        self._base_db_content,
        textwrap.dedent('''\
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
            @@ -64,6 +64,9 @@
                 1:
                   comp_cls_2: comp_2_2
                   comp_cls_3: comp_3_2
            +  new_field:
            +    0:
            +      comp_cls_1: new_comp

             components:
               mainboard:
            @@ -98,6 +101,9 @@
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
                @@ -98,6 +98,9 @@
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


if __name__ == '__main__':
  unittest.main()
