# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import binascii
import collections
import copy
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


_ProbeInfoArtifact = probe_info_analytics.ProbeInfoArtifact
_IBidirectionalProbeInfoConverter = analyzers.IBidirectionalProbeInfoConverter
_ParsedProbeParameter = analyzers.ParsedProbeParameter


class _ParamValueConverter:
  """Converter between probe parameters and probe statement inputs.

  It offers a bidirectional converters to translate the probe parameter value
  into the probe statement expect field input, and vice versa. The reverter
  should accept more flexible inputs than the converter because the reverter
  can be used to revert probe values and the converted probe parameters.

  Properties:
    value_type: Enum item of `_ProbeParameterValueType`.
  """

  def __init__(self, value_type_name, value_converter=None,
               value_reverter=None):
    self._probe_param_field_name = value_type_name + '_value'
    self._value_converter = value_converter or self._DummyValueConverter
    self._value_reverter = value_reverter or self._DummyValueConverter

    self.value_type = getattr(_ProbeParameterValueType, value_type_name.upper())

  def ConvertValue(self, probe_parameter: _ProbeParameter):
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

  def RevertValue(self, param_name: str, probe_val: Any) -> _ProbeParameter:
    """Reverts the given `probe_val` to a probe parameter.

    Args:
      param_name: The parameter name of the output `_ProbeParameter`.
      probe_val: The target probe statement's value or the converted probe
          parameter to revert from.

    Returns:
      A `_ProbeParameter` with name `param_name` and value `probe_val` in the
      same format as the source probe parameter.
    """
    probe_param = _ProbeParameter(name=param_name)
    probe_param_val = self._value_reverter(probe_val)

    if self._probe_param_field_name == 'int_value':
      probe_param_val = int(probe_param_val)
    elif self._probe_param_field_name == 'string_value':
      probe_param_val = str(probe_param_val)

    setattr(probe_param, self._probe_param_field_name, probe_param_val)
    return probe_param

  def NormalizeValue(self, probe_parameter: _ProbeParameter) -> _ProbeParameter:
    """Normalize the probe parameter to the same format for comparison.

    Normalize the given probe parameter by processing sequentially through the
    converter and the reverter.

    Args:
      probe_parameter: The target `_ProbeParameter` to be normalized.

    Returns:
      A normalized `_ProbeParameter`.

    Raises:
      `ValueError` if the execution of converter or reverter fails.
    """
    try:
      converted_value = self.ConvertValue(probe_parameter)
      normalized_param = self.RevertValue(probe_parameter.name, converted_value)
    except (_IncompatibleError, ValueError) as e:
      raise ValueError(
          f'Failed to normalize the probe prarameter {probe_parameter}: {e}'
      ) from e

    return normalized_param

  @classmethod
  def _DummyValueConverter(cls, value):
    return value


class _ProbeParamInput(NamedTuple):
  index: int
  raw_value: _ProbeParameter


class _IProbeStatementParam(abc.ABC):
  """Interface of parameter definitions.

  This is for `_SingleProbeFuncConverter` to convert probe info parameters to
  expected values in probe statements, and probe values to probe info
  parameters.
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
  def ConvertProbeParams(
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

  @abc.abstractmethod
  def ConvertProbeValues(
      self, probe_values: Mapping[str, str]) -> Sequence[_ProbeParameter]:
    """Converts `probe_values` to probe info parameters.

    This function tries to collect the parameters defined by each derived class
    in `probe_values`, and convert them to `_ProbeParameter`.

    Args:
      probe_values: A dictionary contains probe result, mapping parameter names
          to probe values.

    Returns:
      A list of converted `_ProbeParameter`.

    Raises:
      `_IncompatibleError`: if any of the defined parameters are not present in
          `probe_values`.
    """

  @abc.abstractmethod
  def NormalizeProbeParams(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParameter]]
  ) -> Sequence[_ProbeParameter]:
    """Returns the normalized `probe_parameters`.

    This function tries to collect and normalize the values of the parameters
    defined in `self.probe_info_param_definitions` in `probe_parameters`. This
    is used to preprocess the probe parameters before checking if the
    parameters are identical in the context of the probe tool.

    Args:
      probe_parameters: A dictionary mapping probe parameter names to lists of
          `_ProbeParameter` to be normalized.

    Returns:
      A list of normalized `_ProbeParameter`.

    Raises:
      `ValueError` if normalization of any of the probe parameters fails.
    """


class _SingleProbeStatementParam(_IProbeStatementParam):
  """Holds a one-to-one parameter for `_SingleProbeFuncConverter`.

  This can be used either to map one probe info parameter to one probe
  statement parameter for `_SingleProbeFuncConverter`, or as a sub-parameter
  for `_ConcatProbeStatementParam`.
  """

  def __init__(self, param_name: str, description: str,
               value_converter: _ParamValueConverter,
               probe_statement_param_name: Optional[str] = None,
               ps_gen_checker: Optional[Callable] = None):
    probe_statement_param_name = probe_statement_param_name or param_name
    self._param_name = param_name
    self._description = description
    self._value_converter = value_converter
    self._ps_gen_checker = ps_gen_checker
    self._is_informational = ps_gen_checker is None
    self._probe_statement_param_name = probe_statement_param_name

  @property
  def probe_info_param_definitions(
      self) -> Mapping[str, _ProbeParameterDefinition]:
    """See base class."""
    definition = _ProbeParameterDefinition(
        name=self._param_name, description=self._description,
        value_type=self._value_converter.value_type)
    return {
        self._param_name: definition
    }

  @property
  def probe_statement_param_name(self) -> Optional[str]:
    """See base class."""
    return None if self._is_informational else self._probe_statement_param_name

  def ConvertProbeParams(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParamInput]]
  ) -> Tuple[Sequence[Any], Sequence[_ProbeParameterSuggestion]]:
    """See base class."""
    converted_values = []
    suggestions = []
    for probe_parameter in probe_parameters.get(self._param_name, []):
      try:
        value = self._value_converter.ConvertValue(probe_parameter.raw_value)
        if not self._is_informational:
          # Attempt to trigger the probe statement generator directly to see if
          # it's convertible.
          self._ps_gen_checker(value)
        converted_values.append(value)
      except _IncompatibleError as e:
        raise _IncompatibleError(
            f'Got improper probe parameter {self._param_name!r}: '
            f'{e}.') from e
      except (TypeError, ValueError) as e:
        suggestions.append(
            _ProbeParameterSuggestion(index=probe_parameter.index, hint=str(e)))

    return converted_values, suggestions

  def ConvertProbeValues(
      self, probe_values: Mapping[str, str]) -> Sequence[_ProbeParameter]:
    """See base class."""
    if self._is_informational:
      return []
    return self.ConvertProbeValuesWithInformational(probe_values)

  def ConvertProbeValuesWithInformational(
      self, probe_values: Mapping[str, str]) -> Sequence[_ProbeParameter]:
    if self._probe_statement_param_name not in probe_values:
      raise _IncompatibleError(
          f'Parameter "{self._probe_statement_param_name}" does not exist in '
          f'the probe result')

    probe_val = probe_values[self._probe_statement_param_name]
    converted_probe_val = self._value_converter.RevertValue(
        self._param_name, probe_val)
    return [converted_probe_val]

  def NormalizeProbeParams(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParameter]]
  ) -> Sequence[_ProbeParameter]:
    """See base class."""
    normalized_params = [
        self._value_converter.NormalizeValue(probe_parameter)
        for probe_parameter in probe_parameters.get(self._param_name, [])
    ]
    return normalized_params


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

  def ConvertProbeParams(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParamInput]]
  ) -> Tuple[List[Any], Sequence[_ProbeParameterSuggestion]]:
    """See base class."""
    converted_values = collections.OrderedDict()
    suggestions = []
    for probe_info_param in self._probe_info_params:
      param_name = next(iter(probe_info_param.probe_info_param_definitions))
      converted_values[param_name] = []
      for probe_parameter in probe_parameters[param_name]:
        sub_values, sub_suggestions = probe_info_param.ConvertProbeParams(
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

  def ConvertProbeValues(
      self, probe_values: Mapping[str, str]) -> Sequence[_ProbeParameter]:
    """See base class."""
    if self._is_informational:
      return []

    if self._name not in probe_values:
      raise _IncompatibleError(
          f'Parameter "{self._name}" does not exist in the probe result')

    converted_probe_vals = []
    probe_val = probe_values[self._name]
    for probe_info_param in self._probe_info_params:
      param_name = next(iter(probe_info_param.probe_info_param_definitions))
      sub_converted_vals = probe_info_param.ConvertProbeValuesWithInformational(
          {param_name: probe_val})
      converted_probe_vals.extend(sub_converted_vals)

    return converted_probe_vals

  def NormalizeProbeParams(
      self, probe_parameters: Mapping[str, Sequence[_ProbeParameter]]
  ) -> Sequence[_ProbeParameter]:
    normalized_params = []
    for probe_info_param in self._probe_info_params:
      normalized_params.extend(
          probe_info_param.NormalizeProbeParams(probe_parameters))
    return normalized_params


class _IProbeParamSpec(abc.ABC):
  """Interface of probe parameter spec.

  This is for `_IBidirectionalProbeInfoConverter` to define the relationship
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
               value_converter: Optional[_ParamValueConverter] = None,
               probe_statement_param_name: Optional[str] = None):
    self._param_name = param_name
    self._description = description
    self._value_converter = value_converter
    self._probe_statement_param_name = probe_statement_param_name or param_name

  def BuildProbeStatementParam(
      self,
      output_fields: Mapping[str, probe_config_types.OutputFieldDefinition],
  ) -> _IProbeStatementParam:
    """See base class."""
    output_field = output_fields[self._probe_statement_param_name]
    return _SingleProbeStatementParam(
        self._param_name, self._description or output_field.description,
        (self._value_converter or
         self._DEFAULT_VALUE_TYPE_MAPPING[output_field.value_type]),
        self._probe_statement_param_name,
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
    probe_statement_param_name = None
    ps_gen_checker = None
    return _SingleProbeStatementParam(
        self._param_name, self._description, self._value_converter,
        probe_statement_param_name, ps_gen_checker)


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


def _ToProbeParamInputs(
    probe_params: Sequence[_ProbeParameter]
) -> Mapping[str, Sequence[_ProbeParamInput]]:
  probe_param_inputs = collections.defaultdict(list)

  for index, probe_param in enumerate(probe_params):
    probe_param_inputs[probe_param.name].append(
        _ProbeParamInput(index, probe_param))

  return probe_param_inputs


class _SingleProbeFuncConverter(_IBidirectionalProbeInfoConverter):
  """Converts probe info into a statement of one single probe function call."""

  _DEFAULT_VALUE_TYPE_MAPPING = {
      probe_config_types.ValueType.INT: _ParamValueConverter('int'),
      probe_config_types.ValueType.STRING: _ParamValueConverter('string'),
  }

  def __init__(self, ps_generator: probe_config_types.ProbeStatementDefinition,
               probe_function_name: str, converter_name: Optional[str] = None,
               probe_params: Optional[Sequence[_IProbeParamSpec]] = None,
               probe_function_argument: Optional[Mapping[str, Any]] = None):
    self._ps_generator = ps_generator
    self._probe_func_def = self._ps_generator.probe_functions[
        probe_function_name]
    self._probe_function_argument = probe_function_argument
    output_fields: Mapping[str, probe_config_types.OutputFieldDefinition] = {
        f.name: f
        for f in self._probe_func_def.output_fields
    }

    if probe_params is None:
      probe_params = [_ProbeFunctionParam(n) for n in output_fields]

    self._probe_params = [
        spec.BuildProbeStatementParam(output_fields) for spec in probe_params
    ]

    self._name = converter_name or (
        f'{self._ps_generator.category_name}.{self._probe_func_def.name}')

  @classmethod
  def FromDefaultRuntimeProbeStatementGenerator(
      cls, runtime_probe_category_name: str, runtime_probe_func_name: str,
      converter_name: Optional[str] = None,
      probe_params: Optional[Sequence[_IProbeParamSpec]] = None,
      probe_function_argument: Optional[Mapping[str, Any]] = None):
    ps_generator = probe_config_definition.GetProbeStatementDefinition(
        runtime_probe_category_name)
    return cls(ps_generator, runtime_probe_func_name,
               converter_name=converter_name, probe_params=probe_params,
               probe_function_argument=probe_function_argument)

  @property
  def probe_params(self) -> Sequence[_IProbeStatementParam]:
    return self._probe_params

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

  def ParseProbeParamInputs(
      self, probe_param_inputs: Mapping[str, Sequence[_ProbeParamInput]],
      allow_missing_params: bool, comp_name_for_probe_statement: Optional[str]
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """See `ParseProbeParams()` for more details."""
    probe_param_errors = []
    expected_values_of_field = collections.defaultdict(list)

    try:
      expected_values_of_field, probe_param_errors = (
          self._ConvertProbeParamInputsToProbeStatementValues(
              probe_param_inputs, allow_missing_params))
    except _IncompatibleError as e:
      return _ProbeInfoArtifact(
          _ProbeInfoParsedResult(
              result_type=_ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
              general_error_msg=str(e)), None)

    if probe_param_errors:
      return _ProbeInfoArtifact(
          _ProbeInfoParsedResult(
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
            ps_expected_fields,
            probe_function_argument=self._probe_function_argument)
      except Exception as e:
        return _ProbeInfoArtifact(
            _ProbeInfoParsedResult(
                result_type=_ProbeInfoParsedResult.UNKNOWN_ERROR,
                general_error_msg=str(e)), None)
    return _ProbeInfoArtifact(
        _ProbeInfoParsedResult(result_type=_ProbeInfoParsedResult.PASSED), [ps])

  def ParseProbeParams(
      self, probe_params: Sequence[_ProbeParameter], allow_missing_params: bool,
      comp_name_for_probe_statement=None
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    return self.ParseProbeParamInputs(
        _ToProbeParamInputs(probe_params), allow_missing_params,
        comp_name_for_probe_statement)

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
      values, suggestions = probe_param.ConvertProbeParams(probe_param_inputs)
      if probe_param.probe_statement_param_name:
        expected_values_of_field[
            probe_param.probe_statement_param_name] = values

      for suggestion in suggestions:
        probe_param_errors.append(suggestion)

    return expected_values_of_field, probe_param_errors

  def ParseProbeResult(
      self, probe_result: Mapping[str, Sequence[Mapping[str, str]]]
  ) -> Sequence[_ParsedProbeParameter]:
    """See base class."""
    category_probe_result = probe_result.get(self._ps_generator.category_name,
                                             [])
    parsed_results = []
    for probe_values in category_probe_result:
      try:
        res = []
        for param in self.probe_params:
          converted_values = param.ConvertProbeValues(probe_values)
          res.extend([
              _ParsedProbeParameter(self._ps_generator.category_name, val)
              for val in converted_values
          ])
        parsed_results.extend(res)
      except _IncompatibleError:
        # Some probe functions have the same component category (e.g. usb_camera
        # and mipi_camera), so just skip the probe result if any parameters are
        # not found in the probe result.
        pass

    return parsed_results

  def GetNormalizedProbeParams(
      self,
      probe_params: Sequence[_ProbeParameter]) -> Sequence[_ProbeParameter]:
    """See base class."""
    probe_parameters = collections.defaultdict(list)
    for probe_param in probe_params:
      probe_parameters[probe_param.name].append(probe_param)

    normalized_params = []
    for probe_param in self._probe_params:
      for param in probe_param.NormalizeProbeParams(probe_parameters):
        normalized_params.append(param)

    return normalized_params


def _AggregrateProbeInfoParsedResults(
    sources: Sequence[_ProbeInfoParsedResult]) -> _ProbeInfoParsedResult:
  aggregated_result = _ProbeInfoParsedResult(
      general_error_msg=' '.join(
          s.general_error_msg for s in sources if s.general_error_msg),
      probe_parameter_errors=itertools.chain.from_iterable(
          s.probe_parameter_errors for s in sources))

  for error_result_type in (_ProbeInfoParsedResult.UNKNOWN_ERROR,
                            _ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
                            _ProbeInfoParsedResult.PROBE_PARAMETER_ERROR):
    if any(s.result_type == error_result_type for s in sources):
      aggregated_result.result_type = error_result_type
      return aggregated_result
  aggregated_result.result_type = (
      _ProbeInfoParsedResult.UNKNOWN_ERROR if any(
          s.result_type != _ProbeInfoParsedResult.PASSED for s in sources) else
      _ProbeInfoParsedResult.PASSED)
  return aggregated_result


class _MultiProbeFuncConverter(_IBidirectionalProbeInfoConverter):
  """Converts a probe info into multiple component probe statements.

  It can convert one single probe info into a list of component probe
  statements, each identifies one single part of the component.  This
  conversion enables probe statement generation for components that
  show multiple functionalities from software's point of view.
  """

  def __init__(self, name: str, description: str,
               sub_converters: Mapping[str, _SingleProbeFuncConverter]):
    self._name = name
    self._description = description
    self._sub_converters = sub_converters

  def GetName(self) -> str:
    """See base class."""
    return self._name

  def GenerateDefinition(self) -> probe_info_analytics.ProbeFunctionDefinition:
    """See base class."""
    ret = probe_info_analytics.ProbeFunctionDefinition(
        name=self._name, description=self._description)
    for sub_converter in self._sub_converters.values():
      ret.parameter_definitions.extend(
          sub_converter.GenerateDefinition().parameter_definitions)
    return ret

  def ParseProbeParamInputs(
      self, probe_param_inputs: Mapping[str, Sequence[_ProbeParamInput]],
      allow_missing_params: bool, comp_name_for_probe_statement: Optional[str]
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """See `ParseProbeParams()` for more details."""
    remaining_probe_param_inputs = copy.deepcopy(probe_param_inputs)

    sub_probe_info_artifacts = []
    for sub_converter_name, sub_converter in self._sub_converters.items():
      probe_param_inputs = {}
      for param in sub_converter.probe_params:
        for param_name in param.probe_info_param_definitions:
          if param_name in remaining_probe_param_inputs:
            probe_param_inputs[param_name] = remaining_probe_param_inputs.pop(
                param_name)
      sub_comp_name = (f'{comp_name_for_probe_statement}-{sub_converter_name}'
                       if comp_name_for_probe_statement else None)
      sub_probe_info_artifacts.append(
          sub_converter.ParseProbeParamInputs(
              probe_param_inputs, allow_missing_params, sub_comp_name))

    all_parsed_results = [
        r.probe_info_parsed_result for r in sub_probe_info_artifacts
    ]
    if remaining_probe_param_inputs:
      error_msg = ('Unknown probe parameters: '
                   f'{", ".join(remaining_probe_param_inputs)}.')
      all_parsed_results.append(
          _ProbeInfoParsedResult(
              result_type=_ProbeInfoParsedResult.INCOMPATIBLE_ERROR,
              general_error_msg=error_msg))

    aggregated_parsed_result = _AggregrateProbeInfoParsedResults(
        all_parsed_results)
    if (aggregated_parsed_result.result_type != _ProbeInfoParsedResult.PASSED or
        not comp_name_for_probe_statement):
      return _ProbeInfoArtifact(aggregated_parsed_result, None)

    return _ProbeInfoArtifact(
        aggregated_parsed_result,
        list(
            itertools.chain.from_iterable(
                a.output for a in sub_probe_info_artifacts)))

  def ParseProbeParams(
      self, probe_params: Sequence[_ProbeParameter], allow_missing_params: bool,
      comp_name_for_probe_statement=None
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    return self.ParseProbeParamInputs(
        _ToProbeParamInputs(probe_params), allow_missing_params,
        comp_name_for_probe_statement=comp_name_for_probe_statement)

  def ParseProbeResult(
      self, probe_result: Mapping[str, Sequence[Mapping[str, str]]]
  ) -> Sequence[_ParsedProbeParameter]:
    """See base class."""
    return [
        parsed_result for converter in self._sub_converters.values()
        for parsed_result in converter.ParseProbeResult(probe_result)
    ]

  def GetNormalizedProbeParams(
      self,
      probe_params: Sequence[_ProbeParameter]) -> Sequence[_ProbeParameter]:
    """See base class."""
    normalized_params = []
    for converter in self._sub_converters.values():
      for param in converter.GetNormalizedProbeParams(probe_params):
        normalized_params.append(param)

    return normalized_params


def _RemoveHexPrefixAndCapitalize(value: str) -> str:
  if not value.lower().startswith('0x'):
    raise ValueError('Expect hex value to start with "0x" or "0X".')
  return value[2:].upper()


def _RemoveHexPrefixAndLowerize(value: str) -> str:
  if not value.lower().startswith('0x'):
    raise ValueError('Expect hex value to start with "0x" or "0X".')
  return value[2:].lower()


def _AddHexPrefixIfNotExistAndLowerize(value: str) -> str:
  lowerized_val = value.lower()
  if not lowerized_val.startswith('0x'):
    return '0x' + lowerized_val
  return lowerized_val


def _ResizeHexStr(length: int, lowerize=False, capitalize=False,
                  prefix=True) -> Callable:
  """Creates a function to resize the input hex string.

  The returned function gets the last `length` characters of the input hex
  string. If `length` is larger than the length of input string, pad the string
  with zeros at the beginning until the length of the string is equal to
  `length`.

  Args:
    length: The expected hex-string length after conversion.
    lowerize: Lowerize the output string if the value is True.
    capitalize: Capitalize the output string if the value is True.
    prefix: If the value is True, add `0x` prefix to the output string if there
        is no `0x` prefix. Otherwise, remove the prefix if there is one.

  Returns:
    The created function with a string as the input and a fixed size string as
    the output.
  """

  if lowerize and capitalize:
    raise ValueError('Only one of lowerize or capitalize can be set to True.')

  def _ResizeFunc(value: Any) -> str:
    val_length = min(len(value) - 2, length)
    res = f'{value[-val_length:].zfill(length)}'.lower()

    if prefix and not res.startswith('0x'):
      res = '0x' + res
    elif not prefix and res.startswith('0x'):
      res = res[2:]

    if lowerize:
      return res.lower()
    if capitalize:
      return res.capitalize()

    return res

  return _ResizeFunc


def _CapitalizeHexValueWithoutPrefix(value: str) -> str:
  if value.lower().startswith('0x'):
    raise ValueError('Expect hex value not to start with "0x" or "0X".')
  return value.upper()


def _MipiVIDReverter(value: Any) -> str:
  if not (isinstance(value, str) and len(value) in [2, 6]):
    raise ValueError('Expect string value with a length of 2 or 6')

  if len(value) == 2:
    return value

  return value[:2]


def _MipiPIDReverter(value: Any) -> str:
  if not (isinstance(value, str) and len(value) in [4, 6]):
    raise ValueError('Expect string value with a length of 4 or 6')

  if len(value) == 4:
    return '0x' + value.lower()

  return '0x' + value[2:].lower()


def _StringToRegexpOrString(value):
  PREFIX = '!re '
  if value.startswith(PREFIX):
    return re.compile(value.lstrip(PREFIX))
  return value


def _BuildCPUProbeStatementConverter() -> _IBidirectionalProbeInfoConverter:
  builder = probe_config_types.ProbeStatementDefinitionBuilder('cpu')
  builder.AddProbeFunction(
      'generic_cpu', 'A currently non-existent runtime probe function for CPU.')
  builder.AddStrOutputField('identifier', 'Model name on x86, chip-id on ARM.')
  return _SingleProbeFuncConverter(builder.Build(), 'generic_cpu')


def BuildTouchscreenModuleConverter() -> _IBidirectionalProbeInfoConverter:
  # TODO(b/293377003): Confirm the reverter once this is launched.
  sub_converters = {
      'touchscreen_controller':
          _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
              'touchscreen', 'input_device', probe_params=[
                  _ProbeFunctionParam(
                      'module_vendor_id', value_converter=_ParamValueConverter(
                          'string', _CapitalizeHexValueWithoutPrefix,
                          _CapitalizeHexValueWithoutPrefix),
                      probe_statement_param_name='vendor'),
                  _ProbeFunctionParam(
                      'module_product_id', value_converter=_ParamValueConverter(
                          'string', _CapitalizeHexValueWithoutPrefix,
                          _CapitalizeHexValueWithoutPrefix),
                      probe_statement_param_name='product'),
              ], probe_function_argument={'device_type': 'touchscreen'}),
      'edid_panel':
          _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
              'display_panel', 'edid', probe_params=[
                  _ProbeFunctionParam('panel_edid_vendor_code',
                                      probe_statement_param_name='vendor'),
                  _ProbeFunctionParam(
                      'panel_edid_product_id',
                      value_converter=_ParamValueConverter(
                          'string', _CapitalizeHexValueWithoutPrefix,
                          _CapitalizeHexValueWithoutPrefix),
                      probe_statement_param_name='product_id'),
              ]),
  }
  return _MultiProbeFuncConverter(
      'touchscreen_module.generic_input_device_and_edid',
      'Probe statement converter for touchscreen modules with eDP displays.',
      sub_converters)


_MMC_BASIC_PARAMS = (
    _ProbeFunctionParam(
        'mmc_manfid', value_converter=_ParamValueConverter(
            'string', _RemoveHexPrefixAndCapitalize,
            _ResizeHexStr(2, lowerize=True))),
    _ProbeFunctionParam(
        'mmc_name', value_converter=_ParamValueConverter(
            'string', lambda hex_with_prefix: bytes.fromhex(hex_with_prefix[2:])
            .decode('ascii'), lambda str_val: '0x' + binascii.hexlify(
                str_val.encode('ascii')).decode('ascii').lower())),
)


class MMCWithBridgeProbeStatementConverter(_IBidirectionalProbeInfoConverter):

  _NAME = 'emmc_pcie_assembly.generic'
  _DESCRIPTION = (
      'The probe statement converter for eMMC + eMMC-PCIe bridge assemblies.')
  _NVME_MODEL = 'nvme_model'

  _INVISIBLE_EMMC_TAG = '(to_be_removed)'

  def __init__(self):

    def _BuildPCIeParam(param_name, probe_statement_param_name):
      return _ProbeFunctionParam(
          param_name, value_converter=_ParamValueConverter(
              'string', _RemoveHexPrefixAndCapitalize,
              _AddHexPrefixIfNotExistAndLowerize),
          probe_statement_param_name=probe_statement_param_name)

    emmc_converter = (
        _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
            'storage', 'mmc_storage', probe_params=_MMC_BASIC_PARAMS))
    mmc_host_converter = (
        _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
            'mmc_host', 'mmc_host', probe_params=[
                _BuildPCIeParam('bridge_pcie_vendor', 'pci_vendor_id'),
                _BuildPCIeParam('bridge_pcie_device', 'pci_device_id'),
                _BuildPCIeParam('bridge_pcie_class', 'pci_class'),
            ], probe_function_argument={'is_emmc_attached': True}))
    self._nvme_converter = (
        _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
            'storage', 'nvme_storage', probe_params=[
                _BuildPCIeParam('bridge_pcie_vendor', 'pci_vendor'),
                _BuildPCIeParam('bridge_pcie_device', 'pci_device'),
                _BuildPCIeParam('bridge_pcie_class', 'pci_class'),
                _ProbeFunctionParam(self._NVME_MODEL),
            ]))
    self._emmc_and_host_converter = _MultiProbeFuncConverter(
        self._NAME, self._DESCRIPTION, {
            'storage': emmc_converter,
            'bridge': mmc_host_converter,
        })
    self._invisible_emmc_and_nvme_converter = _MultiProbeFuncConverter(
        self._NAME, self._DESCRIPTION, {
            self._INVISIBLE_EMMC_TAG: emmc_converter,
            'assembly': self._nvme_converter,
        })

  def GetName(self) -> str:
    """See base class."""
    return self._NAME

  def GenerateDefinition(self) -> probe_info_analytics.ProbeFunctionDefinition:
    """See base class."""
    ret = probe_info_analytics.ProbeFunctionDefinition(
        name=self._NAME, description=self._DESCRIPTION)
    appended_param_names = set()
    for p in self._emmc_and_host_converter.GenerateDefinition(
    ).parameter_definitions:
      ret.parameter_definitions.append(p)
      appended_param_names.add(p.name)
    for p in self._invisible_emmc_and_nvme_converter.GenerateDefinition(
    ).parameter_definitions:
      if p.name in appended_param_names:
        continue
      ret.parameter_definitions.append(p)
      ret.parameter_definitions[-1].description += (
          ' (if the bridge component contains a NVMe controller)')
    return ret

  def ParseProbeParams(
      self, probe_params: Sequence[_ProbeParameter], allow_missing_params: bool,
      comp_name_for_probe_statement=None
  ) -> _ProbeInfoArtifact[Sequence[probe_config_types.ComponentProbeStatement]]:
    """See base class."""
    probe_param_inputs = _ToProbeParamInputs(probe_params)

    # Treat "empty NVMe model string" as not exist.
    nvme_model_params = probe_param_inputs.pop(self._NVME_MODEL, [])
    for nvme_model_param in nvme_model_params:
      if (nvme_model_param.raw_value.WhichOneof('value') != 'string_value' or
          nvme_model_param.raw_value.string_value):
        probe_param_inputs[self._NVME_MODEL].append(nvme_model_param)

    if self._NVME_MODEL not in probe_param_inputs:
      return self._emmc_and_host_converter.ParseProbeParamInputs(
          probe_param_inputs, allow_missing_params,
          comp_name_for_probe_statement=comp_name_for_probe_statement)

    result = self._invisible_emmc_and_nvme_converter.ParseProbeParamInputs(
        probe_param_inputs, allow_missing_params,
        comp_name_for_probe_statement=comp_name_for_probe_statement)
    if not result.output:
      return result
    return _ProbeInfoArtifact(result.probe_info_parsed_result, [
        cps for cps in result.output
        if self._INVISIBLE_EMMC_TAG not in cps.component_name
    ])

  def ParseProbeResult(
      self, probe_result: Mapping[str, Sequence[Mapping[str, str]]]
  ) -> Sequence[_ParsedProbeParameter]:
    """See base class."""
    for storage_res in probe_result.get('storage', []):
      if self._NVME_MODEL in storage_res:
        break
    else:
      return self._emmc_and_host_converter.ParseProbeResult(probe_result)

    return self._nvme_converter.ParseProbeResult(probe_result)

  def GetNormalizedProbeParams(
      self,
      probe_params: Sequence[_ProbeParameter]) -> Sequence[_ProbeParameter]:
    """See base class."""
    processed_param_names = set()
    normalized_params = []
    for converter in [
        self._emmc_and_host_converter, self._invisible_emmc_and_nvme_converter
    ]:
      processed_by_this_converter = set()
      for param in converter.GetNormalizedProbeParams(probe_params):
        if param.name in processed_param_names:
          continue

        processed_by_this_converter.add(param.name)
        normalized_params.append(param)

      processed_param_names.update(processed_by_this_converter)

    return normalized_params


def GetAllConverters() -> Sequence[analyzers._IBidirectionalProbeInfoConverter]:
  # TODO(yhong): Separate the data piece out the code logic.
  return [
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'audio_codec', 'audio_codec', probe_params=[
              _ProbeFunctionParam('name'),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'battery', 'generic_battery', probe_params=[
              _ProbeFunctionParam('manufacturer'),
              _ProbeFunctionParam('model_name'),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'camera', 'mipi_camera', probe_params=[
              _ConcatParam('mipi_module_id', [
                  _SingleProbeStatementParam(
                      'module_vid', 'The camera module vendor ID.',
                      _ParamValueConverter('string',
                                           value_reverter=_MipiVIDReverter)),
                  _SingleProbeStatementParam(
                      'module_pid', 'The camera module product ID.',
                      _ParamValueConverter('string',
                                           _RemoveHexPrefixAndLowerize,
                                           _MipiPIDReverter))
              ]),
              _ConcatParam('mipi_sensor_id', [
                  _SingleProbeStatementParam(
                      'sensor_vid', 'The camera sensor vendor ID.',
                      _ParamValueConverter('string',
                                           value_reverter=_MipiVIDReverter)),
                  _SingleProbeStatementParam(
                      'sensor_pid', 'The camera sensor product ID.',
                      _ParamValueConverter('string',
                                           _RemoveHexPrefixAndLowerize,
                                           _MipiPIDReverter))
              ])
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'camera', 'usb_camera', probe_params=[
              _ProbeFunctionParam(
                  'usb_vendor_id', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix,
                      _CapitalizeHexValueWithoutPrefix)),
              _ProbeFunctionParam(
                  'usb_product_id', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix,
                      _CapitalizeHexValueWithoutPrefix)),
              _ProbeFunctionParam(
                  'usb_bcd_device', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix,
                      _CapitalizeHexValueWithoutPrefix)),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'display_panel', 'edid', probe_params=[
              _ProbeFunctionParam(
                  'product_id', value_converter=_ParamValueConverter(
                      'string', _CapitalizeHexValueWithoutPrefix,
                      _CapitalizeHexValueWithoutPrefix)),
              _ProbeFunctionParam('vendor'),
              _InformationalParam('width', 'The width of display panel.',
                                  _ParamValueConverter('int')),
              _InformationalParam('height', 'The height of display panel.',
                                  _ParamValueConverter('int')),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'dram', 'memory', probe_params=[
              _ProbeFunctionParam('part'),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'mmc_host', 'mmc_host',
          converter_name='emmc_pcie_storage_bridge.mmc_host', probe_params=[
              _ProbeFunctionParam(
                  'pci_vendor_id', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _AddHexPrefixIfNotExistAndLowerize)),
              _ProbeFunctionParam(
                  'pci_device_id', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _AddHexPrefixIfNotExistAndLowerize)),
              _ProbeFunctionParam(
                  'pci_class', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _AddHexPrefixIfNotExistAndLowerize)),
          ], probe_function_argument={'is_emmc_attached': True}),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'storage', 'mmc_storage', probe_params=[
              *_MMC_BASIC_PARAMS,
              _ProbeFunctionParam(
                  'mmc_prv', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _ResizeHexStr(2, lowerize=True))),
              _InformationalParam('size_in_gb', 'The storage size in GB.',
                                  _ParamValueConverter('int')),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'storage', 'nvme_storage', probe_params=[
              _ProbeFunctionParam(
                  'pci_vendor', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _AddHexPrefixIfNotExistAndLowerize)),
              _ProbeFunctionParam(
                  'pci_device', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _AddHexPrefixIfNotExistAndLowerize)),
              _ProbeFunctionParam(
                  'pci_class', value_converter=_ParamValueConverter(
                      'string', _RemoveHexPrefixAndCapitalize,
                      _AddHexPrefixIfNotExistAndLowerize)),
              _ProbeFunctionParam('nvme_model'),
              _InformationalParam('size_in_gb', 'The storage size in GB.',
                                  _ParamValueConverter('int')),
          ]),
      _SingleProbeFuncConverter.FromDefaultRuntimeProbeStatementGenerator(
          'storage', 'ufs_storage', probe_params=[
              _ProbeFunctionParam('ufs_vendor'),
              _ProbeFunctionParam('ufs_model'),
              _InformationalParam('size_in_gb', 'The storage size in GB.',
                                  _ParamValueConverter('int')),
          ]),
      _BuildCPUProbeStatementConverter(),
      BuildTouchscreenModuleConverter(),
      MMCWithBridgeProbeStatementConverter(),
  ]
