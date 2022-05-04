# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import os.path
import re
import tempfile
import unittest

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers import v3_self_service_helper as ss_helper
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils

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
        ("    ComponentEq('audio_codec', ['hdmi_1', 'codec_1']) and "
         "ComponentEq('cpu', 'cpu_4')"),
        ("    and ComponentEq('battery', 'battery_medium') and ComponentEq("
         "'keyboard', 'GB')"),
        "    and ComponentEq('storage', ['HDD', '500G'])",
    ])

  def testAnalyzeDraftDBEditableSection_FPChangesForDifferentSource(self):
    helper_inst1 = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst2 = self._LoadSSHelper('v3-golden-after-good.yaml')

    change_info1 = helper_inst1.AnalyzeDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)
    change_info2 = helper_inst2.AnalyzeDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)

    self.assertNotEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testAnalyzeDraftDBEditableSection_FPChangesForDifferentDest(self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    change_info1 = helper_inst.AnalyzeDraftDBEditableSection(
        'editable section 1', derive_fingerprint_only=True,
        require_hwid_db_lines=False)
    change_info2 = helper_inst.AnalyzeDraftDBEditableSection(
        'editable section 2', derive_fingerprint_only=True,
        require_hwid_db_lines=False)

    self.assertNotEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testAnalyzeDraftDBEditableSection_FPNotChangeIfSourceAndDestAreNotChanged(
      self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    change_info1 = helper_inst.AnalyzeDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)
    change_info2 = helper_inst.AnalyzeDraftDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)

    self.assertEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testAnalyzeDraftDbEditableSection(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDraftDBEditableSection(
        editable_section, False, True)

    self.assertEqual(analysis_report.precondition_errors, [])
    self.assertEqual(analysis_report.validation_errors, [])
    self.assertGreater(len(analysis_report.lines), 0)

  def testAnalyzeDraftDbEditableSection_FingerprintOnly(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDraftDBEditableSection(
        editable_section, True, False)

    self.assertEqual(analysis_report.precondition_errors, [])
    self.assertEqual(analysis_report.validation_errors, [])
    self.assertEqual(len(analysis_report.lines), 0)
    self.assertEqual(analysis_report.fingerprint,
                     '22e990e315e68acd94537c5aa85eeaf2f99044bc')

  def testAnalyzeDraftDbEditableSection_SyntaxError(self):
    helper_inst = self._LoadSSHelper('v3-golden-before.yaml')

    analysis_report = helper_inst.AnalyzeDraftDBEditableSection(
        'invalid hwid db contents', False, True)

    self.assertEqual(analysis_report.validation_errors[0].code,
                     hwid_action.DBValidationErrorCode.SCHEMA_ERROR)

  def testGetHWIDBundleResourceInfo_DifferentDBContentsHasDifferentFP(self):
    ss_helper1 = self._LoadSSHelper('v3-golden-before.yaml')
    ss_helper2 = self._LoadSSHelper('v3-golden-after-good.yaml')

    resource_info1 = ss_helper1.GetHWIDBundleResourceInfo(True)
    resource_info2 = ss_helper2.GetHWIDBundleResourceInfo(True)
    self.assertNotEqual(resource_info1.fingerprint, resource_info2.fingerprint)

  def testGetHWIDBundleResourceInfo_FilterLinkAvl(self):
    helper = self._LoadSSHelper('v3-golden-internal-tags.yaml')

    resource_info = helper.GetHWIDBundleResourceInfo(False)
    comp_name_info_cls = hwid_action.DBHWIDComponentNameInfo
    self.assertEqual(
        {
            'x@@@@component-storage-storage_0@@y@':
                hwid_action.DBHWIDComponentAnalysisResult(
                    comp_cls='storage', comp_name='storage_0',
                    support_status='supported', is_newly_added=True,
                    comp_name_info=comp_name_info_cls.from_comp(0), seq_no=1,
                    comp_name_with_correct_seq_no=None, null_values=False,
                    diff_prev=None, link_avl=True),
            'x@@@@component-storage-storage_2@@y@':
                hwid_action.DBHWIDComponentAnalysisResult(
                    comp_cls='storage', comp_name='storage_2',
                    support_status='supported', is_newly_added=True,
                    comp_name_info=comp_name_info_cls.from_comp(2), seq_no=3,
                    comp_name_with_correct_seq_no=None, null_values=False,
                    diff_prev=None, link_avl=True)
        }, resource_info.hwid_components)

  def testBundleHWIDDB_BundleInstallationWorks_NoInternalTags(self):
    data, helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden-no-internal-tags.yaml')

    payload = helper_inst.BundleHWIDDB().bundle_contents

    # Verify the created bundle payload by trying to install it.
    with file_utils.UnopenedTemporaryFile() as bundle_path:
      os.chmod(bundle_path, 0o755)
      file_utils.WriteFile(bundle_path, payload, encoding=None)
      with tempfile.TemporaryDirectory() as dest_dir:
        process_utils.CheckCall([bundle_path, dest_dir])
        db_path = os.path.join(dest_dir, data.project.upper())
        self.assertEqual(file_utils.ReadFile(db_path), data.raw_database)

  def testBundleHWIDDB_BundleInstallationWorks_InternalTags(self):
    data, helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden-internal-tags.yaml')
    trimmed_data, unused_helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden-no-internal-tags.yaml')

    payload = helper_inst.BundleHWIDDB().bundle_contents

    # Verify the created bundle payload by trying to install it.
    with file_utils.UnopenedTemporaryFile() as bundle_path:
      os.chmod(bundle_path, 0o755)
      file_utils.WriteFile(bundle_path, payload, encoding=None)
      with tempfile.TemporaryDirectory() as dest_dir:
        process_utils.CheckCall([bundle_path, dest_dir])
        db_path = os.path.join(dest_dir, data.project.upper())
        self.assertEqual(
            file_utils.ReadFile(db_path), trimmed_data.raw_database)

  # TODO(b/211957606) modify this test to ensure that the checksum information
  # is embedded in the generated bundle.
  def testBundleHWIDDB_ChecksumShownInInstallerScript(self):
    data, helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden-no-internal-tags.yaml')

    payload = helper_inst.BundleHWIDDB().bundle_contents

    checksum_pattern = re.compile(f'^checksum: {data.database.checksum}$',
                                  re.MULTILINE)
    self.assertIsNotNone(
        checksum_pattern.search(payload.decode('utf-8')),
        'checksum line was not displayed in payload.')

  def testBundleHWIDDB_CommitShownInInstallerScript(self):
    unused_data, helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden-no-internal-tags.yaml', 'SHOW_THIS_COMMIT')

    payload = helper_inst.BundleHWIDDB().bundle_contents

    self.assertIn('hwid_commit_id: SHOW_THIS_COMMIT', payload.decode('utf-8'))

  def testBundleHWIDDB_PreserveLegacyFormat(self):
    legacy_data, helper_inst_legacy = self._LoadPreprocDataAndSSHelper(
        'v3-golden.yaml')  # with legacy format
    tot_data, helper_inst_tot = self._LoadPreprocDataAndSSHelper(
        'v3-golden-internal-tags.yaml')  # with tot format

    payload_legacy = helper_inst_legacy.BundleHWIDDB().bundle_contents

    with file_utils.UnopenedTemporaryFile() as bundle_path:
      os.chmod(bundle_path, 0o755)
      file_utils.WriteFile(bundle_path, payload_legacy, encoding=None)
      with tempfile.TemporaryDirectory() as dest_dir:
        process_utils.CheckCall([bundle_path, dest_dir])
        db_path = os.path.join(dest_dir, legacy_data.project.upper())
        legacy_yaml = yaml.safe_load(file_utils.ReadFile(db_path))
        self.assertIn('board', legacy_yaml)
        self.assertNotIn('project', legacy_yaml)

    payload_tot = helper_inst_tot.BundleHWIDDB().bundle_contents

    with file_utils.UnopenedTemporaryFile() as bundle_path:
      os.chmod(bundle_path, 0o755)
      file_utils.WriteFile(bundle_path, payload_tot, encoding=None)
      with tempfile.TemporaryDirectory() as dest_dir:
        process_utils.CheckCall([bundle_path, dest_dir])
        db_path = os.path.join(dest_dir, tot_data.project.upper())
        tot_yaml = yaml.safe_load(file_utils.ReadFile(db_path))
        self.assertNotIn('board', tot_yaml)
        self.assertIn('project', tot_yaml)

  def _LoadPreprocDataAndSSHelper(self, testdata_name, commit_id='COMMIT-ID'):
    preproc_data = hwid_preproc_data.HWIDV3PreprocData(
        'CHROMEBOOK',
        file_utils.ReadFile(os.path.join(_TESTDATA_PATH, testdata_name)),
        file_utils.ReadFile(os.path.join(_TESTDATA_PATH, testdata_name)),
        commit_id)
    helper_inst = ss_helper.HWIDV3SelfServiceActionHelper(preproc_data)
    return preproc_data, helper_inst

  def _LoadSSHelper(self, testdata_name):
    unused_preproc_data, action = self._LoadPreprocDataAndSSHelper(
        testdata_name)
    return action


if __name__ == '__main__':
  unittest.main()
