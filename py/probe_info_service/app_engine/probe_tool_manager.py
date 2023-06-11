# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import collections
import hashlib
import itertools
import os
import re
from typing import Any, Callable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from google.protobuf import text_format

from cros.factory.probe.runtime_probe import probe_config_definition
from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.probe_info_service.app_engine import bundle_builder
from cros.factory.probe_info_service.app_engine import client_payload_pb2  # pylint: disable=no-name-in-module
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import type_utils


_RESOURCE_PATH = os.path.join(
    os.path.realpath(os.path.dirname(__file__)), 'resources')

ProbeSchema = stubby_pb2.ProbeSchema
ProbeFunctionDefinition = stubby_pb2.ProbeFunctionDefinition
ProbeParameterValueType = stubby_pb2.ProbeParameterDefinition.ValueType
ProbeInfo = stubby_pb2.ProbeInfo
ProbeInfoParsedResult = stubby_pb2.ProbeInfoParsedResult
ProbeParameterSuggestion = stubby_pb2.ProbeParameterSuggestion
ProbeInfoTestResult = stubby_pb2.ProbeInfoTestResult


class _IncompatibleError(Exception):
  """Raised when the given input is incompatible with the probe tool."""


class _IComponentProbeStatementConverter(abc.ABC):
  """Represents a converter for probe info to component probe statement."""

  @abc.abstractmethod
  def GetName(self) -> str:
    """Gets the converter's unique name."""

  @abc.abstractmethod
  def GenerateDefinition(self) -> ProbeFunctionDefinition:
    """Returns the schema of this converter."""

  @abc.abstractmethod
  def ParseProbeParams(
      self, probe_params: Sequence[stubby_pb2.ProbeParameter],
      allow_missing_params: bool, comp_name_for_probe_statement=None
  ) -> Tuple[ProbeInfoParsedResult,
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


class RawProbeStatementConverter(_IComponentProbeStatementConverter):
  """A converter that is simply a wrapper of raw probe statement string."""

  _CONVERTER_NAME = 'raw_probe_statement'
  _CONVERTER_DESCRIPTION = 'Probe by the given raw probe statement.'

  _PARAMETER_NAME = 'json_text'
  _PARAMETER_DESCRIPTION = 'The raw probe statement text value in JSON.'

  def GetName(self) -> str:
    """See base class."""
    return self._CONVERTER_NAME

  def GenerateDefinition(self) -> ProbeFunctionDefinition:
    """See base class."""
    ret = ProbeFunctionDefinition(name=self._CONVERTER_NAME,
                                  description=self._CONVERTER_DESCRIPTION)
    ret.parameter_definitions.add(name=self._PARAMETER_NAME,
                                  description=self._PARAMETER_DESCRIPTION,
                                  value_type=ProbeParameterValueType.STRING)
    return ret

  def ParseProbeParams(
      self, probe_params: Sequence[stubby_pb2.ProbeParameter],
      allow_missing_params: bool, comp_name_for_probe_statement=None
  ) -> Tuple[ProbeInfoParsedResult,
             Optional[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    if (len(probe_params) != 1 or
        probe_params[0].name != self._PARAMETER_NAME or
        probe_params[0].WhichOneof('value') != 'string_value'):
      parsed_result = ProbeInfoParsedResult(
          result_type=ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
          general_error_msg='Got unexpected probe parameter(s).')
      return parsed_result, None

    try:
      loaded_component_probe_statement = (
          probe_config_types.ComponentProbeStatement.FromDict(
              json_utils.LoadStr(probe_params[0].string_value)))
    except ValueError as ex:
      parsed_result = ProbeInfoParsedResult(
          result_type=ProbeInfoParsedResult.PROBE_PARAMETER_ERROR)
      parsed_result.probe_parameter_errors.add(
          index=0,
          hint=f'Unable to load the component probe statement in JSON: {ex}.')
      return parsed_result, None

    parsed_result = ProbeInfoParsedResult(
        result_type=ProbeInfoParsedResult.PASSED)
    component_probe_statement = None
    if comp_name_for_probe_statement is not None:
      component_probe_statement = probe_config_types.ComponentProbeStatement(
          loaded_component_probe_statement.category_name,
          comp_name_for_probe_statement,
          loaded_component_probe_statement.statement)
    return parsed_result, component_probe_statement

  @classmethod
  def BuildProbeInfo(cls, probe_statement: str) -> ProbeInfo:
    probe_info = stubby_pb2.ProbeInfo(probe_function_name=cls._CONVERTER_NAME)
    probe_info.probe_parameters.add(name=cls._PARAMETER_NAME,
                                    string_value=probe_statement)
    return probe_info

  @classmethod
  def ComponentProbeStatementToProbeInfo(
      cls, component_probe_statement: probe_config_types.ComponentProbeStatement
  ) -> ProbeInfo:
    return cls.BuildProbeInfo(
        json_utils.DumpStr(component_probe_statement.statement))


class _ParamValueConverter:
  """Converter for the input of the probe statement from the probe parameter.

  Properties:
    value_type: Enum item of `ProbeParameterValueType`.
  """

  def __init__(self, value_type_name, value_converter=None):
    self._probe_param_field_name = value_type_name + '_value'
    self._value_converter = value_converter or self._DummyValueConverter

    self.value_type = getattr(ProbeParameterValueType, value_type_name.upper())

  def ConvertValue(self, probe_parameter):
    """Converts the given probe parameter to the probe statement's value.

    Args:
      probe_parameter: The target `ProbeParameter` to convert from.

    Returns:
      A value that the probe statement generator accepts.

    Raises:
      - `ValueError` if the format of the given probe parameter value is
        incorrect.
      - `_IncompatibleError` on all unexpected failures.
    """
    which_one_of = probe_parameter.WhichOneof('value')
    if which_one_of not in (None, self._probe_param_field_name):
      raise _IncompatibleError(f'Unexpected type {which_one_of!r}.')

    return self._value_converter(
        getattr(probe_parameter, self._probe_param_field_name))

  @classmethod
  def _DummyValueConverter(cls, value):
    return value


class _ProbeParamInput(NamedTuple):
  index: int
  raw_value: stubby_pb2.ProbeParameter


class _IProbeStatementParam(abc.ABC):
  """Interface of parameter definitions.

  This is for `_SingleProbeFuncConverter` to convert probe info parameters to
  expected values in probe statements.
  """

  @property
  @abc.abstractmethod
  def probe_info_param_definitions(
      self) -> Mapping[str, stubby_pb2.ProbeParameterDefinition]:
    """All related probe info parameter definitions."""

  @property
  @abc.abstractmethod
  def probe_statement_param_name(self) -> Optional[str]:
    """The parameter name used in the probe statement."""

  @abc.abstractmethod
  def ConvertValues(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParamInput]]
  ) -> Tuple[Sequence[Any], Sequence[ProbeParameterSuggestion]]:
    """Converts `probe_parameters` to expected values in probe statements.

    This function tries to collect and convert the values of the parameters
    defined in `self.probe_info_param_definitions` in `probe_parameters` into
    the expected values of the parameter with name
    `self.probe_statement_param_name` in the probe statement.

    Args:
      probe_parameters: The target message dictionary that maps probe
          parameter names to `_ProbeParamInput` list to convert.

    Returns:
      A pair of the following values:
        1. A list of converted values.
        2. A `ProbeParameterSuggestion` list containing parameters that were
            failed to convert or validate.
    """


class _SingleProbeStatementParam(_IProbeStatementParam):
  """Holds a one-to-one parameter for `_SingleProbeFuncConverter`.

  This can be used either to map one probe info parameter to one probe
  statement parameter for `_SingleProbeFuncConverter`, or as a sub-parameter
  for `_ConcatProbeStatementParam`.
  """

  def __init__(self, name: str, description: str,
               value_converter: _ParamValueConverter,
               ps_gen_checker: Optional[Callable] = None):
    self._name = name
    self._description = description
    self._value_converter = value_converter
    self._ps_gen_checker = ps_gen_checker
    self._is_informational = ps_gen_checker is None

  @property
  def probe_info_param_definitions(
      self) -> Mapping[str, stubby_pb2.ProbeParameterDefinition]:
    """See base class."""
    definition = stubby_pb2.ProbeParameterDefinition(
        name=self._name, description=self._description,
        value_type=self._value_converter.value_type)
    return {
        self._name: definition
    }

  @property
  def probe_statement_param_name(self) -> Optional[str]:
    """See base class."""
    return None if self._is_informational else self._name

  def ConvertValues(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParamInput]]
  ) -> Tuple[Sequence[Any], Sequence[ProbeParameterSuggestion]]:
    """See base class."""
    converted_values = []
    suggestions = []
    for probe_parameter in probe_parameters.get(self._name, []):
      try:
        value = self._value_converter.ConvertValue(probe_parameter.raw_value)
        if not self._is_informational:
          # Attempt to trigger the probe statement generator directly to see if
          # it's convertible.
          self._ps_gen_checker(value)
        converted_values.append(value)
      except _IncompatibleError as e:
        raise _IncompatibleError(
            f'Got improper probe parameter {self._name!r}: '
            f'{e}.') from e
      except (TypeError, ValueError) as e:
        suggestions.append(
            ProbeParameterSuggestion(index=probe_parameter.index, hint=str(e)))

    return converted_values, suggestions


class _ConcatProbeStatementParam(_IProbeStatementParam):
  """Holds a many-to-one parameter for `_SingleProbeFuncConverter`.

  The probe info parameter and probe statement parameter should be many-to-one.
  This is initialized with a sequence of `_SingleProbeStatementParam`.
  When generating expected values for the parameter, it first generates the
  values of all its `_SingleProbeStatementParam`, and then concatenates the
  values in the initialization order.
  """

  class _ConvertedValue(NamedTuple):
    index: int
    value: str

  def __init__(self, name: str,
               probe_info_params: Sequence[_SingleProbeStatementParam],
               ps_gen_checker: Optional[Callable]):
    self._name = name
    self._probe_info_params = probe_info_params
    self._ps_gen_checker = ps_gen_checker
    self._is_informational = ps_gen_checker is None

  @property
  def probe_info_param_definitions(
      self) -> Mapping[str, stubby_pb2.ProbeParameterDefinition]:
    """See base class."""
    definitions = collections.defaultdict()
    for probe_info_param in self._probe_info_params:
      definitions.update(probe_info_param.probe_info_param_definitions)

    return definitions

  @property
  def probe_statement_param_name(self) -> Optional[str]:
    """See base class."""
    return None if self._is_informational else self._name

  def ConvertValues(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParamInput]]
  ) -> Tuple[List[Any], Sequence[ProbeParameterSuggestion]]:
    """See base class."""
    converted_values = collections.OrderedDict()
    suggestions = []
    for probe_info_param in self._probe_info_params:
      param_name = next(iter(probe_info_param.probe_info_param_definitions))
      converted_values[param_name] = []
      for probe_parameter in probe_parameters[param_name]:
        sub_values, sub_suggestions = probe_info_param.ConvertValues(
            {param_name: [probe_parameter]})
        suggestions.extend(sub_suggestions)

        if sub_values:
          converted_values[param_name].append(
              self._ConvertedValue(probe_parameter.index, str(sub_values[0])))

    concat_values = []
    for values in itertools.product(*converted_values.values()):
      try:
        concat_value = ''.join(value.value for value in values)
        if self._ps_gen_checker:
          # Attempt to trigger the probe statement generator directly to see if
          # it's convertible.
          self._ps_gen_checker(concat_value)
        concat_values.append(concat_value)
      except (TypeError, ValueError) as e:
        suggestions.extend(
            ProbeParameterSuggestion(index=value.index, hint=str(e))
            for value in values)

    return concat_values, suggestions


class _IProbeParamSpec(abc.ABC):
  """Interface of probe parameter spec.

  This is for `_IComponentProbeStatementConverter` to define the relationship
  and conversion between probe info parameters and probe statement parameters.
  """

  @abc.abstractmethod
  def BuildProbeStatementParam(
      self,
      output_fields: Mapping[str, probe_config_types.OutputFieldDefinition],
  ) -> _IProbeStatementParam:
    """Builds an `_IProbeStatementParam` instance.

    Args:
      output_fields: A dictionary that maps probe statement parameter names to
          the corresponding `OutputFieldDefinition`. This can be used to get
          the default description and probe statement generator to initialize
          the `_IProbeStatementParam` instance.
    """


class _ProbeFunctionParam(_IProbeParamSpec):
  _DEFAULT_VALUE_TYPE_MAPPING = {
      probe_config_types.ValueType.INT: _ParamValueConverter('int'),
      probe_config_types.ValueType.STRING: _ParamValueConverter('string'),
  }

  def __init__(self, param_name: str, description: Optional[str] = None,
               value_converter: Optional[_ParamValueConverter] = None):
    self._param_name = param_name
    self._description = description
    self._value_converter = value_converter

  def BuildProbeStatementParam(
      self,
      output_fields: Mapping[str, probe_config_types.OutputFieldDefinition],
  ) -> _IProbeStatementParam:
    """See base class."""
    output_field = output_fields[self._param_name]
    return _SingleProbeStatementParam(
        self._param_name, self._description or output_field.description,
        (self._value_converter or
         self._DEFAULT_VALUE_TYPE_MAPPING[output_field.value_type]),
        output_field.probe_statement_generator)


class _InformationalParam(_IProbeParamSpec):

  def __init__(self, param_name: str, description: str,
               value_converter: _ParamValueConverter):
    self._param_name = param_name
    self._description = description
    self._value_converter = value_converter

  def BuildProbeStatementParam(
      self,
      output_fields: Mapping[str, probe_config_types.OutputFieldDefinition],
  ) -> _IProbeStatementParam:
    """See base class."""
    del output_fields
    ps_gen_checker = None
    return _SingleProbeStatementParam(self._param_name, self._description,
                                      self._value_converter, ps_gen_checker)


class _ConcatParam(_IProbeParamSpec):

  def __init__(
      self,
      param_name: str,
      probe_info_params: Sequence[_SingleProbeStatementParam],
      description: Optional[str] = None,
  ):
    self._param_name = param_name
    self._probe_info_params = probe_info_params
    self._description = description

  def BuildProbeStatementParam(
      self, output_fields: Mapping[str,
                                   probe_config_types.OutputFieldDefinition]
  ) -> _IProbeStatementParam:
    """See base class."""
    output_field = output_fields[self._param_name]
    return _ConcatProbeStatementParam(self._param_name, self._probe_info_params,
                                      output_field.probe_statement_generator)


class _SingleProbeFuncConverter(_IComponentProbeStatementConverter):
  """Converts probe info into a statement of one single probe function call."""

  _DEFAULT_VALUE_TYPE_MAPPING = {
      probe_config_types.ValueType.INT: _ParamValueConverter('int'),
      probe_config_types.ValueType.STRING: _ParamValueConverter('string'),
  }

  def __init__(self, ps_generator: probe_config_types.ProbeStatementDefinition,
               probe_function_name: str,
               probe_params: Optional[Sequence[_IProbeParamSpec]] = None):
    self._ps_generator = ps_generator
    self._probe_func_def = self._ps_generator.probe_functions[
        probe_function_name]
    output_fields: Mapping[str, probe_config_types.OutputFieldDefinition] = {
        f.name: f
        for f in self._probe_func_def.output_fields
    }

    if probe_params is None:
      probe_params = [_ProbeFunctionParam(n) for n in output_fields]

    self._probe_params: List[_IProbeStatementParam] = [
        spec.BuildProbeStatementParam(output_fields) for spec in probe_params
    ]

    self._name = (
        f'{self._ps_generator.category_name}.{self._probe_func_def.name}')

  @classmethod
  def FromDefaultRuntimeProbeStatementGenerator(
      cls, runtime_probe_category_name: str, runtime_probe_func_name: str,
      probe_params: Optional[Sequence[_IProbeParamSpec]] = None):
    ps_generator = probe_config_definition.GetProbeStatementDefinition(
        runtime_probe_category_name)
    return cls(ps_generator, runtime_probe_func_name, probe_params=probe_params)

  def GetName(self) -> str:
    """See base class."""
    return self._name

  def GenerateDefinition(self) -> ProbeFunctionDefinition:
    """See base class."""
    ret = ProbeFunctionDefinition(name=self._name,
                                  description=self._probe_func_def.description)
    ret.parameter_definitions.extend(
        definition for probe_param in self._probe_params
        for definition in probe_param.probe_info_param_definitions.values())

    return ret

  def ParseProbeParams(
      self, probe_params: Sequence[stubby_pb2.ProbeParameter],
      allow_missing_params: bool, comp_name_for_probe_statement=None
  ) -> Tuple[ProbeInfoParsedResult,
             Optional[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    probe_param_errors = []
    expected_values_of_field = collections.defaultdict(list)
    probe_param_inputs = collections.defaultdict(list)

    for index, probe_param in enumerate(probe_params):
      probe_param_inputs[probe_param.name].append(
          _ProbeParamInput(index, probe_param))

    try:
      expected_values_of_field, probe_param_errors = (
          self._ConvertProbeParamInputsToProbeStatementValues(
              probe_param_inputs, allow_missing_params))
    except _IncompatibleError as e:
      return (ProbeInfoParsedResult(
          result_type=ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
          general_error_msg=str(e)), None)

    if probe_param_errors:
      return (ProbeInfoParsedResult(
          result_type=ProbeInfoParsedResult.PROBE_PARAMETER_ERROR,
          probe_parameter_errors=probe_param_errors), None)

    ps = None
    if comp_name_for_probe_statement:
      field_names = tuple(expected_values_of_field)
      field_values_combinations = itertools.product(
          *expected_values_of_field.values())
      ps_expected_fields = [
          dict(zip(field_names, field_values))
          for field_values in field_values_combinations
      ]
      try:
        ps = self._ps_generator.GenerateProbeStatement(
            comp_name_for_probe_statement, self._probe_func_def.name,
            ps_expected_fields)
      except Exception as e:
        return (ProbeInfoParsedResult(
            result_type=ProbeInfoParsedResult.UNKNOWN_ERROR,
            general_error_msg=str(e)), None)
    return ProbeInfoParsedResult(result_type=ProbeInfoParsedResult.PASSED), ps

  def _ConvertProbeParamInputsToProbeStatementValues(
      self, probe_param_inputs: Mapping[str, Sequence[_ProbeParamInput]],
      allow_missing_params: bool
  ) -> Tuple[Mapping[str, Any], Sequence[ProbeParameterSuggestion]]:
    """Tries to convert the given `_ProbeParamInput` dictionary into the
    expected values in the probe statement.

    Args:
      probe_param_inputs: The target message dictionary that maps probe
          parameter names to `_ProbeParamInput` list to convert.
      allow_missing_params: Whether missing required probe parameters is
          allowed.

    Returns:
      A tuple of the following 2 items:
        1. A dictionary that maps probe parameter names to converted value list
        2. A `ProbeParameterSuggestion` list containing parameters that were
            failed to convert.

    Raises:
      `_IncompatibleError` if the parameter inputs are invalid.
    """
    probe_param_names = {
        probe_info_param_name
        for probe_param in self._probe_params
        for probe_info_param_name in probe_param.probe_info_param_definitions
    }
    probe_param_input_names = set(probe_param_inputs)

    missing_param_names = probe_param_names - probe_param_input_names
    if missing_param_names and not allow_missing_params:
      raise _IncompatibleError(
          f'Missing probe parameters: {", ".join(missing_param_names)}.')

    unknown_param_names = probe_param_input_names - probe_param_names
    if unknown_param_names:
      raise _IncompatibleError(
          f'Unknown probe parameters: {", ".join(unknown_param_names)}.')

    expected_values_of_field = collections.defaultdict(list)
    probe_param_errors = []

    for probe_param in self._probe_params:
      values, suggestions = probe_param.ConvertValues(probe_param_inputs)
      if probe_param.probe_statement_param_name:
        expected_values_of_field[
            probe_param.probe_statement_param_name] = values

      for suggestion in suggestions:
        probe_param_errors.append(suggestion)

    return expected_values_of_field, probe_param_errors


def _RemoveHexPrefixAndCapitalize(value: str) -> str:
  if not value.lower().startswith('0x'):
    raise ValueError('Expect hex value to start with "0x" or "0X".')
  return value[2:].upper()


def _RemoveHexPrefixAndLowerize(value: str) -> str:
  if not value.lower().startswith('0x'):
    raise ValueError('Expect hex value to start with "0x" or "0X".')
  return value[2:].lower()


def _CapitalizeHexValueWithoutPrefix(value: str) -> str:
  if value.lower().startswith('0x'):
    raise ValueError('Expect hex value not to start with "0x" or "0X".')
  return value.upper()


def _BuildCPUProbeStatementConverter() -> _IComponentProbeStatementConverter:
  builder = probe_config_types.ProbeStatementDefinitionBuilder('cpu')
  builder.AddProbeFunction(
      'generic_cpu', 'A currently non-existent runtime probe function for CPU.')
  builder.AddStrOutputField('identifier', 'Model name on x86, chip-id on ARM.')
  return _SingleProbeFuncConverter(builder.Build(), 'generic_cpu')


@type_utils.CachedGetter
def _GetAllConverters() -> Sequence[_IComponentProbeStatementConverter]:
  # TODO(yhong): Separate the data piece out the code logic.
  def _StringToRegexpOrString(value):
    PREFIX = '!re '
    if value.startswith(PREFIX):
      return re.compile(value.lstrip(PREFIX))
    return value

  return [
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'audio_codec', 'audio_codec', [
              _ProbeFunctionParam('name'),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'battery', 'generic_battery', [
              _ProbeFunctionParam('manufacturer'),
              _ProbeFunctionParam('model_name'),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'camera', 'mipi_camera', [
              _ConcatParam('mipi_module_id', [
                  _SingleProbeStatementParam('module_vid',
                                             'The camera module vendor ID.',
                                             _ParamValueConverter('string')),
                  _SingleProbeStatementParam(
                      'module_pid', 'The camera module product ID.',
                      _ParamValueConverter('string',
                                           _RemoveHexPrefixAndLowerize))
              ]),
              _ConcatParam('mipi_sensor_id', [
                  _SingleProbeStatementParam('sensor_vid',
                                             'The camera sensor vendor ID.',
                                             _ParamValueConverter('string')),
                  _SingleProbeStatementParam(
                      'sensor_pid', 'The camera sensor product ID.',
                      _ParamValueConverter(
                          'string',
                          _RemoveHexPrefixAndLowerize,
                      ))
              ])
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'camera', 'usb_camera', [
              _ProbeFunctionParam(
                  'usb_vendor_id', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix)),
              _ProbeFunctionParam(
                  'usb_product_id', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix)),
              _ProbeFunctionParam(
                  'usb_bcd_device', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix)),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'display_panel', 'edid', [
              _ProbeFunctionParam(
                  'product_id', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix)),
              _ProbeFunctionParam('vendor'),
              _InformationalParam('width', 'The width of display panel.',
                                  _ParamValueConverter('int')),
              _InformationalParam('height', 'The height of display panel.',
                                  _ParamValueConverter('int')),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'storage', 'mmc_storage', [
              _ProbeFunctionParam(
                  'mmc_manfid', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize)),
              _ProbeFunctionParam(
                  'mmc_name', value_converter=_ParamValueConverter(
                      'string', lambda hex_with_prefix: bytes.fromhex(
                          hex_with_prefix[2:]).decode('ascii'))),
              _ProbeFunctionParam(
                  'mmc_prv', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize)),
              _InformationalParam('size_in_gb', 'The storage size in GB.',
                                  _ParamValueConverter('int')),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'storage', 'nvme_storage', [
              _ProbeFunctionParam(
                  'pci_vendor', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize)),
              _ProbeFunctionParam(
                  'pci_device', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize)),
              _ProbeFunctionParam(
                  'pci_class', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize)),
              _ProbeFunctionParam('nvme_model'),
              _InformationalParam('size_in_gb', 'The storage size in GB.',
                                  _ParamValueConverter('int')),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'storage', 'ufs_storage', [
              _ProbeFunctionParam('ufs_vendor'),
              _ProbeFunctionParam('ufs_model'),
              _InformationalParam('size_in_gb', 'The storage size in GB.',
                                  _ParamValueConverter('int')),
          ]),
      _BuildCPUProbeStatementConverter(),
      RawProbeStatementConverter(),
  ]


class PayloadInvalidError(Exception):
  """Exception class raised when the given payload is invalid."""


class ProbeDataSource:
  """A record class for a source of probe statement and its metadata.

  Instances of this class are the source for generating the final probe bundle.

  Attributes:
    component_name: A string of the name of the component.
    probe_info: An instance of `ProbeInfo`.
    fingerprint: A string of fingerprint of this instance, like a kind of
        unique identifier.
  """

  def __init__(self, component_name: str, probe_info: ProbeInfo):
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


class ProbeInfoArtifact(NamedTuple):
  """A placeholder for any artifact generated from probe info(s).

  Many tasks performed by this module involve parsing the given `ProbeInfo`
  instance(s) to get any kind of output.  The probe info might not necessary be
  valid, the module need to return a structured summary for the parsed result
  all the time.  This class provides a placeholder for those methods.

  Properties:
    probe_info_parsed_result: (optional) an instance of `ProbeInfoParsedResult`
        if the source is a single `ProbeInfo` instance.
    probe_info_parsed_results: (optional) a list of instances of
        `ProbeInfoParsedResult` corresponds to the source of array of
        `ProbeInfo` instances.
    output: `None` or any kind of the output.
  """
  probe_info_parsed_result: ProbeInfoParsedResult
  output: Any

  @property
  def probe_info_parsed_results(self) -> List[ProbeInfoParsedResult]:
    # Since the input is always either one `ProbeInfo` or multiple `ProbeInfo`,
    # `self.probe_info_parsed_result` and `self.probe_info_parsed_results` are
    # mutually exclusively meaningful.  Therefore, we re-use the same
    # placeholder.
    return self.probe_info_parsed_result


class NamedFile(NamedTuple):
  """A placeholder represents a named file."""
  name: str
  content: bytes


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
  probed_components: Optional[List[str]]


class DeviceProbeResultAnalyzedResult(NamedTuple):
  """Placeholder for the analyzed result of a device probe result."""
  intrivial_error_msg: Optional[str]
  probe_info_test_results: Optional[List[ProbeInfoTestResult]]


class ProbeToolManager:
  """Provides functionalities related to the probe tool."""

  def __init__(self):
    self._converters = {c.GetName(): c
                        for c in _GetAllConverters()}

  def GetProbeSchema(self) -> ProbeSchema:
    """
    Returns:
      An instance of `ProbeSchema`.
    """
    ret = ProbeSchema()
    for converter in self._converters.values():
      ret.probe_function_definitions.append(converter.GenerateDefinition())
    return ret

  def ValidateProbeInfo(self, probe_info: ProbeInfo,
                        allow_missing_params: bool) -> ProbeInfoParsedResult:
    """Validate the given probe info.

    Args:
      probe_info: An instance of `ProbeInfo` to be validated.
      allow_missing_params: Whether missing some probe parameters is allowed
          or not.

    Returns:
        An instance of `ProbeInfoParsedResult` which records detailed
        validation result.
    """
    probe_info_parsed_result, converter = self._LookupProbeConverter(
        probe_info.probe_function_name)
    if converter:
      probe_info_parsed_result, unused_ps = converter.ParseProbeParams(
          probe_info.probe_parameters, allow_missing_params)
    return probe_info_parsed_result

  def CreateProbeDataSource(self, component_name,
                            probe_info) -> ProbeDataSource:
    """Creates the probe data source from the given probe_info."""
    return ProbeDataSource(component_name, probe_info)

  def DumpProbeDataSource(self, probe_data_source) -> ProbeInfoArtifact:
    """Dump the probe data source to a loadable probe statement string."""
    result = self._ConvertProbeDataSourceToProbeStatement(probe_data_source)
    if result.output is None:
      return result

    builder = probe_config_types.ProbeConfigPayload()
    builder.AddComponentProbeStatement(result.output)
    return ProbeInfoArtifact(result.probe_info_parsed_result,
                             builder.DumpToString())

  def GenerateDummyProbeStatement(
      self, reference_probe_data_source: ProbeDataSource) -> str:
    """Generate a dummy loadable probe statement string.

    This is a backup-plan in case `DumpProbeDataSource` fails.
    """
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
      self, probe_data_source: ProbeDataSource) -> ProbeInfoArtifact:
    """Generate raw probe statement string for the given probe data source.

    Args:
      probe_data_source: The source for the probe statement.

    Returns:
      An instance of `ProbeInfoArtifact`, which `output` property is a string
      of the probe statement or `None` if failed.
    """
    return self.DumpProbeDataSource(probe_data_source)

  def GenerateProbeBundlePayload(
      self, probe_data_sources: List[ProbeDataSource]) -> ProbeInfoArtifact:
    """Generates the payload for testing the given probe infos.

    Args:
      probe_data_source: The source of the test bundle.

    Returns:
      An instance of `ProbeInfoArtifact`, which `output` property is an instance
      of `NamedFile`, which represents the result payload for the user to
      download.
    """
    probe_info_parsed_results = []
    probe_statements = []
    for probe_data_source in probe_data_sources:
      pi_parsed_result, ps = self._ConvertProbeDataSourceToProbeStatement(
          probe_data_source)
      probe_statements.append(ps)
      probe_info_parsed_results.append(pi_parsed_result)

    if any(ps is None for ps in probe_statements):
      return ProbeInfoArtifact(probe_info_parsed_results, None)

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
    result_file = NamedFile('probe_bundle' + builder.FILE_NAME_EXT,
                            builder.Build())
    return ProbeInfoArtifact(probe_info_parsed_results, result_file)

  def AnalyzeQualProbeTestResultPayload(
      self, probe_data_source: ProbeDataSource,
      probe_result_payload: bytes) -> ProbeInfoTestResult:
    """Analyzes the given probe result payload for a qualification.

    Args:
      probe_data_source: The original source for the probe statement.
      probe_result_payload: A byte string of the payload to be analyzed.

    Returns:
      An instance of `ProbeInfoTestResult`.

    Raises:
      `PayloadInvalidError` if the given input is invalid.
    """
    preproc_conclusion = self._PreprocessProbeResultPayload(
        probe_result_payload)

    num_ps_metadatas = len(
        preproc_conclusion.probed_outcome.probe_statement_metadatas)
    if num_ps_metadatas != 1:
      raise PayloadInvalidError(
          f'Incorrect number of probe statements: {num_ps_metadatas}.')

    ps_metadata = preproc_conclusion.probed_outcome.probe_statement_metadatas[0]
    if ps_metadata.component_name != probe_data_source.component_name:
      raise PayloadInvalidError('Probe statement component name mismatch.')

    if ps_metadata.fingerprint != probe_data_source.fingerprint:
      return ProbeInfoTestResult(result_type=ProbeInfoTestResult.LEGACY)

    if preproc_conclusion.intrivial_error_msg:
      return ProbeInfoTestResult(
          result_type=ProbeInfoTestResult.INTRIVIAL_ERROR,
          intrivial_error_msg=preproc_conclusion.intrivial_error_msg)

    if preproc_conclusion.probed_components:
      return ProbeInfoTestResult(result_type=ProbeInfoTestResult.PASSED)

    # TODO(yhong): Provide hints from generic probed result.
    return ProbeInfoTestResult(result_type=ProbeInfoTestResult.INTRIVIAL_ERROR,
                               intrivial_error_msg='No component is found.')

  def AnalyzeDeviceProbeResultPayload(
      self, probe_data_sources: List[ProbeDataSource],
      probe_result_payload: bytes) -> DeviceProbeResultAnalyzedResult:
    """Analyzes the given probe result payload from a specific device.

    Args:
      probe_data_sources: The original sources for the probe statements.
      probed_result_payload: A byte string of the payload to be analyzed.

    Returns:
      List of `ProbeInfoTestResult` for each probe data sources.

    Raises:
      `PayloadInvalidError` if the given input is invalid.
    """
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
      raise PayloadInvalidError('The probe result payload contains unknown '
                                f'components: {unknown_comp_names}.')
    if preproc_conclusion.intrivial_error_msg:
      return DeviceProbeResultAnalyzedResult(
          intrivial_error_msg=preproc_conclusion.intrivial_error_msg,
          probe_info_test_results=None)
    pi_test_result_types = []
    for pds in probe_data_sources:
      comp_name = pds.component_name
      ps_metadata = ps_metadata_of_comp_name.get(comp_name, None)
      if ps_metadata is None:
        pi_test_result_types.append(ProbeInfoTestResult.NOT_INCLUDED)
      elif ps_metadata.fingerprint != pds.fingerprint:
        pi_test_result_types.append(ProbeInfoTestResult.LEGACY)
      elif any(c == comp_name for c in preproc_conclusion.probed_components):
        pi_test_result_types.append(ProbeInfoTestResult.PASSED)
      else:
        pi_test_result_types.append(ProbeInfoTestResult.NOT_PROBED)
    return DeviceProbeResultAnalyzedResult(
        intrivial_error_msg=None, probe_info_test_results=[
            ProbeInfoTestResult(result_type=t) for t in pi_test_result_types
        ])

  def _LookupProbeConverter(
      self, converter_name: str
  ) -> Tuple[ProbeInfoParsedResult, _IComponentProbeStatementConverter]:
    """A helper method to find the probe statement converter instance by name.

    When the target probe converter doesn't exist, the method creates and
    returns a `ProbeInfoParsedResult` message so that the caller merely
    needs to forward the error message without constructing it.

    Args:
      converter_name: A string of name of the target converter.

    Returns:
      A pair of the following:
        - An instance of `ProbeInfoParsedResult` if not found; otherwise `None`.
        - An instance of `_IComponentProbeStatementConverter` if found;
          otherwise `None`.
    """
    converter = self._converters.get(converter_name)
    if converter:
      parsed_result = None
    else:
      parsed_result = ProbeInfoParsedResult(
          result_type=ProbeInfoParsedResult.ResultType.INCOMPATIBLE_ERROR,
          general_error_msg=f'Unknown probe converter: {converter_name!r}.')
    return parsed_result, converter

  def _ConvertProbeDataSourceToProbeStatement(
      self, probe_data_source: ProbeDataSource) -> ProbeInfoArtifact:
    probe_info_parsed_result, converter = self._LookupProbeConverter(
        probe_data_source.probe_info.probe_function_name)
    if converter:
      probe_info_parsed_result, ps = converter.ParseProbeParams(
          probe_data_source.probe_info.probe_parameters, False,
          comp_name_for_probe_statement=probe_data_source.component_name)
    else:
      ps = None
    return ProbeInfoArtifact(probe_info_parsed_result, ps)

  def _PreprocessProbeResultPayload(self, probe_result_payload):
    try:
      probed_outcome = client_payload_pb2.ProbedOutcome()
      text_format.Parse(probe_result_payload, probed_outcome)
    except text_format.ParseError as e:
      raise PayloadInvalidError('Unable to load and parse the content.') from e

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
