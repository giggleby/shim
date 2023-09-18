#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shlex
import tempfile
from typing import Mapping, Sequence
import unittest

from google.protobuf import text_format

from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine.probe_tools import analyzers
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import process_utils


_ProbeInfo = probe_info_analytics.ProbeInfo
_ProbeInfoArtifact = probe_info_analytics.ProbeInfoArtifact
_ProbeInfoParsedResult = probe_info_analytics.ProbeInfoParsedResult
_ProbeParameter = probe_info_analytics.ProbeParameter
_ProbeParameterSuggestion = probe_info_analytics.ProbeParameterSuggestion
_ProbeParameterValueType = probe_info_analytics.ProbeParameterValueType
_ProbeFunctionDefinition = probe_info_analytics.ProbeFunctionDefinition
_ProbeInfoTestResult = probe_info_analytics.ProbeInfoTestResult


class _FakeMultiProbeInfoConverter(analyzers.IBidirectionalProbeInfoConverter):

  PARAM_NAMES = ('param1', 'param2')

  def GetName(self) -> str:
    return 'fake_multi_converter'

  def GenerateDefinition(self) -> _ProbeFunctionDefinition:
    ret = _ProbeFunctionDefinition(
        name=self.GetName(),
        description=('A fake converter that turns probe info into 2 '
                     'component probe statements.'))
    for param_name in self.PARAM_NAMES:
      ret.probe_parameter_definitions.add(
          name=param_name, value_type=_ProbeParameterValueType.STRING)
    return ret

  def _BuildIncompatibleProbeInfoArtifact(self,
                                          error_msg: str) -> _ProbeInfoArtifact:
    return _ProbeInfoArtifact(
        _ProbeInfoParsedResult(
            result_type=_ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
            general_error_msg=error_msg), None)

  def ParseProbeParams(
      self, probe_params: Sequence[_ProbeParameter], allow_missing_params: bool,
      comp_name_for_probe_statement=None
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    if len(set(p.name for p in probe_params)) != len(probe_params):
      return self._BuildIncompatibleProbeInfoArtifact(
          'Got repeated parameter values.')
    if any(p.name not in self.PARAM_NAMES for p in probe_params):
      return self._BuildIncompatibleProbeInfoArtifact(
          'Got unknown parameter(s).')
    if not all(p.WhichOneof('value') == 'string_value' for p in probe_params):
      return self._BuildIncompatibleProbeInfoArtifact(
          'Got non-string parameter(s).')
    if not allow_missing_params and len(probe_params) != len(self.PARAM_NAMES):
      return self._BuildIncompatibleProbeInfoArtifact(
          'Missing some parameters.')
    parsed_result = _ProbeInfoParsedResult(
        result_type=_ProbeInfoParsedResult.PASSED)
    if comp_name_for_probe_statement is None:
      return _ProbeInfoArtifact(parsed_result, None)
    comp_probe_statements = []
    probe_param_of_name = {p.name: p
                           for p in probe_params}
    for name in self.PARAM_NAMES:
      if name not in probe_param_of_name:
        continue
      probe_statement = {
          'eval': {
              'the_probe_function': {}
          },
          'expect': {
              name: [
                  True, 'str', f'!eq {probe_param_of_name[name].string_value}'
              ]
          }
      }
      comp_probe_statements.append(
          probe_config_types.ComponentProbeStatement(
              'the_category', f'{comp_name_for_probe_statement}-for_{name}',
              probe_statement))
    return _ProbeInfoArtifact(parsed_result, comp_probe_statements)


  def ParseProbeResult(
      self, probe_result: Mapping[str, Sequence[Mapping[str, str]]]
  ) -> Sequence[analyzers.ParsedProbeParameter]:
    category_probe_result = probe_result.get('the_category', [])
    parsed_results = []

    for probe_values in category_probe_result:
      res = [
          analyzers.ParsedProbeParameter(
              'the_category',
              _ProbeParameter(name=param_name,
                              string_value=probe_values[param_name]))
          for param_name in self.PARAM_NAMES
          if param_name in probe_values
      ]
      if len(res) == len(self.PARAM_NAMES):
        parsed_results.extend(res)

    return parsed_results

  def GetNormalizedProbeParams(
      self,
      probe_params: Sequence[_ProbeParameter]) -> Sequence[_ProbeParameter]:
    return probe_params


class ProbeInfoAnalyzerTest(unittest.TestCase):
  # Most test cases are still live in `../probe_tool_utils_unittest.py`.
  # However, developers should put newly test cases (especially for features
  # introduced after crrev/c/4607726) here.

  def _AssertJSONStringEqual(self, lhs: str, rhs: str):
    self.assertEqual(
        json_utils.DumpStr(json_utils.LoadStr(lhs), pretty=True),
        json_utils.DumpStr(json_utils.LoadStr(rhs), pretty=True))

  def testWithMultiProbeStatementProbeInfo_ThenCanDump(self):
    # Arrange.
    pi_analyzer = analyzers.ProbeInfoAnalyzer([_FakeMultiProbeInfoConverter()])
    pi = text_format.Parse(
        '''probe_function_name: "fake_multi_converter"
           probe_parameters { name: "param1" string_value: "value1" }
           probe_parameters { name: "param2" string_value: "value2" }''',
        _ProbeInfo())

    # Act.
    actual = pi_analyzer.DumpProbeDataSource(
        pi_analyzer.CreateProbeDataSource('comp_name', pi))

    # Assert.
    self.assertEqual(actual.probe_info_parsed_result.result_type,
                     _ProbeInfoParsedResult.PASSED)
    expect_probe_statement = '''
        { "the_category": {
            "comp_name-for_param1": {
              "eval": {"the_probe_function": {}},
              "expect": {"param1": [true, "str", "!eq value1"]}
            },
            "comp_name-for_param2": {
              "eval": {"the_probe_function": {}},
              "expect": {"param2": [true, "str", "!eq value2"]}
        } } }'''
    self._AssertJSONStringEqual(actual.output, expect_probe_statement)

  def testLoadProbeInfo_WithMultiProbeStatements_ThenCanLoad(self):
    # Arrange.
    pi_analyzer = analyzers.ProbeInfoAnalyzer([])
    probe_statement = '''
        { "the_category": {
            "part1": {"eval": {"the_probe_function1": {}}},
            "part2": {"eval": {"the_probe_function2": {}}}
        } }'''

    # Act.
    actual = pi_analyzer.LoadProbeInfo(probe_statement)

    # Assert, check if the loaded probe info is valid by verifying if it can
    # be dumped to the expected probe statement.
    generation_result = pi_analyzer.GenerateRawProbeStatement(
        pi_analyzer.CreateProbeDataSource('comp_name', actual))
    self.assertEqual(generation_result.probe_info_parsed_result.result_type,
                     _ProbeInfoParsedResult.PASSED)
    expect_probe_statement = '''
        { "the_category": {
            "comp_name-part1": {"eval": {"the_probe_function1": {}}},
            "comp_name-part2": {"eval": {"the_probe_function2": {}}}
        } }'''
    self._AssertJSONStringEqual(generation_result.output,
                                expect_probe_statement)

  def testWithMultiProbeStatementProbeInfo_ThenCanGenerateDummyProbeStatement(
      self):
    # Arrange.
    pi_analyzer = analyzers.ProbeInfoAnalyzer([_FakeMultiProbeInfoConverter()])
    pi = text_format.Parse(
        '''probe_function_name: "fake_multi_converter"
           probe_parameters { name: "param1" string_value: "value1" }
           probe_parameters { name: "param2" string_value: "value2" }''',
        _ProbeInfo())

    # Act, dump the probe info and load back.
    actual = pi_analyzer.GenerateDummyProbeStatement(
        pi_analyzer.CreateProbeDataSource('comp_name', pi))

    # Assert, by checking if the loaded probe info can generate the probe
    # statement.
    expect = '''
        { "<unknown_component_category>": {
            "comp_name": {
              "eval": {"unknown_probe_function": {}},
              "expect": {}
        } } }'''
    self._AssertJSONStringEqual(actual, expect)

  def testWithMultiProbeStatementProbeInfo_ThenGenerateRawProbeStatement(self):
    # Arrange.
    pi_analyzer = analyzers.ProbeInfoAnalyzer([_FakeMultiProbeInfoConverter()])
    pi = text_format.Parse(
        '''probe_function_name: "fake_multi_converter"
           probe_parameters { name: "param1" string_value: "value1" }
           probe_parameters { name: "param2" string_value: "value2" }''',
        _ProbeInfo())

    # Act, dump the probe info and load back.
    actual = pi_analyzer.GenerateRawProbeStatement(
        pi_analyzer.CreateProbeDataSource('comp_name', pi))

    # Assert.
    self.assertEqual(actual.probe_info_parsed_result.result_type,
                     _ProbeInfoParsedResult.PASSED)
    expect_probe_statement = '''
        { "the_category": {
            "comp_name-for_param1": {
              "eval": {"the_probe_function": {}},
              "expect": {"param1": [true, "str", "!eq value1"]}
            },
            "comp_name-for_param2": {
              "eval": {"the_probe_function": {}},
              "expect": {"param2": [true, "str", "!eq value2"]}
        } } }'''
    self._AssertJSONStringEqual(actual.output, expect_probe_statement)

  def _InvokeProbeBundleWithStubRuntimeProbe(
      self, probe_bundle_payload: bytes, runtime_probe_stdout: str = '',
      runtime_probe_stderr: str = '', runtime_probe_retcode: int = 0) -> bytes:
    probe_bundle_path = file_utils.CreateTemporaryFile()
    os.chmod(probe_bundle_path, 0o755)
    file_utils.WriteFile(probe_bundle_path, probe_bundle_payload, encoding=None)

    unpacked_dir = tempfile.mkdtemp()
    with file_utils.TempDirectory() as fake_bin_path:
      runtime_probe_path = os.path.join(fake_bin_path, 'runtime_probe')
      file_utils.WriteFile(
          runtime_probe_path, '\n'.join([
              '#!/usr/bin/env bash',
              'if [[ $1 == "--help" ]]; then',
              '  echo "--verbosity_level   blahblahblah..."',
              '  exit 1',
              'fi',
              f'echo -n {shlex.quote(runtime_probe_stdout)}',
              f'echo -n {shlex.quote(runtime_probe_stderr)} >&2',
              f'exit {runtime_probe_retcode}',
              '',
          ]))
      os.chmod(runtime_probe_path, 0o755)
      subproc_envs = dict(os.environ)
      subproc_envs['PATH'] = f'{fake_bin_path}:{subproc_envs["PATH"]}'
      return process_utils.CheckOutput([
          probe_bundle_path, '-d', unpacked_dir, '--', '--verbose', '--output',
          '-'
      ], env=subproc_envs, encoding=None)

  def testWithMultiProbeStatementProbeInfo_ThenCanTestByQualBundle(self):
    # Arrange.
    pi_analyzer = analyzers.ProbeInfoAnalyzer([_FakeMultiProbeInfoConverter()])
    pi = text_format.Parse(
        '''probe_function_name: "fake_multi_converter"
           probe_parameters { name: "param1" string_value: "value1" }
           probe_parameters { name: "param2" string_value: "value2" }''',
        _ProbeInfo())

    # Act, generate the probe bundle.
    pds = pi_analyzer.CreateProbeDataSource('comp_name', pi)
    actual = pi_analyzer.GenerateProbeBundlePayload([pds])

    # Assert, the bundle is generated.
    self.assertEqual(actual.probe_info_parsed_results[0].result_type,
                     _ProbeInfoParsedResult.PASSED)
    self.assertIsNotNone(actual.output)
    bundle_content = actual.output.content

    with self.subTest('Tested'):
      # Arrange, invoke the probe bundle.
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_stdout='''
              { "the_category": [ {"name": "comp_name-for_param1"},
                                  {"name": "comp_name-for_param2"} ] }''')

      result = pi_analyzer.AnalyzeQualProbeTestResultPayload(pds, bundle_output)

      self.assertEqual(
          result, _ProbeInfoTestResult(result_type=_ProbeInfoTestResult.PASSED))

    with self.subTest('IntrivialError'):
      # Arrange, invoke the probe bundle.
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_retcode=3)

      result = pi_analyzer.AnalyzeQualProbeTestResultPayload(pds, bundle_output)

      expected_result = _ProbeInfoTestResult(
          result_type=_ProbeInfoTestResult.INTRIVIAL_ERROR,
          intrivial_error_msg=(
              'The return code of runtime probe is non-zero: 3.'))
      self.assertEqual(result, expected_result)

    with self.subTest('PartiallyProbed'):
      # Arrange, invoke the probe bundle.
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_stdout='''
              { "the_category": [ {"name": "comp_name-for_param1"} ] }''')

      result = pi_analyzer.AnalyzeQualProbeTestResultPayload(pds, bundle_output)

      expected_result = _ProbeInfoTestResult(
          result_type=_ProbeInfoTestResult.INTRIVIAL_ERROR,
          intrivial_error_msg=(
              "Component(s) not found: ({'comp_name-for_param2'})."))
      self.assertEqual(result, expected_result)

    with self.subTest('ProbedResultsMismatched'):
      # Arrange, invoke the probe bundle.
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_stdout='''
              { "the_category": [ {
                  "name": "generic",
                  "values": {
                    "param1": "aaa",
                    "param2": "bbb"
              } } ] }''')

      result = pi_analyzer.AnalyzeQualProbeTestResultPayload(pds, bundle_output)

      expected_result = _ProbeInfoTestResult(
          result_type=_ProbeInfoTestResult.PROBE_PRAMETER_SUGGESTION,
          probe_parameter_suggestions=[
              _ProbeParameterSuggestion(
                  index=0,
                  hint=('expected: \"[\'value1\']\", probed 1 the_category '
                        'component(s) with value:\ncomponent 1: \"aaa\"')),
              _ProbeParameterSuggestion(
                  index=1,
                  hint=('expected: \"[\'value2\']\", probed 1 the_category '
                        'component(s) with value:\ncomponent 1: \"bbb\"'))
          ])
      self.assertEqual(result, expected_result)

    with self.subTest('ProbeInfoBecomeOutOfDate'):
      # Arrange, invoke the probe bundle.
      updated_pi = text_format.Parse(
          '''probe_function_name: "fake_multi_converter"
             probe_parameters { name: "param1" string_value: "value100" }
             probe_parameters { name: "param2" string_value: "value200" }''',
          _ProbeInfo())
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_stdout='''
              { "the_category": {
                  "comp_name-for_param1": [{"param1": "value1"}],
                  "comp_name-for_param2": [{"param1": "value2"}]
              } }''')

      result = pi_analyzer.AnalyzeQualProbeTestResultPayload(
          pi_analyzer.CreateProbeDataSource('comp_name', updated_pi),
          bundle_output)

      self.assertEqual(
          result, _ProbeInfoTestResult(result_type=_ProbeInfoTestResult.LEGACY))

  def testWithMultiProbeStatementProbeInfo_ThenCanTestByDeviceBundle(self):
    # Arrange.
    pi_analyzer = analyzers.ProbeInfoAnalyzer([_FakeMultiProbeInfoConverter()])
    pi = text_format.Parse(
        '''probe_function_name: "fake_multi_converter"
           probe_parameters { name: "param1" string_value: "value1" }
           probe_parameters { name: "param2" string_value: "value2" }''',
        _ProbeInfo())

    # Act, generate the device probe bundle.
    pds = pi_analyzer.CreateProbeDataSource('comp_name', pi)
    actual = pi_analyzer.GenerateProbeBundlePayload([pds])

    # Assert, the bundle is generated.
    self.assertEqual(actual.probe_info_parsed_results[0].result_type,
                     _ProbeInfoParsedResult.PASSED)
    self.assertIsNotNone(actual.output)
    bundle_content = actual.output.content

    with self.subTest('Probed'):
      # Arrange, invoke the probe bundle.
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_stdout='''
              { "the_category": [ {"name": "comp_name-for_param1"},
                                  {"name": "comp_name-for_param2"} ] }''')

      result = pi_analyzer.AnalyzeDeviceProbeResultPayload([pds], bundle_output)

      self.assertEqual(
          result.probe_info_test_results,
          [_ProbeInfoTestResult(result_type=_ProbeInfoTestResult.PASSED)])

    with self.subTest('NotProbed'):
      # Arrange, invoke the probe bundle.
      bundle_output = self._InvokeProbeBundleWithStubRuntimeProbe(
          bundle_content, runtime_probe_stdout='''
              { "the_category": [ {"name": "comp_name-for_param1"} ] }''')

      result = pi_analyzer.AnalyzeDeviceProbeResultPayload([pds], bundle_output)

      self.assertEqual(
          result.probe_info_test_results,
          [_ProbeInfoTestResult(result_type=_ProbeInfoTestResult.NOT_PROBED)])


if __name__ == '__main__':
  unittest.main()
