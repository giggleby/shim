# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import hashlib
import itertools
import os
import typing
from typing import NamedTuple, Optional, Sequence, Tuple

from google.protobuf import text_format

from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.probe_info_service.app_engine import bundle_builder
from cros.factory.probe_info_service.app_engine.probe_tools import client_payload_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import type_utils


class IComponentProbeStatementConverter(abc.ABC):
  """Represents a converter for probe info to component probe statement."""

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
  ) -> Tuple[probe_info_analytics.ProbeInfoParsedResult,
             Optional[probe_config_types.ComponentProbeStatement]]:
    """Walk through the given probe parameters.

    The method first validate each probe parameter.  Then if specified,
    it also generates the probe statement from the given input.

    Args:
      probe_params: A list of `ProbeParameter` to validate.
      allow_missing_params: Whether missing required probe parameters is
          allowed.
      comp_name_for_probe_statement: If set, this method generates the probe
          statement with the specified component name when all probe parameters
          are valid.

    Returns:
      A pair of the following:
        - `ProbeInfoParsedResult`
        - A probe statement object or `None`.
    """


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
_ProbeInfoArtifact = probe_info_analytics.ProbeInfoArtifact
_MultiProbeInfoArtifact = probe_info_analytics.MultiProbeInfoArtifact
_NamedFile = probe_info_analytics.NamedFile
_IProbeDataSource = probe_info_analytics.IProbeDataSource
_PayloadInvalidError = probe_info_analytics.PayloadInvalidError


class _RawProbeStatementConverter(IComponentProbeStatementConverter):
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
  ) -> Tuple[_ProbeInfoParsedResult,
             Optional[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    if (len(probe_params) != 1 or
        probe_params[0].name != self._PARAMETER_NAME or
        probe_params[0].WhichOneof('value') != 'string_value'):
      parsed_result = _ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
          general_error_msg='Got unexpected probe parameter(s).')
      return parsed_result, None

    try:
      loaded_component_probe_statement = (
          probe_config_types.ComponentProbeStatement.FromDict(
              json_utils.LoadStr(probe_params[0].string_value)))
    except ValueError as ex:
      parsed_result = _ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.PROBE_PARAMETER_ERROR)
      parsed_result.probe_parameter_errors.add(
          index=0,
          hint=f'Unable to load the component probe statement in JSON: {ex}.')
      return parsed_result, None

    parsed_result = _ProbeInfoParsedResult(
        result_type=_ProbeInfoParsedResult.PASSED)
    component_probe_statement = None
    if comp_name_for_probe_statement is not None:
      component_probe_statement = probe_config_types.ComponentProbeStatement(
          loaded_component_probe_statement.category_name,
          comp_name_for_probe_statement,
          loaded_component_probe_statement.statement)
    return parsed_result, component_probe_statement

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


class ProbeInfoAnalyzer(probe_info_analytics.IProbeInfoAnalyzer):
  """Provides functionalities related to the probe tool."""

  def __init__(self, converters: Sequence[IComponentProbeStatementConverter]):
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
    if converter:
      probe_info_parsed_result, unused_ps = converter.ParseProbeParams(
          probe_info.probe_parameters, allow_missing_params)
    return probe_info_parsed_result

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
    builder.AddComponentProbeStatement(result.output)
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
    probe_statements = []
    for probe_data_source in probe_data_sources:
      pi_parsed_result, ps = self._ConvertProbeDataSourceToProbeStatement(
          probe_data_source)
      probe_statements.append(ps)
      probe_info_parsed_results.append(pi_parsed_result)

    if any(ps is None for ps in probe_statements):
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

    for i, probe_data_source in enumerate(probe_data_sources):
      metadata.probe_statement_metadatas.add(
          component_name=probe_data_source.component_name,
          fingerprint=probe_data_source.fingerprint)
      if probe_statements[i]:
        pc_payload.AddComponentProbeStatement(probe_statements[i])

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

    if preproc_conclusion.probed_components:
      return _ProbeInfoTestResult(result_type=_ProbeInfoTestResult.PASSED)

    # TODO(yhong): Provide hints from generic probed result.
    return _ProbeInfoTestResult(
        result_type=_ProbeInfoTestResult.INTRIVIAL_ERROR,
        intrivial_error_msg='No component is found.')

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
    pi_test_result_types = []
    for pds in probe_data_sources:
      comp_name = pds.component_name
      ps_metadata = ps_metadata_of_comp_name.get(comp_name, None)
      if ps_metadata is None:
        pi_test_result_types.append(_ProbeInfoTestResult.NOT_INCLUDED)
      elif ps_metadata.fingerprint != pds.fingerprint:
        pi_test_result_types.append(_ProbeInfoTestResult.LEGACY)
      elif any(c == comp_name for c in preproc_conclusion.probed_components):
        pi_test_result_types.append(_ProbeInfoTestResult.PASSED)
      else:
        pi_test_result_types.append(_ProbeInfoTestResult.NOT_PROBED)
    return _DeviceProbeResultAnalyzedResult(
        intrivial_error_msg=None, probe_info_test_results=[
            _ProbeInfoTestResult(result_type=t) for t in pi_test_result_types
        ])

  def _LookupProbeConverter(
      self, converter_name: str
  ) -> Tuple[_ProbeInfoParsedResult, IComponentProbeStatementConverter]:
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
        - An instance of `IComponentProbeStatementConverter` if found;
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
  ) -> _ProbeInfoArtifact[probe_config_types.ComponentProbeStatement]:
    probe_info_parsed_result, converter = self._LookupProbeConverter(
        probe_data_source.probe_info.probe_function_name)
    if converter:
      probe_info_parsed_result, ps = converter.ParseProbeParams(
          probe_data_source.probe_info.probe_parameters, False,
          comp_name_for_probe_statement=probe_data_source.component_name)
    else:
      ps = None
    return _ProbeInfoArtifact(probe_info_parsed_result, ps)

  def _PreprocessProbeResultPayload(
      self, probe_result_payload: bytes) -> _ProbedOutcomePreprocessConclusion:
    try:
      probed_outcome = client_payload_pb2.ProbedOutcome()
      text_format.Parse(probe_result_payload, probed_outcome)
    except text_format.ParseError as e:
      raise _PayloadInvalidError('Unable to load and parse the content.') from e

    rp_invocation_result = probed_outcome.rp_invocation_result
    if rp_invocation_result.result_type != rp_invocation_result.FINISHED:
      return _ProbedOutcomePreprocessConclusion(
          probed_outcome, ('The invocation of runtime_probe is abnormal: '
                           f'type={rp_invocation_result.result_type}.'), None)
    if rp_invocation_result.return_code != 0:
      return _ProbedOutcomePreprocessConclusion(
          probed_outcome, ('The return code of runtime probe is non-zero: '
                           f'{rp_invocation_result.return_code}.'), None)

    known_component_names = set(
        m.component_name for m in probed_outcome.probe_statement_metadatas)
    probed_components = []
    try:
      probed_result = json_utils.LoadStr(
          rp_invocation_result.raw_stdout.decode('utf-8'))
      for category_probed_results in probed_result.values():
        for probed_component in category_probed_results:
          if probed_component['name'] not in known_component_names:
            raise ValueError(f'Unexpected component: {probed_component}.')
          probed_components.append(probed_component['name'])
    except Exception as e:
      return _ProbedOutcomePreprocessConclusion(
          probed_outcome, f'The output of runtime_probe is invalid: {e}.', None)

    return _ProbedOutcomePreprocessConclusion(
        probed_outcome, None, probed_components=probed_components)
