# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import os.path
import tempfile
import typing
import unittest

from google.protobuf import text_format

from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine import probe_tool_utils
from cros.factory.probe_info_service.app_engine.probe_tools import analyzers
from cros.factory.probe_info_service.app_engine.probe_tools import client_payload_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import stubby_handler
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import unittest_utils
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import process_utils


def _LoadProbeInfoAndCompName(testdata_name):
  comp_probe_info = unittest_utils.LoadComponentProbeInfo(testdata_name)
  comp_name = stubby_handler.GetProbeDataSourceComponentName(
      comp_probe_info.component_identity)
  return comp_probe_info.probe_info, comp_name


def _LoadProbeInfoAndCompNameFromPayload(proto_payload):
  comp_probe_info = unittest_utils.LoadComponentProbeInfoPayload(proto_payload)
  comp_name = stubby_handler.GetProbeDataSourceComponentName(
      comp_probe_info.component_identity)
  return comp_probe_info.probe_info, comp_name


_FAKE_RUNTIME_PROBE_PATH = os.path.join(unittest_utils.TESTDATA_DIR,
                                        'fake_runtime_probe')
_FAKE_LEGACY_RUNTIME_PROBE_PATH = os.path.join(
    unittest_utils.TESTDATA_DIR, 'fake_runtime_probe_with_legacy_args')


# TODO(yhong): Split probe statement converter specific test cases into
# `./probe_tools/probe_statement_converters_unittest.py`.  Also, for test cases
#  of general `.probe_tools.analyzers.ProbeInfoAnalyzer` logic, move them to
# `./probe_tools/analyzers_unittest.py`.
class ProbeInfoAnalyzerTest(unittest.TestCase):

  def setUp(self):
    self._pi_analyzer = probe_tool_utils.CreateProbeInfoAnalyzer()

  def testGetProbeSchema(self):
    resp = self._pi_analyzer.GetProbeSchema()
    self.assertCountEqual([f.name for f in resp.probe_function_definitions], [
        'audio_codec.audio_codec',
        'battery.generic_battery',
        'camera.mipi_camera',
        'camera.usb_camera',
        'display_panel.edid',
        'storage.mmc_storage',
        'storage.nvme_storage',
        'storage.ufs_storage',
        'raw_probe_statement',
        'cpu.generic_cpu',
    ])

  def testValidateProbeInfo_InvalidProbeFunction(self):
    probe_info = probe_info_analytics.ProbeInfo(probe_function_name='no_such_f')
    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, True)
    self.assertEqual(resp.result_type, resp.INCOMPATIBLE_ERROR)

  def testValidateProbeInfo_UnknownProbeParameter(self):
    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('1-valid')
    probe_info.probe_parameters.add(name='no_such_param')

    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, True)
    self.assertEqual(resp.result_type, resp.INCOMPATIBLE_ERROR)

  def testValidateProbeInfo_ProbeParameterBadType(self):
    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('1-valid')
    for probe_param in probe_info.probe_parameters:
      if probe_param.name == 'mmc_manfid':
        probe_param.string_value = ''
        probe_param.int_value = 123

    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, True)
    self.assertEqual(resp.result_type, resp.INCOMPATIBLE_ERROR)

  def testValidateProbeInfo_MissingProbeParameter(self):
    # Missing probe parameters is a kind of compatible error unless
    # `allow_missing_parameters` is `True`.
    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('1-valid')
    for probe_param in probe_info.probe_parameters:
      if probe_param.name == 'mmc_manfid':
        probe_info.probe_parameters.remove(probe_param)
        break

    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, False)
    self.assertEqual(resp.result_type, resp.INCOMPATIBLE_ERROR)

    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, True)
    self.assertEqual(resp.result_type, resp.PASSED)

  def testValidateProbeInfo_ParameterFormatError(self):
    probe_info, unused_comp_name = _LoadProbeInfoAndCompName(
        '1-param_value_error')
    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, False)
    self.assertEqual(
        resp, unittest_utils.LoadProbeInfoParsedResult('1-param_value_error'))

  def testValidateProbeInfo_Passed(self):
    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('1-valid')
    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, False)
    self.assertEqual(resp.result_type, resp.PASSED)

    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('2-valid')
    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, False)
    self.assertEqual(resp.result_type, resp.PASSED)

    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('3-valid')
    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, False)
    self.assertEqual(resp.result_type, resp.PASSED)

  def testValidateProbeInfo_PassedWithDuplicatedParam(self):
    probe_info, unused_comp_name = _LoadProbeInfoAndCompName('1-valid')
    probe_info.probe_parameters.add(name='mmc_manfid', string_value='0x03')

    resp = self._pi_analyzer.ValidateProbeInfo(probe_info, True)
    self.assertEqual(resp.result_type, resp.PASSED)

  def testCreateProbeDataSource(self):
    # TODO(yhong): We should check if the analyzer can tell if the probe
    #     info has changed by the actual use cases (e.g.
    #     `AnalyzeQualProbeTestResultPayload()` reports `LEGACY`) instead of
    #     directly checks the internal data structure.
    # pylint: disable=protected-access
    s1 = typing.cast(analyzers._ProbeDataSourceImpl,
                     self._LoadProbeDataSource('1-valid', comp_name='aaa'))
    s2 = typing.cast(analyzers._ProbeDataSourceImpl,
                     self._LoadProbeDataSource('2-valid', comp_name='aaa'))
    s3 = typing.cast(analyzers._ProbeDataSourceImpl,
                     self._LoadProbeDataSource('1-valid', comp_name='bbb'))
    # pylint: enable=protected-access
    self.assertNotEqual(s1.fingerprint, s2.fingerprint)
    self.assertEqual(s1.fingerprint, s3.fingerprint)

  def testDumpProbeDataSource(self):
    s = self._LoadProbeDataSource('1-valid')
    ps = self._pi_analyzer.DumpProbeDataSource(s).output
    self._AssertJSONStringEqual(
        ps, unittest_utils.LoadProbeStatementString('1-default'))

  def testGenerateRawProbeStatement_FromValidProbeInfo(self):
    s = self._LoadProbeDataSource('1-valid')
    ps = self._pi_analyzer.GenerateRawProbeStatement(s).output
    self._AssertJSONStringEqual(
        ps, unittest_utils.LoadProbeStatementString('1-default'))

  def testGenerateRawProbeStatement_WithMultipleProbeValues(self):
    probe_info, comp_name = _LoadProbeInfoAndCompNameFromPayload('''
        component_identity: {
          qual_id: 1
          readable_label: "PART_NO_1234"
          component_id: 100
        }
        probe_info: {
          probe_function_name: "storage.mmc_storage"
          probe_parameters: { name: "mmc_manfid" string_value: "0x0a" }
          probe_parameters: { name: "mmc_manfid" string_value: "0x0b" }
          probe_parameters: { name: "mmc_name" string_value: "0x414141414141" }
          probe_parameters: { name: "mmc_prv" string_value: "0x12" }
          probe_parameters: { name: "size_in_gb" int_value: 256 }
        }
    ''')
    probe_data_source = self._pi_analyzer.CreateProbeDataSource(
        comp_name, probe_info)

    probe_statement = self._pi_analyzer.GenerateRawProbeStatement(
        probe_data_source).output

    self._AssertJSONStringEqual(
        probe_statement, '''{
          "storage": {
            "AVL_1": {
              "eval": { "mmc_storage": {} },
              "expect": [
                { "mmc_manfid": [ true, "hex", "!eq 0x0A" ],
                  "mmc_name": [ true, "str", "!eq AAAAAA" ],
                  "mmc_prv": [ true, "hex", "!eq 0x12" ] },
                { "mmc_manfid": [ true, "hex", "!eq 0x0B" ],
                  "mmc_name": [ true, "str", "!eq AAAAAA" ],
                  "mmc_prv": [ true, "hex", "!eq 0x12" ] }
              ]
            }
          }
        }''')

  def testGenerateRawProbeStatement_WithInformationalParam(self):
    probe_info, comp_name = _LoadProbeInfoAndCompNameFromPayload('''
        component_identity: {
          qual_id: 1
          readable_label: "PART_NO_1234"
          component_id: 100
        }
        probe_info: {
          probe_function_name: "storage.mmc_storage"
          probe_parameters: { name: "mmc_manfid" string_value: "0x0a" }
          probe_parameters: { name: "mmc_name" string_value: "0x414141414141" }
          probe_parameters: { name: "mmc_prv" string_value: "0x12" }
          probe_parameters: { name: "size_in_gb" int_value: 256 }
        }
    ''')
    probe_data_source = self._pi_analyzer.CreateProbeDataSource(
        comp_name, probe_info)

    probe_statement = self._pi_analyzer.GenerateRawProbeStatement(
        probe_data_source).output

    self._AssertJSONStringEqual(
        probe_statement, '''{
          "storage": {
            "AVL_1": {
              "eval": { "mmc_storage": {} },
              "expect": {
                "mmc_manfid": [ true, "hex", "!eq 0x0A" ],
                "mmc_name": [ true, "str", "!eq AAAAAA" ],
                "mmc_prv": [ true, "hex", "!eq 0x12" ]
              }
            }
          }
        }''')

  def testGenerateRawProbeStatement_WithConcatParams(self):
    self.maxDiff = None
    probe_info, comp_name = _LoadProbeInfoAndCompNameFromPayload('''
        component_identity: {
          qual_id: 1
          readable_label: "PART_NO_1234"
          component_id: 100
        }
        probe_info: {
          probe_function_name: "camera.mipi_camera"
          probe_parameters: { name: "module_vid" string_value: "TC" }
          probe_parameters: { name: "module_pid" string_value: "0x1234" }
          probe_parameters: { name: "sensor_vid" string_value: "OV" }
          probe_parameters: { name: "sensor_pid" string_value: "0xabcd" }
        }
    ''')
    probe_data_source = self._pi_analyzer.CreateProbeDataSource(
        comp_name, probe_info)

    probe_statement = self._pi_analyzer.GenerateRawProbeStatement(
        probe_data_source).output

    self._AssertJSONStringEqual(
        probe_statement, '''{
          "camera": {
            "AVL_1": {
              "eval": { "mipi_camera": {} },
              "expect": {
                "mipi_module_id": [ true, "str", "!eq TC1234" ],
                "mipi_sensor_id": [ true, "str", "!eq OVabcd" ]
              }
            }
          }
        }''')

  def testGenerateRawProbeStatement_WithConcatParamsAndMultipleProbeValues(
      self):
    self.maxDiff = None
    probe_info, comp_name = _LoadProbeInfoAndCompNameFromPayload('''
        component_identity: {
          qual_id: 1
          readable_label: "PART_NO_1234"
          component_id: 100
        }
        probe_info: {
          probe_function_name: "camera.mipi_camera"
          probe_parameters: { name: "module_vid" string_value: "TC" }
          probe_parameters: { name: "module_vid" string_value: "ZZ" }
          probe_parameters: { name: "module_pid" string_value: "0x1234" }
          probe_parameters: { name: "sensor_vid" string_value: "OV" }
          probe_parameters: { name: "sensor_pid" string_value: "0xabcd" }
          probe_parameters: { name: "sensor_pid" string_value: "0x5678" }
        }
    ''')
    probe_data_source = self._pi_analyzer.CreateProbeDataSource(
        comp_name, probe_info)

    probe_statement = self._pi_analyzer.GenerateRawProbeStatement(
        probe_data_source).output

    self._AssertJSONStringEqual(
        probe_statement, '''{
          "camera": {
            "AVL_1": {
              "eval": { "mipi_camera": {} },
              "expect": [
                { "mipi_module_id": [ true, "str", "!eq TC1234" ],
                  "mipi_sensor_id": [ true, "str", "!eq OVabcd" ] },
                { "mipi_module_id": [ true, "str", "!eq TC1234" ],
                  "mipi_sensor_id": [ true, "str", "!eq OV5678" ] },
                { "mipi_module_id": [ true, "str", "!eq ZZ1234" ],
                  "mipi_sensor_id": [ true, "str", "!eq OVabcd" ] },
                { "mipi_module_id": [ true, "str", "!eq ZZ1234" ],
                  "mipi_sensor_id": [ true, "str", "!eq OV5678" ] }
              ]
            }
          }
        }''')

  def testGenerateRawProbeStatement_FromInvalidProbeInfo(self):
    s = self._LoadProbeDataSource('1-param_value_error')
    gen_result = self._pi_analyzer.GenerateRawProbeStatement(s)
    self.assertEqual(
        gen_result.probe_info_parsed_result,
        unittest_utils.LoadProbeInfoParsedResult('1-param_value_error'))
    self.assertIsNone(gen_result.output)

  def testGenerateProbeBundlePayload_ProbeParameterError(self):
    s = self._LoadProbeDataSource('1-param_value_error')
    resp = self._pi_analyzer.GenerateProbeBundlePayload([s])
    self.assertEqual(
        resp.probe_info_parsed_results[0],
        unittest_utils.LoadProbeInfoParsedResult('1-param_value_error'))

  def testGenerateProbeBundlePayload_IncompatibleError(self):
    probe_info, comp_name = _LoadProbeInfoAndCompName('1-valid')
    for probe_param in probe_info.probe_parameters:
      if probe_param.name == 'mmc_manfid':
        probe_info.probe_parameters.remove(probe_param)
        break
    resp = self._pi_analyzer.GenerateProbeBundlePayload(
        [self._pi_analyzer.CreateProbeDataSource(comp_name, probe_info)])
    self.assertEqual(resp.probe_info_parsed_results[0].result_type,
                     resp.probe_info_parsed_results[0].INCOMPATIBLE_ERROR)

  def testGenerateQualProbeTestBundlePayload_Passed(self):
    for fake_runtime_probe_script in (_FAKE_RUNTIME_PROBE_PATH,
                                      _FAKE_LEGACY_RUNTIME_PROBE_PATH):
      with self.subTest(fake_runtime_probe_script=fake_runtime_probe_script):
        info = unittest_utils.FakeProbedOutcomeInfo('1-succeed')

        resp = self._GenerateProbeBundlePayloadForFakeRuntimeProbe(info)
        self.assertEqual(resp.probe_info_parsed_results[0].result_type,
                         resp.probe_info_parsed_results[0].PASSED)

        # Invoke the probe bundle file with a fake `runtime_probe` to verify
        # if the probe bundle works.
        probed_outcome = self._InvokeProbeBundleWithFakeRuntimeProbe(
            resp.output.content, info.envs,
            fake_runtime_probe_path=fake_runtime_probe_script)
        pc_payload = self._ExtractProbePayloadFromFakeProbedOutcome(
            probed_outcome)
        self.assertEqual(probed_outcome, info.probed_outcome)
        self._AssertJSONStringEqual(pc_payload, info.probe_config_payload)

  def testGenerateQualProbeTestBundlePayload_MultipleSourcePassed(self):
    info = unittest_utils.FakeProbedOutcomeInfo('1_2-succeed')

    resp = self._GenerateProbeBundlePayloadForFakeRuntimeProbe(info)
    self.assertEqual(resp.probe_info_parsed_results[0].result_type,
                     resp.probe_info_parsed_results[0].PASSED)
    self.assertEqual(resp.probe_info_parsed_results[1].result_type,
                     resp.probe_info_parsed_results[1].PASSED)

    # Invoke the probe bundle file with a fake `runtime_probe` to verify if the
    # probe bundle works.
    probed_outcome = self._InvokeProbeBundleWithFakeRuntimeProbe(
        resp.output.content, info.envs)
    pc_payload = self._ExtractProbePayloadFromFakeProbedOutcome(probed_outcome)
    self.assertEqual(probed_outcome, info.probed_outcome)
    self._AssertJSONStringEqual(pc_payload, info.probe_config_payload)

  def testGenerateQualProbeTestBundlePayload_NoRuntimeProbe(self):
    info = unittest_utils.FakeProbedOutcomeInfo('1-bin_not_found')

    resp = self._GenerateProbeBundlePayloadForFakeRuntimeProbe(info)
    self.assertEqual(resp.probe_info_parsed_results[0].result_type,
                     resp.probe_info_parsed_results[0].PASSED)

    probed_outcome = (
        self._InvokeProbeBundleWithFakeRuntimeProbe(resp.output.content,
                                                    info.envs))
    self.assertTrue(bool(probed_outcome.rp_invocation_result.error_msg))
    self.assertEqual(probed_outcome, info.probed_outcome)

  def testAnalyzeQualProbeTestResult_PayloadFormatError(self):
    s = self._LoadProbeDataSource('1-valid')
    with self.assertRaises(probe_info_analytics.PayloadInvalidError):
      self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
          s, 'this_is_an_invalid_data')

  def testAnalyzeQualProbeTestResult_WrongComponentError(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome(
        '1-wrong_component')
    with self.assertRaises(probe_info_analytics.PayloadInvalidError):
      self._pi_analyzer.AnalyzeQualProbeTestResultPayload(s, raw_probed_outcome)

  def testAnalyzeQualProbeTestResult_Pass(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome('1-passed')
    resp = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
        s, raw_probed_outcome)
    self.assertEqual(resp.result_type, resp.PASSED)

  def testAnalyzeQualProbeTestResult_Legacy(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome('1-legacy')
    resp = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
        s, raw_probed_outcome)
    self.assertEqual(resp.result_type, resp.LEGACY)

  def testAnalyzeQualProbeTestResult_IntrivialError_BadReturnCode(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome(
        '1-bad_return_code')
    resp = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
        s, raw_probed_outcome)
    self.assertEqual(resp.result_type, resp.INTRIVIAL_ERROR)

  def testAnalyzeQualProbeTestResult_IntrivialError_InvalidProbeResult(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome(
        '1-invalid_probe_result')
    resp = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
        s, raw_probed_outcome)
    self.assertEqual(resp.result_type, resp.INTRIVIAL_ERROR)

  def testAnalyzeQualProbeTestResult_IntrivialError_ProbeResultMismatch(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome(
        '1-probe_result_not_match_metadata')
    resp = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
        s, raw_probed_outcome)
    self.assertEqual(resp.result_type, resp.INTRIVIAL_ERROR)

  def testAnalyzeQualProbeTestResult_IntrivialError_RuntimeProbeTimeout(self):
    s = self._LoadProbeDataSource('1-valid')
    raw_probed_outcome = unittest_utils.LoadRawProbedOutcome('1-timeout')
    resp = self._pi_analyzer.AnalyzeQualProbeTestResultPayload(
        s, raw_probed_outcome)
    self.assertEqual(resp.result_type, resp.INTRIVIAL_ERROR)

  def testAnalyzeDeviceProbeResultPayload_FormatError(self):
    s1 = self._LoadProbeDataSource('1-valid')
    s2 = self._LoadProbeDataSource('2-valid')
    raw_probed_outcome = 'this is not a valid probed outcome'
    with self.assertRaises(probe_info_analytics.PayloadInvalidError):
      self._pi_analyzer.AnalyzeDeviceProbeResultPayload([s1, s2],
                                                        raw_probed_outcome)

  def testAnalyzeDeviceProbeResultPayload_HasUnknownComponentError(self):
    s1 = self._LoadProbeDataSource('1-valid')
    s2 = self._LoadProbeDataSource('2-valid')
    with self.assertRaises(probe_info_analytics.PayloadInvalidError):
      self._pi_analyzer.AnalyzeDeviceProbeResultPayload(
          [s1, s2],
          unittest_utils.LoadRawProbedOutcome('1_2-has_unknown_component'))

  def testAnalyzeDeviceProbeResultPayload_IntrivialError(self):
    s1 = self._LoadProbeDataSource('1-valid')
    s2 = self._LoadProbeDataSource('2-valid')
    result = self._pi_analyzer.AnalyzeDeviceProbeResultPayload(
        [s1, s2],
        unittest_utils.LoadRawProbedOutcome('1_2-runtime_probe_crash'))
    self.assertIsNotNone(result.intrivial_error_msg)
    self.assertIsNone(result.probe_info_test_results)

  def testAnalyzeDeviceProbeResultPayload_Passed(self):
    s1 = self._LoadProbeDataSource('1-valid')
    s2 = self._LoadProbeDataSource('2-valid')
    s3 = self._LoadProbeDataSource('3-valid')
    s4 = self._LoadProbeDataSource('1-valid', comp_name='yet_another_component')
    result = self._pi_analyzer.AnalyzeDeviceProbeResultPayload(
        [s1, s2, s3, s4], unittest_utils.LoadRawProbedOutcome('1_2_3-valid'))
    self.assertIsNone(result.intrivial_error_msg)
    self.assertEqual([r.result_type for r in result.probe_info_test_results], [
        stubby_pb2.ProbeInfoTestResult.NOT_PROBED,
        stubby_pb2.ProbeInfoTestResult.PASSED,
        stubby_pb2.ProbeInfoTestResult.LEGACY,
        stubby_pb2.ProbeInfoTestResult.NOT_INCLUDED
    ])

  def _AssertJSONStringEqual(self, lhs, rhs):
    self.assertEqual(json_utils.LoadStr(lhs), json_utils.LoadStr(rhs))

  def _LoadProbeDataSource(self, testdata_name, comp_name=None):
    probe_info, default_comp_name = _LoadProbeInfoAndCompName(testdata_name)
    return self._pi_analyzer.CreateProbeDataSource(
        comp_name or default_comp_name, probe_info)

  def _GenerateProbeBundlePayloadForFakeRuntimeProbe(self,
                                                     fake_probe_outcome_info):
    probe_info_sources = []
    for testdata_name in fake_probe_outcome_info.component_testdata_names:
      probe_info_sources.append(self._LoadProbeDataSource(testdata_name))
    return self._pi_analyzer.GenerateProbeBundlePayload(probe_info_sources)

  def _InvokeProbeBundleWithFakeRuntimeProbe(
      self, probe_bundle_payload, envs,
      fake_runtime_probe_path=_FAKE_RUNTIME_PROBE_PATH,
      runtime_probe_bin_name='runtime_probe'):
    probe_bundle_path = file_utils.CreateTemporaryFile()
    os.chmod(probe_bundle_path, 0o755)
    file_utils.WriteFile(probe_bundle_path, probe_bundle_payload, encoding=None)

    unpacked_dir = tempfile.mkdtemp()
    with file_utils.TempDirectory() as fake_bin_path:
      file_utils.ForceSymlink(
          fake_runtime_probe_path,
          os.path.join(fake_bin_path, runtime_probe_bin_name))
      subproc_envs = dict(os.environ)
      subproc_envs['PATH'] = f'{fake_bin_path}:{subproc_envs["PATH"]}'
      # Override `subproc_envs` with the given `envs` after configuring `PATH`
      # so that test cases can simulate no runtime probe by assigning `PATH` by
      # an empty directory.
      subproc_envs.update(envs)
      raw_output = process_utils.CheckOutput([
          probe_bundle_path, '-d', unpacked_dir, '--', '--verbose', '--output',
          '-'
      ], env=subproc_envs, encoding=None)
    return text_format.Parse(raw_output, client_payload_pb2.ProbedOutcome())

  def _ExtractProbePayloadFromFakeProbedOutcome(self, probed_outcome):
    probe_payload = probed_outcome.rp_invocation_result.raw_stderr.decode(
        'utf-8')
    probed_outcome.rp_invocation_result.raw_stderr = b''
    return probe_payload


if __name__ == '__main__':
  unittest.main()
