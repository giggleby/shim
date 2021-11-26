# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os.path
import unittest

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers \
    import v3_self_service_helper as ss_helper
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.v3 import database
from cros.factory.utils import file_utils


_TESTDATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata')


class HWIDV3SelfServiceActionHelperTest(unittest.TestCase):

  def testGetDBEditableSection(self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    editable_section = helper_inst.GetDBEditableSection()

    # The full editable section is too huge, verify the first and the last 3
    # lines.
    lines = editable_section.splitlines()
    self.assertEqual(lines[:3] + lines[-3:], [
        'image_id:',
        '  0: EVT',
        '  1: DVT',
        "      ComponentEq('battery', 'battery_medium') and",
        "      ComponentEq('keyboard', 'GB') and",
        "      ComponentEq('storage', ['HDD', '500G'])",
    ])

  def testReviewDraftDBEditableSection_FPChangesForDifferentSource(self):
    helper_inst1 = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst2 = self._LoadSSHelper('v3-golden-after-good.yaml')

    change_info1 = helper_inst1.ReviewDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True)
    change_info2 = helper_inst2.ReviewDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True)

    self.assertNotEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testReviewDraftDBEditableSection_FPChangesForDifferentDest(self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    change_info1 = helper_inst.ReviewDraftDBEditableSection(
        'editable section 1', derive_fingerprint_only=True)
    change_info2 = helper_inst.ReviewDraftDBEditableSection(
        'editable section 2', derive_fingerprint_only=True)

    self.assertNotEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testReviewDraftDBEditableSection_FPNotChangeIfSourceAndDestAreNotChanged(
      self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    change_info1 = helper_inst.ReviewDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True)
    change_info2 = helper_inst.ReviewDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True)

    self.assertEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testReviewDraftDBEditableSection_WithValidationError(self):
    helper_inst = self._LoadSSHelper('v3-golden-before.yaml')

    change_info = helper_inst.ReviewDraftDBEditableSection('not a valid data')

    self.assertFalse(change_info.is_change_valid)
    self.assertEqual(change_info.invalid_reasons[0].code,
                     hwid_action.DBValidationErrorCode.SCHEMA_ERROR)

  def testReviewDraftDBEditableSection_ValidationPassed(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    preproc_data_after, helper_inst_after = self._LoadPreprocDataAndSSHelper(
        'v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    change_info = helper_inst_before.ReviewDraftDBEditableSection(
        editable_section)

    self.assertTrue(change_info.is_change_valid)
    self.assertEqual(list(change_info.new_hwid_comps), ['dram'])
    self.assertCountEqual(change_info.new_hwid_comps['dram'], [
        hwid_action.DBNameChangedComponentInfo(comp_name='dram_type_4g_0',
                                               cid=0, qid=0, status='supported',
                                               has_cid_qid=False),
        hwid_action.DBNameChangedComponentInfo(
            comp_name='dram_allow_no_size_info_in_name', cid=0, qid=0,
            status='supported', has_cid_qid=False)
    ])
    db_after_change = database.Database.LoadData(
        change_info.new_hwid_db_contents,
        expected_checksum=database.Database.ChecksumForText(
            change_info.new_hwid_db_contents))
    self.assertEqual(db_after_change, preproc_data_after.database)

  def testAnalyzeDraftDbEditableSection(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDraftDBEditableSection(
        editable_section)

    self.assertEqual(analysis_report.precondition_errors, [])
    self.assertGreater(len(analysis_report.lines), 0)

  def testAnalyzeDraftDbEditableSection_SyntaxError(self):
    helper_inst = self._LoadSSHelper('v3-golden-before.yaml')

    analysis_report = helper_inst.AnalyzeDraftDBEditableSection(
        'invalid hwid db contents')

    self.assertGreater(len(analysis_report.precondition_errors), 0)

  def _LoadPreprocDataAndSSHelper(self, testdata_name):
    preproc_data = hwid_preproc_data.HWIDV3PreprocData(
        'CHROMEBOOK',
        file_utils.ReadFile(os.path.join(_TESTDATA_PATH, testdata_name)))
    helper_inst = ss_helper.HWIDV3SelfServiceActionHelper(preproc_data)
    return preproc_data, helper_inst

  def _LoadSSHelper(self, testdata_name):
    unused_preproc_data, action = self._LoadPreprocDataAndSSHelper(
        testdata_name)
    return action


if __name__ == '__main__':
  unittest.main()
