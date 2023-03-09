#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import unittest

from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils


_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')
_TEST_DATA_PREFIX = 'contents_analyzer_test'

DB_DRAM_GOOD_PATH = os.path.join(_TEST_DATA_PATH,
                                 'test_database_db_good_dram.yaml')
DB_DRAM_BAD_PATH = os.path.join(_TEST_DATA_PATH,
                                'test_database_db_bad_dram.yaml')
DB_COMP_BEFORE_PATH = os.path.join(_TEST_DATA_PATH,
                                   'test_database_db_comp_before.yaml')
DB_COMP_AFTER_GOOD_PATH = os.path.join(
    _TEST_DATA_PATH, 'test_database_db_comp_good_change.yaml')
DB_COMP_AFTER_INCOMPATIBLE_CHANGE_PATH = os.path.join(
    _TEST_DATA_PATH, 'test_database_db_comp_incompatible_change.yaml')
DB_COMP_MODIFY_FROM_FACTORY_BUNDLE_PATH = os.path.join(
    _TEST_DATA_PATH, 'test_database_db_comp_modify_from_factory_bundle.yaml')

_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus
_HWIDCompAnalysisResult = contents_analyzer.HWIDComponentAnalysisResult


class ContentsAnalyzerTest(unittest.TestCase):

  def test_ValidateIntegrity_Pass(self):
    db_contents = file_utils.ReadFile(DB_DRAM_GOOD_PATH)
    inst = contents_analyzer.ContentsAnalyzer(db_contents, None, None)
    report = inst.ValidateIntegrity()
    self.assertFalse(report.errors)

  def test_ValidateIntegrity_BadDramField(self):
    db_contents = file_utils.ReadFile(DB_DRAM_BAD_PATH)
    inst = contents_analyzer.ContentsAnalyzer(db_contents, None, None)
    report = inst.ValidateIntegrity()
    expected_error = contents_analyzer.Error(
        contents_analyzer.ErrorCode.CONTENTS_ERROR,
        "'dram_type_256mb_and_real_is_512mb' does not contain size property")
    self.assertIn(expected_error, report.errors)

  def test_ValidateChange_GoodCompNameChange(self):
    prev_db_contents = file_utils.ReadFile(DB_COMP_BEFORE_PATH)
    curr_db_contents = file_utils.ReadFile(DB_COMP_AFTER_GOOD_PATH)

    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    report = inst.ValidateChange()

    self.assertEqual(report.errors, [])

  def test_ValidateChange_InvalidForModifyBothComponentNameAndValues(self):
    prev_db_contents = file_utils.ReadFile(DB_COMP_BEFORE_PATH)
    curr_db_contents = file_utils.ReadFile(
        DB_COMP_AFTER_INCOMPATIBLE_CHANGE_PATH)

    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    report = inst.ValidateChange()

    expect_error = contents_analyzer.Error(
        contents_analyzer.ErrorCode.COMPATIBLE_ERROR,
        "Modifying both the component name ('display_panel_100_200' -> "
        "'display_panel_123_456') and values often causes compatibility "
        'issues. Is this change proposal mistakenly based on a legacy HWID '
        'bundle?')
    self.assertIn(expect_error, report.errors)

  def test_ValidateFirmwareComponents_ModifyFromFactoryBundle(self):
    prev_db_contents = file_utils.ReadFile(DB_COMP_BEFORE_PATH)
    curr_db_contents = file_utils.ReadFile(
        DB_COMP_MODIFY_FROM_FACTORY_BUNDLE_PATH)

    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    report = inst.ValidateFirmwareComponents()

    expect_error = contents_analyzer.Error(
        contents_analyzer.ErrorCode.CONTENTS_ERROR,
        "Modifying firmware component 'ro_ec_firmware_1' which is generated "
        'from the system. Is this change proposal mistakenly based on a legacy '
        'HWID bundle?')
    self.assertIn(expect_error, report.errors)

  def test_AnalyzeChange_PreconditionErrors(self):
    prev_db_contents = 'some invalid text for HWID DB.'
    curr_db_contents = 'some invalid text for HWID DB.'
    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    report = inst.AnalyzeChange(lambda s: s, True)
    self.assertTrue(report.precondition_errors)

  def test_AnalyzeChange_WithLines(self):

    def _HWIDDBHeaderPatcher(contents):
      # Remove everything before the checksum line.
      lines = contents.splitlines()
      for i, line in enumerate(lines):
        if line.startswith('checksum:'):
          return '\n'.join(lines[i + 1:])
      return contents

    prev_db_contents = self._ReadTestData('test_analyze_change_db_before.yaml')
    curr_db_contents = self._ReadTestData('test_analyze_change_db_after.yaml')
    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    report = inst.AnalyzeChange(_HWIDDBHeaderPatcher, True)

    test_name = 'test_analyze_change_with_lines'
    expected_report_txt = file_utils.ReadFile(
        os.path.join(_TEST_DATA_PATH,
                     f'{_TEST_DATA_PREFIX}-{test_name}-expected_report.json'))
    actual_report_txt = self._DumpRecordClass(report)
    self.assertEqual(actual_report_txt, expected_report_txt)

  def test_AnalyzeChange_WithoutLines(self):

    def _HWIDDBHeaderPatcher(contents):
      # Remove everything before the checksum line.
      lines = contents.splitlines()
      for i, line in enumerate(lines):
        if line.startswith('checksum:'):
          return '\n'.join(lines[i + 1:])
      return contents

    prev_db_contents = self._ReadTestData('test_analyze_change_db_before.yaml')
    curr_db_contents = self._ReadTestData('test_analyze_change_db_after.yaml')
    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    analysis = inst.AnalyzeChange(_HWIDDBHeaderPatcher, False)
    self.assertFalse(analysis.precondition_errors)
    self.assertFalse(analysis.lines)

  def test_AnalyzeChange_TouchedSections(self):
    prev_db_contents = self._ReadTestData('test_database_db.yaml')
    curr_db_contents = self._ReadTestData(
        'test_database_db_touched_sections.yaml')
    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None,
                                              prev_db_contents)
    analysis = inst.AnalyzeChange(None, False)

    self.assertEqual(
        contents_analyzer.TouchHWIDSections(
            image_id_change_status=(
                contents_analyzer.HWIDSectionTouchCase.TOUCHED),
            pattern_change_status=(
                contents_analyzer.HWIDSectionTouchCase.TOUCHED),
            encoded_fields_change_status={
                'field1': contents_analyzer.HWIDSectionTouchCase.TOUCHED,
                'field2': contents_analyzer.HWIDSectionTouchCase.UNTOUCHED,
                'field3': contents_analyzer.HWIDSectionTouchCase.UNTOUCHED,
                'field4': contents_analyzer.HWIDSectionTouchCase.UNTOUCHED,
            },
            components_change_status=(
                contents_analyzer.HWIDSectionTouchCase.TOUCHED),
            rules_change_status=(
                contents_analyzer.HWIDSectionTouchCase.TOUCHED),
            framework_version_change_status=(
                contents_analyzer.HWIDSectionTouchCase.TOUCHED),
        ), analysis.touched_sections)

  def test_AnalyzeChange_WithSkipAVLCheckChecker(self):
    skippable_comp = database.ComponentInfo({'xxx': 'yyy'}, 'supported')

    def Checker(category: str, comp: database.ComponentInfo) -> bool:
      return category == 'cls3' and comp == skippable_comp

    curr_db_contents = self._ReadTestData('test_database_db.yaml')
    inst = contents_analyzer.ContentsAnalyzer(curr_db_contents, None, None)

    analysis = inst.AnalyzeChange(None, False, Checker)

    skippable_comps = [
        comp_analysis for comp_analysis in analysis.hwid_components.values()
        if comp_analysis.skip_avl_check
    ]
    self.assertCountEqual([
        _HWIDCompAnalysisResult(
            comp_cls='cls3', comp_name='comp4', support_status='supported',
            is_newly_added=True, comp_name_info=None, seq_no=1,
            comp_name_with_correct_seq_no=None, null_values=False,
            diff_prev=None, link_avl=False,
            probe_value_alignment_status=_PVAlignmentStatus.NO_PROBE_INFO,
            skip_avl_check=True)
    ], skippable_comps)

  def _ReadTestData(self, test_data_name: str) -> str:
    return file_utils.ReadFile(os.path.join(_TEST_DATA_PATH, test_data_name))

  def _DumpRecordClass(self, inst) -> str:
    serializer = json_utils.Serializer(
        [json_utils.ConvertEnumToStr, json_utils.ConvertNamedTupleToDict])
    return json_utils.DumpStr(
        serializer.Serialize(inst), pretty=True, sort_keys=False)


if __name__ == '__main__':
  unittest.main()
