# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import os.path
import re
import tempfile
from typing import Optional
import unittest

from google.protobuf import text_format

from cros.factory.hwid.service.appengine.data import avl_metadata_util
from cros.factory.hwid.service.appengine.data import config_data
from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine import features
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers import v3_self_service_helper as ss_helper
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import feature_compliance
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


_TESTDATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'testdata')
_PVAlignmentStatus = hwid_action.DBHWIDPVAlignmentStatus
_HWIDCompAnalysisResult = hwid_action.DBHWIDComponentAnalysisResult
_DiffStatus = hwid_action.DBHWIDComponentDiffStatus


class _TestAVLAttrs(converter.AVLAttrs):
  MODEL = 'pi_model'
  VENDOR = 'pi_vendor'
  SECTORS = 'pi_sectors'
  NAME = 'pi_name'
  MANFID = 'pi_manfid'


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
        "           ComponentEq('battery', 'battery_medium') and",
        "           ComponentEq('keyboard', 'GB') and",
        "           ComponentEq('storage', ['HDD', '500G']))",
    ])

  def testAnalyzeDBEditableSection_FPChangesForDifferentSource(self):
    helper_inst1 = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst2 = self._LoadSSHelper('v3-golden-after-good.yaml')

    change_info1 = helper_inst1.AnalyzeDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)
    change_info2 = helper_inst2.AnalyzeDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)

    self.assertNotEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testAnalyzeDBEditableSection_FPChangesForDifferentDest(self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    change_info1 = helper_inst.AnalyzeDBEditableSection(
        'editable section 1', derive_fingerprint_only=True,
        require_hwid_db_lines=False)
    change_info2 = helper_inst.AnalyzeDBEditableSection(
        'editable section 2', derive_fingerprint_only=True,
        require_hwid_db_lines=False)

    self.assertNotEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testAnalyzeDBEditableSection_FPNotChangeIfSourceAndDestAreNotChanged(
      self):
    helper_inst = self._LoadSSHelper('v3-golden.yaml')

    change_info1 = helper_inst.AnalyzeDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)
    change_info2 = helper_inst.AnalyzeDBEditableSection(
        'the same editable section', derive_fingerprint_only=True,
        require_hwid_db_lines=False)

    self.assertEqual(change_info1.fingerprint, change_info2.fingerprint)

  def testAnalyzeDBEditableSection(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDBEditableSection(
        editable_section, False, True)

    self.assertEqual(analysis_report.precondition_errors, [])
    self.assertEqual(analysis_report.validation_errors, [])
    self.assertGreater(len(analysis_report.lines), 0)

  def testAnalyzeDBEditableSection_AnalyzeCurrentDB(self):
    helper_inst = self._LoadSSHelper('v3-golden-before.yaml')

    analysis_report = helper_inst.AnalyzeDBEditableSection(
        draft_db_editable_section=None, derive_fingerprint_only=False,
        require_hwid_db_lines=True)

    self.assertEqual(analysis_report.precondition_errors, [])
    self.assertEqual(analysis_report.validation_errors, [])
    self.assertGreater(len(analysis_report.lines), 0)
    self.assertTrue(analysis_report.noop_for_external_db)

  def testAnalyzeDBEditableSection_FingerprintOnly(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDBEditableSection(
        editable_section, True, False)

    self.assertEqual(analysis_report.precondition_errors, [])
    self.assertEqual(analysis_report.validation_errors, [])
    self.assertEqual(len(analysis_report.lines), 0)
    self.assertEqual(analysis_report.fingerprint,
                     '22e990e315e68acd94537c5aa85eeaf2f99044bc')

  def testAnalyzeDBEditableSection_SyntaxError(self):
    helper_inst = self._LoadSSHelper('v3-golden-before.yaml')

    analysis_report = helper_inst.AnalyzeDBEditableSection(
        'invalid hwid db contents', False, True)

    self.assertEqual(analysis_report.validation_errors[0].code,
                     hwid_action.DBValidationErrorCode.SCHEMA_ERROR)

  def testAnalyzeDBEditableSection_SchemaError(self):
    helper_inst = self._LoadSSHelper('v3-golden-before.yaml')
    schema_error_content = file_utils.ReadFile(
        os.path.join(_TESTDATA_PATH, 'v3-schema-error-editable-content.yaml'))

    analysis_report = helper_inst.AnalyzeDBEditableSection(
        schema_error_content, False, True)

    self.assertEqual(analysis_report.validation_errors[0].code,
                     hwid_action.DBValidationErrorCode.SCHEMA_ERROR)

  def testAnalyzeDBEditableSection_ChecksumError(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-good.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDBEditableSection(
        editable_section, False, True, hwid_bundle_checksum='invalid_checksum')

    self.assertEqual(analysis_report.precondition_errors[0].code,
                     hwid_action.DBValidationErrorCode.CHECKSUM_ERROR)

  def testAnalyzeDBEditableSection_AVLProbeInfo(self):
    helper_inst = self._LoadSSHelper('v3-golden-no-avl-tags.yaml')
    editable_section = helper_inst.GetDBEditableSection()
    collection = converter.ConverterCollection('storage')
    collection.AddConverter(
        converter.FieldNameConverter.FromFieldMap(
            'test-converter1', {
                _TestAVLAttrs.MODEL: converter.ConvertedValueSpec('model'),
                _TestAVLAttrs.VENDOR: converter.ConvertedValueSpec('vendor'),
                _TestAVLAttrs.SECTORS: converter.ConvertedValueSpec('sectors'),
            }))
    collection.AddConverter(
        converter.FieldNameConverter.FromFieldMap(
            'test-converter2', {
                _TestAVLAttrs.NAME:
                    converter.ConvertedValueSpec('mmc_name'),
                _TestAVLAttrs.MANFID:
                    converter.ConvertedValueSpec(
                        'mmc_manfid',
                        converter.MakeFixedWidthHexValueFactory(width=6)),
            }))
    avl_converter_manager = converter_utils.ConverterManager(
        {'storage': collection})
    avl_resource = self._LoadAVLResource('v3-golden-internal.prototxt')
    report = helper_inst.AnalyzeDBEditableSection(
        draft_db_editable_section=editable_section,
        derive_fingerprint_only=False, require_hwid_db_lines=False,
        internal=True, avl_converter_manager=avl_converter_manager,
        avl_resource=avl_resource)
    converted_db = database.Database.LoadData(
        report.new_hwid_db_contents_internal)

    preproc_data, unused_helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden-internal-tags.yaml')
    expected_db = database.Database.LoadData(preproc_data.raw_database_internal)

    self.assertEqual(expected_db, converted_db)

  def testAnalyzeDBEditableSection_NoopChange(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-internal-tags.yaml')
    helper_inst_after = self._LoadSSHelper('v3-golden-after-no-op.yaml')
    editable_section = helper_inst_after.GetDBEditableSection()

    analysis_report = helper_inst_before.AnalyzeDBEditableSection(
        editable_section, False, False)

    self.assertTrue(analysis_report.noop_for_external_db)

  def testAnalyzeDBEditableSection_NoSupressSupportStatus(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-before.yaml')
    editable_section = helper_inst_before.GetDBEditableSection()
    converter_manager = converter_utils.ConverterManager({})
    resource_msg = hwid_api_messages_pb2.HwidDbExternalResource()

    analysis_report = helper_inst_before.AnalyzeDBEditableSection(
        draft_db_editable_section=editable_section,
        derive_fingerprint_only=False, require_hwid_db_lines=False,
        internal=True, avl_converter_manager=converter_manager,
        avl_resource=resource_msg)

    self.assertIn('status: supported',
                  analysis_report.new_hwid_db_contents_external)
    self.assertIn('status: supported',
                  analysis_report.new_hwid_db_contents_internal)

  def testAnalyzeDBEditableSection_WithAVLMetadataManager(self):
    helper_inst_before = self._LoadSSHelper('v3-golden-audio-codec.yaml')
    editable_section = helper_inst_before.GetDBEditableSection()
    avl_metadata_manager = avl_metadata_util.AVLMetadataManager(
        ndbc_module.NDBConnector(),
        config_data.AVLMetadataSetting.CreateInstance(True, '', '', []))

    avl_metadata_manager.UpdateAudioCodecBlocklist(['skippable_kernel_names'])
    analysis_report = helper_inst_before.AnalyzeDBEditableSection(
        draft_db_editable_section=editable_section,
        derive_fingerprint_only=False, require_hwid_db_lines=False,
        internal=False, avl_metadata_manager=avl_metadata_manager)

    skippable_comps = [
        comp_analysis
        for comp_analysis in analysis_report.hwid_components.values()
        if comp_analysis.skip_avl_check
    ]
    self.assertCountEqual([
        _HWIDCompAnalysisResult(
            comp_cls='audio_codec',
            comp_name='avl_skipped_comp',
            support_status='supported',
            is_newly_added=False,
            comp_name_info=name_pattern_adapter.LegacyNameInfo(
                'avl_skipped_comp'),
            seq_no=5,
            comp_name_with_correct_seq_no=None,
            null_values=False,
            diff_prev=_DiffStatus(
                unchanged=True, name_changed=False,
                support_status_changed=False, values_changed=False,
                prev_comp_name='avl_skipped_comp',
                prev_support_status='supported',
                probe_value_alignment_status_changed=False,
                prev_probe_value_alignment_status=(
                    _PVAlignmentStatus.NO_PROBE_INFO), converter_changed=False,
                marked_untracked_changed=False),
            link_avl=False,
            probe_value_alignment_status=(_PVAlignmentStatus.NO_PROBE_INFO),
            skip_avl_check=True,
            marked_untracked=False,
        )
    ], skippable_comps)

  def testGetHWIDBundleResourceInfo_DifferentDBContentsHasDifferentFP(self):
    ss_helper1 = self._LoadSSHelper('v3-golden-before.yaml')
    ss_helper2 = self._LoadSSHelper('v3-golden-after-good.yaml')

    resource_info1 = ss_helper1.GetHWIDBundleResourceInfo(True)
    resource_info2 = ss_helper2.GetHWIDBundleResourceInfo(True)
    self.assertNotEqual(resource_info1.fingerprint, resource_info2.fingerprint)

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
        db_path = os.path.join(dest_dir, data.project)
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
        db_path = os.path.join(dest_dir, data.project)
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
        db_path = os.path.join(dest_dir, legacy_data.project)
        legacy_yaml = yaml.safe_load(file_utils.ReadFile(db_path))
        self.assertIn('board', legacy_yaml)
        self.assertNotIn('project', legacy_yaml)

    payload_tot = helper_inst_tot.BundleHWIDDB().bundle_contents

    with file_utils.UnopenedTemporaryFile() as bundle_path:
      os.chmod(bundle_path, 0o755)
      file_utils.WriteFile(bundle_path, payload_tot, encoding=None)
      with tempfile.TemporaryDirectory() as dest_dir:
        process_utils.CheckCall([bundle_path, dest_dir])
        db_path = os.path.join(dest_dir, tot_data.project)
        tot_yaml = yaml.safe_load(file_utils.ReadFile(db_path))
        self.assertNotIn('board', tot_yaml)
        self.assertIn('project', tot_yaml)

  def testBundleHWIDDB_ContainsFeatureRequirementSpecFile(self):
    feature_matcher_builder = (
        hwid_preproc_data.HWIDV3PreprocData.HWID_FEATURE_MATCHER_BUILDER)
    feature_matcher_source = (
        feature_matcher_builder.GenerateFeatureMatcherRawSource(
            feature_version=1, brand_allowed_feature_enablement_types={},
            hwid_requirement_candidates=[
                features.HWIDRequirement(
                    description='always_fulfill_requirement',
                    bit_string_prerequisites=[])
            ]))
    preproc_data, helper_inst = self._LoadPreprocDataAndSSHelper(
        'v3-golden.yaml', feature_matcher_source=feature_matcher_source)

    payload = helper_inst.BundleHWIDDB().bundle_contents

    with file_utils.UnopenedTemporaryFile() as bundle_path:
      os.chmod(bundle_path, 0o755)
      file_utils.WriteFile(bundle_path, payload, encoding=None)
      with tempfile.TemporaryDirectory() as dest_dir:
        process_utils.CheckCall([bundle_path, dest_dir])

        checker = feature_compliance.LoadChecker(dest_dir, preproc_data.project)

        self.assertIsNotNone(checker)

  def _LoadPreprocDataAndSSHelper(self, testdata_name, commit_id='COMMIT-ID',
                                  feature_matcher_source: Optional[str] = None):
    preproc_data = hwid_preproc_data.HWIDV3PreprocData(
        'CHROMEBOOK',
        file_utils.ReadFile(os.path.join(_TESTDATA_PATH, testdata_name)),
        file_utils.ReadFile(os.path.join(_TESTDATA_PATH, testdata_name)),
        commit_id, feature_matcher_source)
    helper_inst = ss_helper.HWIDV3SelfServiceActionHelper(preproc_data)
    return preproc_data, helper_inst

  def _LoadSSHelper(self, testdata_name):
    unused_preproc_data, action = self._LoadPreprocDataAndSSHelper(
        testdata_name)
    return action

  def _LoadAVLResource(self, resource_name):
    resource_content = file_utils.ReadFile(
        os.path.join(_TESTDATA_PATH, 'avl_resource', resource_name))
    resource_msg = hwid_api_messages_pb2.HwidDbExternalResource()
    text_format.Parse(resource_content, resource_msg)
    return resource_msg


if __name__ == '__main__':
  unittest.main()
