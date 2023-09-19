# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import collections
import hashlib
import itertools
import os
import typing
from typing import Collection, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

from google.protobuf import text_format

from cros.factory.probe.runtime_probe import generic_probe_statement
from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.probe_info_service.app_engine import bundle_builder
from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine.probe_tools import client_payload_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import type_utils


_ProbeInfoArtifact = probe_info_analytics.ProbeInfoArtifact


class ParsedProbeParameter(NamedTuple):
  """Represents a probe parameter extracted from generic probe function."""
  component_category: str
  probe_parameter: probe_info_analytics.ProbeParameter


class IProbeInfoConverter(abc.ABC):
  """Represents a converter for probe info to probe statement(s)."""

  @abc.abstractmethod
  def GetName(self) -> str:
    """Gets the converter's unique name."""

  @abc.abstractmethod
  def GenerateDefinition(self) -> probe_info_analytics.ProbeFunctionDefinition:
    """Returns the schema of this converter."""

  @abc.abstractmethod
  def ParseProbeParams(
      self, probe_params: Sequence[probe_info_analytics.ProbeParameter],
      allow_missing_params: bool, comp_name_for_probe_statement=None
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """Walk through the given probe parameters.

    The method first validate each probe parameter.  Then if specified,
    it also generates the probe statement(s) from the given input.

    Args:
      probe_params: A list of `ProbeParameter` to validate.
      allow_missing_params: Whether missing required probe parameters is
          allowed.
      comp_name_for_probe_statement: If set, this method generates the probe
          statement with the specified component name when all probe parameters
          are valid.

    Returns:
      `.probe_info_parsed_result` contains the validation result.  If the
      validation passes and `comp_name_for_probe_statement` is specified,
      `.output` contains a non-empty list of component probe statements.
      The component names of all component probe statements will always start
      with `comp_name_for_probe_statement`.  The target component is considered
      probed if and only if all component probe statements detect something.
    """


class IBidirectionalProbeInfoConverter(IProbeInfoConverter):
  """A converter between probe info and probe statement(s) / probe result."""

  @abc.abstractmethod
  def ParseProbeResult(
      self, probe_result: Mapping[str, Sequence[Mapping[str, str]]]
  ) -> Sequence[ParsedProbeParameter]:
    """Walks through the given probe result.

    This method parses the given probe result, gets the probe values of the
    parameters defined by the converter, converts them to the same format as the
    source probe parameters, and returns them in the form of
    `ParsedProbeParameter`.

    Args:
      probe_result: A dictionary mapping component category to the probe values.

    Returns:
      A list of `ParsedProbeParameter` contains parsed probe parameters and
      their corresponding component categories.
    """

  @abc.abstractmethod
  def GetNormalizedProbeParams(
      self, probe_params: Sequence[probe_info_analytics.ProbeParameter]
  ) -> Sequence[probe_info_analytics.ProbeParameter]:
    """Returns the normalized `probe_params`.

    This method returns the normalized `probe_params` without modifying the
    input `probe_params`. This is used to preprocess the probe parameters
    before checking if the parameters are identical in the context of the probe
    tool.

    Args:
      probe_params: A list of `ProbeParameter` to be normalized.

    Returns:
      A list of normalized `ProbeParameter`.

    Raises:
      `ValueError` if the normalization fails.
    """

  def GenerateSuggestionMsg(
      self, expected_params: CollectedProbeParams,
      generic_probe_params: CollectedProbeParams,
      mismatch_param_names: Collection[str]) -> Sequence[str]:
    """Returns the converter-specific suggestion messages.

    Args:
      expected_params: A `CollectedProbeParams` whose keys are parameter names
          and whose values are the corresponding expected values.
      generic_probe_params: A `CollectedProbeParams` whose keys are parameter
          names and whose values are the corresponding generic probe values.
      mismatch_param_names: A set of names of the parameters that do not match
          between `expected_params` and `generic_probe_params`.

    Returns:
      A list of generated suggestion messages.
    """
    del expected_params, generic_probe_params, mismatch_param_names  # Unused.
    return []


_RESOURCE_PATH = os.path.join(
    os.path.realpath(os.path.dirname(__file__)), 'resources')

_ProbeSchema = probe_info_analytics.ProbeSchema
_ProbeFunctionDefinition = probe_info_analytics.ProbeFunctionDefinition
_ProbeParameterValueType = probe_info_analytics.ProbeParameterValueType
_ProbeInfo = probe_info_analytics.ProbeInfo
_ProbeInfoParsedResult = probe_info_analytics.ProbeInfoParsedResult
_ProbeInfoTestResult = probe_info_analytics.ProbeInfoTestResult
_DeviceProbeResultAnalyzedResult = (
    probe_info_analytics.DeviceProbeResultAnalyzedResult)
_MultiProbeInfoArtifact = probe_info_analytics.MultiProbeInfoArtifact
_NamedFile = probe_info_analytics.NamedFile
_IProbeDataSource = probe_info_analytics.IProbeDataSource
_PayloadInvalidError = probe_info_analytics.PayloadInvalidError
_ProbeParameterSuggestion = probe_info_analytics.ProbeParameterSuggestion
_ProbeParamValues = Sequence[Union[str, int]]

CollectedProbeParams = Mapping[str, _ProbeParamValues]


class _RawProbeStatementConverter(IProbeInfoConverter):
  """A converter that is simply a wrapper of raw probe statement string."""

  _CONVERTER_NAME = 'raw_probe_statement'
  _CONVERTER_DESCRIPTION = 'Probe by the given raw probe statement.'

  _PARAMETER_NAME = 'json_text'
  _PARAMETER_DESCRIPTION = 'The raw probe statement text value in JSON.'

  def GetName(self) -> str:
    """See base class."""
    return self._CONVERTER_NAME

  def GenerateDefinition(self) -> _ProbeFunctionDefinition:
    """See base class."""
    ret = _ProbeFunctionDefinition(name=self._CONVERTER_NAME,
                                   description=self._CONVERTER_DESCRIPTION)
    ret.parameter_definitions.add(name=self._PARAMETER_NAME,
                                  description=self._PARAMETER_DESCRIPTION,
                                  value_type=_ProbeParameterValueType.STRING)
    return ret

  def ParseProbeParams(
      self, probe_params: Sequence[probe_info_analytics.ProbeParameter],
      allow_missing_params: bool, comp_name_for_probe_statement=None
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    if (len(probe_params) != 1 or
        probe_params[0].name != self._PARAMETER_NAME or
        probe_params[0].WhichOneof('value') != 'string_value'):
      parsed_result = _ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
          general_error_msg='Got unexpected probe parameter(s).')
      return _ProbeInfoArtifact(parsed_result, None)

    try:
      loaded_component_probe_statements = (
          probe_config_types.ComponentProbeStatement.FromDictOfMultipleEntries(
              json_utils.LoadStr(probe_params[0].string_value)))
    except ValueError as ex:
      parsed_result = _ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.PROBE_PARAMETER_ERROR)
      parsed_result.probe_parameter_errors.add(
          index=0,
          hint=f'Unable to load the component probe statement in JSON: {ex}.')
      return _ProbeInfoArtifact(parsed_result, None)
    if not loaded_component_probe_statements:
      parsed_result = _ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.PROBE_PARAMETER_ERROR)
      parsed_result.probe_parameter_errors.add(
          index=0,
          hint='It must contain at least one component probe statement.')
      return _ProbeInfoArtifact(parsed_result, None)

    pass_result = _ProbeInfoParsedResult(
        result_type=_ProbeInfoParsedResult.PASSED)
    if comp_name_for_probe_statement is None:
      return _ProbeInfoArtifact(pass_result, None)

    if all(
        e.component_name.startswith(comp_name_for_probe_statement)
        for e in loaded_component_probe_statements):
      return _ProbeInfoArtifact(pass_result, loaded_component_probe_statements)

    return _ProbeInfoArtifact(pass_result, [
        probe_config_types.ComponentProbeStatement(
            original.category_name,
            f'{comp_name_for_probe_statement}-{original.component_name}',
            original.statement)
        for original in loaded_component_probe_statements
    ])

  @classmethod
  def BuildProbeInfo(cls, probe_statement: str) -> _ProbeInfo:
    probe_info = _ProbeInfo(probe_function_name=cls._CONVERTER_NAME)
    probe_info.probe_parameters.add(name=cls._PARAMETER_NAME,
                                    string_value=probe_statement)
    return probe_info

  @classmethod
  def ComponentProbeStatementToProbeInfo(
      cls, component_probe_statement: probe_config_types.ComponentProbeStatement
  ) -> _ProbeInfo:
    return cls.BuildProbeInfo(
        json_utils.DumpStr(component_probe_statement.statement))


class _ProbeDataSourceImpl(_IProbeDataSource):
  """A record class for a source of probe statement and its metadata.

  Instances of this class are the source for generating the final probe bundle.

  Attributes:
    component_name: A string of the name of the component.
    probe_info: An instance of `_ProbeInfo`.
    fingerprint: A string of fingerprint of this instance, like a kind of
        unique identifier.
  """

  def __init__(self, component_name: str, probe_info: _ProbeInfo):
    self.component_name = component_name
    self.probe_info = probe_info

  @type_utils.LazyProperty
  def fingerprint(self) -> str:
    probe_param_values = {}
    for probe_param in self.probe_info.probe_parameters:
      probe_param_values.setdefault(probe_param.name, [])
      value_attr_name = probe_param.WhichOneof('value')
      probe_param_values[probe_param.name].append(
          getattr(probe_param, value_attr_name) if value_attr_name else None)
    serializable_data = {
        'probe_function_name': self.probe_info.probe_function_name,
        'probe_parameters': {
            k: sorted(v)
            for k, v in probe_param_values.items()
        },
    }
    hash_engine = hashlib.sha1()
    hash_engine.update(
        json_utils.DumpStr(serializable_data, sort_keys=True).encode('utf-8'))
    return hash_engine.hexdigest()


@type_utils.CachedGetter
def _GetClientPayloadPb2Content():
  return file_utils.ReadFile(client_payload_pb2.__file__, encoding=None)


@type_utils.CachedGetter
def _GetRuntimeProbeWrapperContent():
  full_path = os.path.join(_RESOURCE_PATH, 'runtime_probe_wrapper.py')
  return file_utils.ReadFile(full_path, encoding=None)


class _ProbedOutcomePreprocessConclusion(NamedTuple):
  probed_outcome: client_payload_pb2.ProbedOutcome
  intrivial_error_msg: Optional[str]
  probed_components: Optional[Sequence[str]]
  probed_generic_components: Optional[Mapping[str, Sequence[str]]]

  @classmethod
  def FromNoProbeResults(cls, probed_outcome, error_msg):
    return cls(probed_outcome, error_msg, None, None)

  @classmethod
  def FromProbeResults(cls, probed_outcome, probed_components,
                       probed_generic_components):
    return cls(probed_outcome, None, probed_components,
               probed_generic_components)


def _GetComponentPartNames(
    ps_metadata: client_payload_pb2.ProbeStatementMetadata) -> Sequence[str]:
  return (ps_metadata.component_part_names
          if ps_metadata.component_part_names else [ps_metadata.component_name])


def _GetProbeParameterValue(probe_param: probe_info_analytics.ProbeParameter):
  which_one_of = probe_param.WhichOneof('value')
  if which_one_of is None:
    return None

  return getattr(probe_param, which_one_of)


USE_LATEST_IMAGE = ('Please use the latest ChromeOS test image and run the '
                    'probe test bundle again. If the probe test still fails, '
                    'please contact Google.')
PROBED_GENERIC_COMPS = ('No component(s) found with all probe values matching '
                        'AVL attributes. If the probe values are reasonable, '
                        'please correct the values in AVL.')
MULTIPLE_PROBED_COMPS = ('There are multiple components probed on the device. '
                         'Please confirm which values belong to this component'
                         ' before correcting AVL values.')


class ProbeInfoAnalyzer(probe_info_analytics.IProbeInfoAnalyzer):
  """Provides functionalities related to the probe tool."""

  def __init__(self, converters: Sequence[IProbeInfoConverter]):
    self._converters = {
        c.GetName(): c
        for c in itertools.chain(converters, [_RawProbeStatementConverter()])
    }

  def GetProbeSchema(self) -> _ProbeSchema:
    """See base class."""
    ret = _ProbeSchema()
    for converter in self._converters.values():
      ret.probe_function_definitions.append(converter.GenerateDefinition())
    return ret

  def ValidateProbeInfo(self, probe_info: _ProbeInfo,
                        allow_missing_params: bool) -> _ProbeInfoParsedResult:
    """See base class."""
    probe_info_parsed_result, converter = self._LookupProbeConverter(
        probe_info.probe_function_name)
    if not converter:
      return probe_info_parsed_result
    parse_result = converter.ParseProbeParams(probe_info.probe_parameters,
                                              allow_missing_params)
    return parse_result.probe_info_parsed_result

  def CreateProbeDataSource(self, component_name: str,
                            probe_info: _ProbeInfo) -> _IProbeDataSource:
    """See base class."""
    return _ProbeDataSourceImpl(component_name, probe_info)

  def DumpProbeDataSource(
      self, probe_data_source: _IProbeDataSource) -> _ProbeInfoArtifact[str]:
    """See base class."""
    result = self._ConvertProbeDataSourceToProbeStatement(
        typing.cast(_ProbeDataSourceImpl, probe_data_source))
    if result.output is None:
      return result

    builder = probe_config_types.ProbeConfigPayload()
    for probe_statement in result.output:
      builder.AddComponentProbeStatement(probe_statement)
    return _ProbeInfoArtifact(result.probe_info_parsed_result,
                              builder.DumpToString())

  def GenerateDummyProbeStatement(
      self, reference_probe_data_source: _IProbeDataSource) -> str:
    """See base class."""
    reference_probe_data_source = typing.cast(_ProbeDataSourceImpl,
                                              reference_probe_data_source)
    return json_utils.DumpStr({
        '<unknown_component_category>': {
            reference_probe_data_source.component_name: {
                'eval': {
                    'unknown_probe_function': {},
                },
                'expect': {},
            },
        },
    })

  def GenerateRawProbeStatement(
      self, probe_data_source: _IProbeDataSource) -> _ProbeInfoArtifact[str]:
    """See base class."""
    return self.DumpProbeDataSource(probe_data_source)

  def LoadProbeInfo(self, probe_statement: str) -> _ProbeInfo:
    """See base class."""
    return _RawProbeStatementConverter.BuildProbeInfo(probe_statement)

  def GenerateProbeBundlePayload(
      self, probe_data_sources: Sequence[_IProbeDataSource]
  ) -> _MultiProbeInfoArtifact[_NamedFile]:
    """See base class."""
    probe_data_sources = typing.cast(Sequence[_ProbeDataSourceImpl],
                                     probe_data_sources)
    probe_info_parsed_results = []
    comp_probe_statements_list = []
    for probe_data_source in probe_data_sources:
      parse_result = self._ConvertProbeDataSourceToProbeStatement(
          probe_data_source)
      probe_info_parsed_results.append(parse_result.probe_info_parsed_result)
      comp_probe_statements_list.append(parse_result.output)

    if not all(comp_probe_statements_list):
      return _MultiProbeInfoArtifact(probe_info_parsed_results, None)

    builder = bundle_builder.BundleBuilder()
    builder.AddRegularFile(
        os.path.basename(client_payload_pb2.__file__),
        _GetClientPayloadPb2Content())
    builder.AddExecutableFile('runtime_probe_wrapper',
                              _GetRuntimeProbeWrapperContent())
    builder.SetRunnerFilePath('runtime_probe_wrapper')

    metadata = client_payload_pb2.ProbeBundleMetadata()
    pc_payload = probe_config_types.ProbeConfigPayload()

    categories = set()

    # Add component probe statements to probe config.
    for i, probe_data_source in enumerate(probe_data_sources):
      ps_metadata = metadata.probe_statement_metadatas.add(
          component_name=probe_data_source.component_name,
          fingerprint=probe_data_source.fingerprint)
      for comp_ps in comp_probe_statements_list[i]:
        ps_metadata.component_part_names.append(comp_ps.component_name)
        pc_payload.AddComponentProbeStatement(comp_ps)
        categories.add(comp_ps.category_name)

    # Add generic probe statements to probe config.
    for ps_gen in (generic_probe_statement
                   .GetAllRuntimeProbeSupportedGenericProbeStatements()):
      if ps_gen.probe_category in categories:
        ps = ps_gen.GenerateProbeStatement()
        ps.UpdateExpect({})
        pc_payload.AddComponentProbeStatement(ps)

    metadata.probe_config_file_path = 'probe_config.json'
    builder.AddRegularFile(metadata.probe_config_file_path,
                           pc_payload.DumpToString().encode('utf-8'))

    builder.AddRegularFile('metadata.prototxt',
                           text_format.MessageToBytes(metadata))

    # TODO(yhong): Construct a more meaningful file name according to the
    #     expected user scenario.
    result_file = _NamedFile('probe_bundle' + builder.FILE_NAME_EXT,
                             builder.Build())
    return _MultiProbeInfoArtifact(probe_info_parsed_results, result_file)

  def AnalyzeQualProbeTestResultPayload(
      self, probe_data_source: _IProbeDataSource,
      probe_result_payload: bytes) -> _ProbeInfoTestResult:
    """See base class."""
    probe_data_source = typing.cast(_ProbeDataSourceImpl, probe_data_source)
    preproc_conclusion = self._PreprocessProbeResultPayload(
        probe_result_payload)

    num_ps_metadatas = len(
        preproc_conclusion.probed_outcome.probe_statement_metadatas)
    if num_ps_metadatas != 1:
      raise _PayloadInvalidError(
          f'Incorrect number of probe statements: {num_ps_metadatas}.')

    ps_metadata = preproc_conclusion.probed_outcome.probe_statement_metadatas[0]
    if ps_metadata.component_name != probe_data_source.component_name:
      raise _PayloadInvalidError('Probe statement component name mismatch.')

    if ps_metadata.fingerprint != probe_data_source.fingerprint:
      return _ProbeInfoTestResult(result_type=_ProbeInfoTestResult.LEGACY)

    if preproc_conclusion.intrivial_error_msg:
      return _ProbeInfoTestResult(
          result_type=_ProbeInfoTestResult.INTRIVIAL_ERROR,
          intrivial_error_msg=preproc_conclusion.intrivial_error_msg)

    expect_component_parts = set(_GetComponentPartNames(ps_metadata))
    missing_component_parts = (
        expect_component_parts - set(preproc_conclusion.probed_components))
    if not missing_component_parts:
      return _ProbeInfoTestResult(result_type=_ProbeInfoTestResult.PASSED)

    # TODO(b/293377003): Enable in production.
    if not config.Config().is_prod:
      suggestions, suggestion_msg = self._AnalyzeGenericProbeResult(
          preproc_conclusion.probed_generic_components, probe_data_source)

      if suggestions or suggestion_msg:
        return _ProbeInfoTestResult(
            result_type=_ProbeInfoTestResult.PROBE_PRAMETER_SUGGESTION,
            probe_parameter_suggestions=suggestions,
            suggestion_msg=suggestion_msg)

    return _ProbeInfoTestResult(
        result_type=_ProbeInfoTestResult.INTRIVIAL_ERROR, intrivial_error_msg=(
            f'Component(s) not found: ({missing_component_parts}).\n'
            f'{USE_LATEST_IMAGE}'))

  def AnalyzeDeviceProbeResultPayload(
      self, probe_data_sources: Sequence[_IProbeDataSource],
      probe_result_payload: bytes) -> _DeviceProbeResultAnalyzedResult:
    """See base class."""
    probe_data_sources = typing.cast(Sequence[_ProbeDataSourceImpl],
                                     probe_data_sources)
    preproc_conclusion = self._PreprocessProbeResultPayload(
        probe_result_payload)
    pds_of_comp_name = {pds.component_name: pds
                        for pds in probe_data_sources}
    ps_metadata_of_comp_name = {
        m.component_name: m
        for m in preproc_conclusion.probed_outcome.probe_statement_metadatas
    }
    unknown_comp_names = set(ps_metadata_of_comp_name.keys()) - set(
        pds_of_comp_name.keys())
    if unknown_comp_names:
      raise _PayloadInvalidError('The probe result payload contains unknown '
                                 f'components: {unknown_comp_names}.')
    if preproc_conclusion.intrivial_error_msg:
      return _DeviceProbeResultAnalyzedResult(
          intrivial_error_msg=preproc_conclusion.intrivial_error_msg,
          probe_info_test_results=None)
    pi_test_results = []
    probed_components = set(preproc_conclusion.probed_components)
    for pds in probe_data_sources:
      pi_test_res = _ProbeInfoTestResult()
      comp_name = pds.component_name
      ps_metadata = ps_metadata_of_comp_name.get(comp_name, None)
      if ps_metadata is None:
        pi_test_res.result_type = _ProbeInfoTestResult.NOT_INCLUDED
      elif ps_metadata.fingerprint != pds.fingerprint:
        pi_test_res.result_type = _ProbeInfoTestResult.LEGACY
      elif not set(_GetComponentPartNames(ps_metadata)) - probed_components:
        pi_test_res.result_type = _ProbeInfoTestResult.PASSED
      else:
        suggestions, suggestion_msg = self._AnalyzeGenericProbeResult(
            preproc_conclusion.probed_generic_components, pds)
        if suggestions or suggestion_msg:
          pi_test_res.probe_parameter_suggestions.extend(suggestions)
          pi_test_res.suggestion_msg = suggestion_msg
          pi_test_res.result_type = (
              _ProbeInfoTestResult.PROBE_PRAMETER_SUGGESTION)
        else:
          pi_test_res.result_type = _ProbeInfoTestResult.NOT_PROBED
      pi_test_results.append(pi_test_res)
    return _DeviceProbeResultAnalyzedResult(
        intrivial_error_msg=None, probe_info_test_results=pi_test_results)

  def _LookupProbeConverter(
      self, converter_name: str
  ) -> Tuple[_ProbeInfoParsedResult, IProbeInfoConverter]:
    """A helper method to find the probe statement converter instance by name.

    When the target probe converter doesn't exist, the method creates and
    returns a `_ProbeInfoParsedResult` message so that the caller merely
    needs to forward the error message without constructing it.

    Args:
      converter_name: A string of name of the target converter.

    Returns:
      A pair of the following:
        - An instance of `_ProbeInfoParsedResult` if not found; otherwise
          `None`.
        - An instance of `IProbeInfoConverter` if found;
          otherwise `None`.
    """
    converter = self._converters.get(converter_name)
    if converter:
      parsed_result = None
    else:
      parsed_result = _ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.ResultType.INCOMPATIBLE_ERROR,
          general_error_msg=f'Unknown probe converter: {converter_name!r}.')
    return parsed_result, converter

  def _ConvertProbeDataSourceToProbeStatement(
      self, probe_data_source: _ProbeDataSourceImpl
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    probe_info_parsed_result, converter = self._LookupProbeConverter(
        probe_data_source.probe_info.probe_function_name)
    if not converter:
      return _ProbeInfoArtifact(probe_info_parsed_result, None)
    return converter.ParseProbeParams(
        probe_data_source.probe_info.probe_parameters, False,
        comp_name_for_probe_statement=probe_data_source.component_name)

  def _PreprocessProbeResultPayload(
      self, probe_result_payload: bytes) -> _ProbedOutcomePreprocessConclusion:
    try:
      probed_outcome = client_payload_pb2.ProbedOutcome()
      text_format.Parse(probe_result_payload, probed_outcome)
    except text_format.ParseError as e:
      raise _PayloadInvalidError('Unable to load and parse the content.') from e

    rp_invocation_result = probed_outcome.rp_invocation_result
    if rp_invocation_result.result_type != rp_invocation_result.FINISHED:
      return _ProbedOutcomePreprocessConclusion.FromNoProbeResults(
          probed_outcome, ('The invocation of runtime_probe is abnormal: '
                           f'type={rp_invocation_result.result_type}.'))
    if rp_invocation_result.return_code != 0:
      return _ProbedOutcomePreprocessConclusion.FromNoProbeResults(
          probed_outcome, ('The return code of runtime probe is non-zero: '
                           f'{rp_invocation_result.return_code}.'))

    known_component_names = set(
        itertools.chain.from_iterable(
            _GetComponentPartNames(m)
            for m in probed_outcome.probe_statement_metadatas))
    probed_components = []
    probed_generic_components = collections.defaultdict(list)
    try:
      probed_result = json_utils.LoadStr(
          rp_invocation_result.raw_stdout.decode('utf-8'))
      for category, category_probed_results in probed_result.items():
        for probed_component in category_probed_results:
          if probed_component['name'] == 'generic':
            probed_generic_components[category].append(
                probed_component['values'])
            continue
          if probed_component['name'] not in known_component_names:
            raise ValueError(f'Unexpected component: {probed_component}.')
          probed_components.append(probed_component['name'])
    except Exception as e:
      return _ProbedOutcomePreprocessConclusion.FromNoProbeResults(
          probed_outcome, f'The output of runtime_probe is invalid: {e}.')

    return _ProbedOutcomePreprocessConclusion.FromProbeResults(
        probed_outcome, probed_components, probed_generic_components)

  def _AnalyzeGenericProbeResult(
      self, generic_probe_result: Mapping[str, Sequence[Mapping[str, str]]],
      probe_data_source: _ProbeDataSourceImpl
  ) -> Tuple[Sequence[_ProbeParameterSuggestion], str]:
    generic_parsed_results = []
    probe_params = collections.defaultdict(set)

    probe_info = probe_data_source.probe_info
    probe_parameters = probe_info.probe_parameters
    unused_parsed_result, converter = self._LookupProbeConverter(
        probe_info.probe_function_name)
    if not converter or not isinstance(converter,
                                       IBidirectionalProbeInfoConverter):
      return [], ''

    generic_parsed_results = converter.ParseProbeResult(generic_probe_result)
    probe_parameters = converter.GetNormalizedProbeParams(probe_parameters)

    for param in probe_parameters:
      param_val = _GetProbeParameterValue(param)
      probe_params[param.name].add(param_val)

    # Collect names of all mismatched parameters.
    mismatch_param_names = set()
    param_name_to_category = {}
    for parsed_result in generic_parsed_results:
      param = parsed_result.probe_parameter
      if param.name in mismatch_param_names:
        continue

      param_val = _GetProbeParameterValue(param)
      if param_val not in probe_params[param.name]:
        mismatch_param_names.add(param.name)
        param_name_to_category[param.name] = parsed_result.component_category

    # Collect the expected values of the mismatched parameters from probe
    # parameters.
    expected_params = collections.defaultdict(list)
    probe_parameters = probe_data_source.probe_info.probe_parameters
    for probe_param in probe_parameters:
      if probe_param.name in mismatch_param_names:
        val = _GetProbeParameterValue(probe_param)
        expected_params[probe_param.name].append(val)

    # Collect the probed values of the mismatched parameters from generic probe
    # results.
    generic_probe_params = collections.defaultdict(list)
    for parsed_result in generic_parsed_results:
      probe_param = parsed_result.probe_parameter
      if probe_param.name in mismatch_param_names:
        val = _GetProbeParameterValue(probe_param)
        generic_probe_params[probe_param.name].append(val)

    param_hints = {}
    for param_name in mismatch_param_names:
      lines = [
          (f'expected: "{expected_params[param_name]}", '
           f'probed {len(generic_probe_params[param_name])} '
           f'{param_name_to_category[param_name]} component(s) with value:')
      ]

      for idx, comp_val in enumerate(generic_probe_params[param_name]):
        lines.append(f'component {idx+1}: "{comp_val}"')
      param_hints[param_name] = '\n'.join(lines)

    return (self._GenerateSuggestions(param_hints, probe_data_source),
            self._GenerateSuggestionMsg(expected_params, generic_probe_params,
                                        mismatch_param_names, converter))

  def _GenerateSuggestions(
      self,
      param_hints: Mapping[str, str],
      probe_data_source: _ProbeDataSourceImpl,
  ) -> Sequence[_ProbeParameterSuggestion]:
    suggestions = []
    probe_parameters = probe_data_source.probe_info.probe_parameters
    probe_params = sorted(
        enumerate(probe_parameters),
        key=lambda probe_param: probe_param[1].name)

    suggestions = collections.OrderedDict()
    for idx, probe_param in probe_params:
      param_name = probe_param.name
      if param_name in param_hints and param_name not in suggestions:
        suggestions[param_name] = _ProbeParameterSuggestion(
            index=idx, hint=param_hints[param_name])

    return list(suggestions.values())

  def _GenerateSuggestionMsg(
      self, expected_params: CollectedProbeParams,
      generic_probe_params: CollectedProbeParams,
      mismatch_param_names: Collection[str],
      converter: IBidirectionalProbeInfoConverter) -> str:
    if not mismatch_param_names:
      return ''

    msg_list = [PROBED_GENERIC_COMPS]

    # Check for multiple probe results of the same component category.
    if any(
        len(generic_probe_params[param_name]) > 1
        for param_name in mismatch_param_names):
      msg_list.append(MULTIPLE_PROBED_COMPS)

    # Converter-specific checks.
    converter_msg = converter.GenerateSuggestionMsg(
        expected_params, generic_probe_params, mismatch_param_names)
    msg_list.extend(converter_msg)

    return ' '.join(msg_list)
