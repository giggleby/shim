# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines the converter which converts Probe Info to HWID probe values."""

import collections
import enum
import io
import logging
import re
from typing import Any, Callable, Dict, Mapping, NamedTuple, Optional, Sequence

from cros.factory.hwid.service.appengine.data.converter import converter_types
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import rule as v3_rule
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus
_ConvertedValueTypeMapping = Mapping[
    str, Sequence[converter_types.ConvertedValueType]]


class ProbeValueMatchStatus(enum.IntEnum):
  INCONVERTIBLE = enum.auto()
  VALUE_IS_NONE = enum.auto()
  KEY_UNMATCHED = enum.auto()
  VALUE_UNMATCHED = enum.auto()
  ALL_MATCHED = enum.auto()


class ConverterConflictException(Exception):
  """Raised if converters will cause ambiguous match."""


class AVLAttrs(str, enum.Enum):
  """Holds the attr names in AVL probe info."""


class Converter:

  def __init__(self, identifier: str):
    self._identifier = identifier

  @property
  def identifier(self):
    return self._identifier

  def Match(self, comp_values: Optional[Mapping[str, Any]],
            probe_info: stubby_pb2.ProbeInfo) -> ProbeValueMatchStatus:
    """Tries to match a probe info to HWID comp values with this converter."""
    raise NotImplementedError

  def ConflictWithExisting(self, other: 'Converter') -> bool:
    """Checks if this and other converter might cause ambiguity in matching."""
    raise NotImplementedError


class ConvertedValueSpec(NamedTuple):
  name: str
  value_factory: Optional[converter_types.ConvertedValueTypeFactory] = None


def _ConvertValueWithDefaultTypeFactory(
    value: Any) -> Optional[converter_types.ConvertedValueType]:
  if isinstance(value, int):  # basic int type
    return converter_types.IntValueType(value)
  if isinstance(value, str):  # basic str type
    return converter_types.StrValueType(value)
  return None


_ACCEPTABLE_SPECIAL_CHAR_IN_REGEXP_OF_FIXED_VALUES = (
    # Accept the following because HWID doesn't use `re.VERBOSE` mode.
    '#',
    ' ',
    # Accept the following because they are normal character outside of `[]`,
    # which will not be accepted.
    '-',
    '~',
    '&',
)


def _IsCharAcceptableInRegexpOfFixedValues(c: str) -> bool:
  return (c.isalnum() or
          c in _ACCEPTABLE_SPECIAL_CHAR_IN_REGEXP_OF_FIXED_VALUES or
          re.escape(c) == c)


def _SplitRegexpOfFixedValues(pattern: str) -> Optional[Sequence[str]]:
  """Splits regexp pattern of the form "val1|val2|..." to ["val1", "val2", ...]

  Args:
    pattern: The regular expression pattern to split.

  Returns:
    A list of strings if the pattern follows the acceptable form.
    Otherwise `None`.
  """
  results = []
  curr_result_buffer = io.StringIO()

  pattern_char_iter = iter(pattern)
  for curr_char in pattern_char_iter:
    if curr_char == '\\':
      # Only accept "\<non-alnum>" that escapes <non-alnum>.
      next_char = next(pattern_char_iter, None)
      if next_char is None or next_char.isalnum():
        return None
      curr_result_buffer.write(next_char)

    elif curr_char == '|':  # reaches a splitter
      results.append(curr_result_buffer.getvalue())
      curr_result_buffer = io.StringIO()

    elif _IsCharAcceptableInRegexpOfFixedValues(curr_char):
      curr_result_buffer.write(curr_char)

    else:  # Do not accept any other regexp special character.
      return None

  results.append(curr_result_buffer.getvalue())
  return results


def _MatchValue(
    comp_value: Any,
    converted_values: Sequence[converter_types.ConvertedValueType]) -> bool:
  if isinstance(comp_value, v3_rule.Value):
    if comp_value.is_re:
      values = _SplitRegexpOfFixedValues(comp_value.raw_value)
      return values is not None and all(v in converted_values for v in values)

    comp_value = comp_value.raw_value

  return comp_value in converted_values


class FieldNameConverter(Converter):

  def __init__(self, identifier: str,
               field_name_map: Mapping[AVLAttrs, ConvertedValueSpec]):
    super().__init__(identifier)
    self._field_name_map = field_name_map

  @classmethod
  def FromFieldMap(
      cls, identifier: str, field_name_map: Mapping[AVLAttrs,
                                                    ConvertedValueSpec]
  ) -> 'FieldNameConverter':
    return cls(identifier, field_name_map)

  @property
  def field_name_map(self):
    return self._field_name_map

  def _Convert(
      self,
      probe_info: stubby_pb2.ProbeInfo) -> Optional[_ConvertedValueTypeMapping]:
    """Converts a probe info to an optional mapping for matching."""
    translated: _ConvertedValueTypeMapping = {}
    probe_info_values = collections.defaultdict(list)

    for param in probe_info.probe_parameters:
      if param.HasField('string_value'):
        probe_info_values[param.name].append(param.string_value)
      elif param.HasField('int_value'):
        probe_info_values[param.name].append(param.int_value)

    for name, translated_value_spec in self._field_name_map.items():
      values = probe_info_values.get(name)
      if values is None:
        return None
      if translated_value_spec.value_factory is not None:
        translated_values = list(
            map(translated_value_spec.value_factory, values))
      else:
        translated_values = []
        for value in values:
          translated_value = _ConvertValueWithDefaultTypeFactory(value)
          if translated_value is None:
            logging.error('Invalid value (%r).', value)
            return None
          translated_values.append(translated_value)
      translated[translated_value_spec.name] = translated_values
    return translated

  def Match(self, comp_values: Optional[Mapping[str, Any]],
            probe_info: stubby_pb2.ProbeInfo) -> ProbeValueMatchStatus:
    converted = self._Convert(probe_info)
    if not converted:
      return ProbeValueMatchStatus.INCONVERTIBLE
    if not comp_values:
      return ProbeValueMatchStatus.VALUE_IS_NONE
    if not converted.keys() <= comp_values.keys():
      return ProbeValueMatchStatus.KEY_UNMATCHED
    for converted_name, converted_values in converted.items():
      if not _MatchValue(comp_values[converted_name], converted_values):
        return ProbeValueMatchStatus.VALUE_UNMATCHED
    return ProbeValueMatchStatus.ALL_MATCHED

  def ConflictWithExisting(self, other: 'FieldNameConverter') -> bool:
    """Returns if field_name_map of both converters might create conflict."""
    return (self.field_name_map.items() <= other.field_name_map.items() or
            self.field_name_map.items() >= other.field_name_map.items())


class CollectionMatchResult(NamedTuple):
  alignment_status: _PVAlignmentStatus
  converter_identifier: Optional[str]


class ConverterCollection:

  def __init__(self, category):
    self._category = category
    self._converters: Dict[str, Converter] = {}

  @property
  def category(self) -> str:
    return self._category

  def AddConverter(self, conv: Converter):
    if conv.identifier in self._converters:
      raise ValueError(f'The converter {conv.identifier!r} already exists.')
    for existing_converter in self._converters.values():
      if conv.ConflictWithExisting(existing_converter):
        raise ConverterConflictException(
            f'Converter {conv.identifier!r} conflicts with existing converter '
            f'{existing_converter.identifier!r}.')
    self._converters[conv.identifier] = conv

  def GetConverter(self, identifier: str) -> Optional[Converter]:
    return self._converters.get(identifier)

  def Match(self, comp_values: Optional[Mapping[str, Any]],
            probe_info: stubby_pb2.ProbeInfo) -> CollectionMatchResult:
    best_match_status, best_match_identifier = (
        ProbeValueMatchStatus.INCONVERTIBLE, None)
    for converter in self._converters.values():
      match_case = converter.Match(comp_values, probe_info)
      if match_case == ProbeValueMatchStatus.ALL_MATCHED:
        best_match_status, best_match_identifier = (match_case,
                                                    converter.identifier)
        break
      if match_case > best_match_status:  # Prefer key matched to key unmatched.
        best_match_status, best_match_identifier = (match_case,
                                                    converter.identifier)
    return CollectionMatchResult(
        _PVAlignmentStatus.ALIGNED
        if best_match_status == ProbeValueMatchStatus.ALL_MATCHED else
        _PVAlignmentStatus.NOT_ALIGNED, best_match_identifier)


# TODO(clarkchung): Consider centralizing similar converters/formatters with
# the ones used in payload generator.
class HexToHexValueFormatter(converter_types.StrFormatter):

  def __init__(self, num_digits, source_has_prefix: bool = True,
               target_has_prefix: bool = True):
    self._num_digits = num_digits
    self._source_has_prefix = source_has_prefix
    self._target_has_prefix = target_has_prefix

  def __call__(self, value, *unused_args, **unused_kwargs):
    source_prefix = '0x' if self._source_has_prefix else ''
    if not re.fullmatch(
        f'{source_prefix.lower()}0*[0-9a-f]{{1,{self._num_digits}}}', value,
        flags=re.I):
      raise converter_types.StrFormatterError(
          f'Not a regular string of {self._num_digits} digits hex number.')
    target_prefix = '0x' if self._target_has_prefix else ''
    return f'{target_prefix}{int(value, 16):0{self._num_digits}x}'


class HexEncodedStrValueFormatter(converter_types.StrFormatter):

  def __init__(self, source_has_prefix: bool, encoding: str,
               fixed_num_bytes: Optional[int]):
    source_prefix = '0x' if source_has_prefix else ''
    self._skip_prefix_len = len(source_prefix)
    bytes_pattern = re.escape(str(fixed_num_bytes))
    repeat_pattern = (r'*'
                      if fixed_num_bytes is None else f'{{{bytes_pattern}}}')
    prefix_pattern = re.escape(source_prefix)
    byte_in_hex = r'([0-9a-f]{2})'
    self._value_pattern = f'{prefix_pattern}{byte_in_hex}{repeat_pattern}'
    self._encoding = encoding

  def __call__(self, value, *unused_args, **unused_kwargs):
    if not re.fullmatch(self._value_pattern, value, flags=re.I):
      raise converter_types.StrFormatterError('Not a hex-encoded string.')
    the_bytes = bytes.fromhex(value[self._skip_prefix_len:])
    try:
      return the_bytes.decode(encoding=self._encoding)
    except ValueError as ex:
      raise converter_types.StrFormatterError(
          'Unable to decode the byte string.') from ex


def MakeFixedWidthHexValueFactory(
    width: int, source_has_prefix: bool = False, target_has_prefix: bool = True
) -> Callable[..., converter_types.FormattedStrType]:
  return converter_types.FormattedStrType.CreateInstanceFactory(
      formatter_self=HexToHexValueFormatter(width, source_has_prefix,
                                            target_has_prefix))


def MakeBothNormalizedFillWidthHexValueFactory(
    fill_width: int,
    source_has_prefix: bool = False,
    target_has_prefix: bool = True,
) -> Callable[..., converter_types.FormattedStrType]:
  return converter_types.FormattedStrType.CreateInstanceFactory(
      formatter_self=HexToHexValueFormatter(fill_width, source_has_prefix,
                                            target_has_prefix),
      formatter_other=HexToHexValueFormatter(fill_width, source_has_prefix,
                                             target_has_prefix))


def MakeHexEncodedStrValueFactory(
    source_has_prefix: bool = False, encoding: str = 'ascii',
    fixed_num_bytes: Optional[int] = None
) -> Callable[..., converter_types.FormattedStrType]:
  return converter_types.FormattedStrType.CreateInstanceFactory(
      formatter_self=HexEncodedStrValueFormatter(source_has_prefix, encoding,
                                                 fixed_num_bytes))
