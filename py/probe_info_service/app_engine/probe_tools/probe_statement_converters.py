# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import collections
import itertools
import re
from typing import Any, Callable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from cros.factory.probe.runtime_probe import probe_config_definition
from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine.probe_tools import analyzers


_ProbeParameterDefinition = probe_info_analytics.ProbeParameterDefinition
_ProbeParameterValueType = probe_info_analytics.ProbeParameterValueType
_ProbeParameter = probe_info_analytics.ProbeParameter
_ProbeInfoParsedResult = probe_info_analytics.ProbeInfoParsedResult
_ProbeParameterSuggestion = probe_info_analytics.ProbeParameterSuggestion


class _IncompatibleError(Exception):
  """Raised when the given input is incompatible with the probe tool."""


_IComponentProbeStatementConverter = analyzers.IComponentProbeStatementConverter


class _ParamValueConverter:
  """Converter for the input of the probe statement from the probe parameter.

  Properties:
    value_type: Enum item of `_ProbeParameterValueType`.
  """

  def __init__(self, value_type_name, value_converter=None):
    self._probe_param_field_name = value_type_name + '_value'
    self._value_converter = value_converter or self._DummyValueConverter

    self.value_type = getattr(_ProbeParameterValueType, value_type_name.upper())

  def ConvertValue(self, probe_parameter):
    """Converts the given probe parameter to the probe statement's value.

    Args:
      probe_parameter: The target `_ProbeParameter` to convert from.

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
  raw_value: _ProbeParameter


class _IProbeStatementParam(abc.ABC):
  """Interface of parameter definitions.

  This is for `_SingleProbeFuncConverter` to convert probe info parameters to
  expected values in probe statements.
  """

  @property
  @abc.abstractmethod
  def probe_info_param_definitions(
      self) -> Mapping[str, _ProbeParameterDefinition]:
    """All related probe info parameter definitions."""

  @property
  @abc.abstractmethod
  def probe_statement_param_name(self) -> Optional[str]:
    """The parameter name used in the probe statement."""

  @abc.abstractmethod
  def ConvertValues(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParamInput]]
  ) -> Tuple[Sequence[Any], Sequence[_ProbeParameterSuggestion]]:
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
        2. A `_ProbeParameterSuggestion` list containing parameters that were
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
      self) -> Mapping[str, _ProbeParameterDefinition]:
    """See base class."""
    definition = _ProbeParameterDefinition(
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
  ) -> Tuple[Sequence[Any], Sequence[_ProbeParameterSuggestion]]:
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
            _ProbeParameterSuggestion(index=probe_parameter.index, hint=str(e)))

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
      self) -> Mapping[str, _ProbeParameterDefinition]:
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
  ) -> Tuple[List[Any], Sequence[_ProbeParameterSuggestion]]:
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
            _ProbeParameterSuggestion(index=value.index, hint=str(e))
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

  def GenerateDefinition(self) -> probe_info_analytics.ProbeFunctionDefinition:
    """See base class."""
    ret = probe_info_analytics.ProbeFunctionDefinition(
        name=self._name, description=self._probe_func_def.description)
    ret.parameter_definitions.extend(
        definition for probe_param in self._probe_params
        for definition in probe_param.probe_info_param_definitions.values())

    return ret

  def ParseProbeParams(
      self, probe_params: Sequence[_ProbeParameter], allow_missing_params: bool,
      comp_name_for_probe_statement=None
  ) -> Tuple[_ProbeInfoParsedResult,
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
      return (_ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
          general_error_msg=str(e)), None)

    if probe_param_errors:
      return (_ProbeInfoParsedResult(
          result_type=_ProbeInfoParsedResult.PROBE_PARAMETER_ERROR,
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
        return (_ProbeInfoParsedResult(
            result_type=_ProbeInfoParsedResult.UNKNOWN_ERROR,
            general_error_msg=str(e)), None)
    return _ProbeInfoParsedResult(result_type=_ProbeInfoParsedResult.PASSED), ps

  def _ConvertProbeParamInputsToProbeStatementValues(
      self, probe_param_inputs: Mapping[str, Sequence[_ProbeParamInput]],
      allow_missing_params: bool
  ) -> Tuple[Mapping[str, Any], Sequence[_ProbeParameterSuggestion]]:
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
        2. A `_ProbeParameterSuggestion` list containing parameters that were
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


def _StringToRegexpOrString(value):
  PREFIX = '!re '
  if value.startswith(PREFIX):
    return re.compile(value.lstrip(PREFIX))
  return value


def _BuildCPUProbeStatementConverter() -> _IComponentProbeStatementConverter:
  builder = probe_config_types.ProbeStatementDefinitionBuilder('cpu')
  builder.AddProbeFunction(
      'generic_cpu', 'A currently non-existent runtime probe function for CPU.')
  builder.AddStrOutputField('identifier', 'Model name on x86, chip-id on ARM.')
  return _SingleProbeFuncConverter(builder.Build(), 'generic_cpu')


def GetAllConverters() -> Sequence[analyzers.IComponentProbeStatementConverter]:
  # TODO(yhong): Separate the data piece out the code logic.
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
  ]
