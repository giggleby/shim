# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines the converter which converts Probe Info to HWID probe values."""

import enum
from typing import Any, Dict, Mapping, NamedTuple, Optional, Union

from cros.factory.hwid.service.appengine.data.converter import converter_types
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module

# Shorter identifiers.
_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus
_ConvertedValues = Dict[str, Union[str, converter_types.IntValueType]]


class ProbeValueMatchStatus(enum.IntEnum):
  INCONVERTIBLE = enum.auto()
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

  def Convert(self,
              probe_info: stubby_pb2.ProbeInfo) -> Optional[_ConvertedValues]:
    """Converts a probe info to an optional mapping for matching."""
    raise NotImplementedError

  def Match(self, comp_values: Optional[Mapping[str, Any]],
            probe_info: stubby_pb2.ProbeInfo) -> ProbeValueMatchStatus:
    """Tries to match a probe info to HWID comp values with this converter."""
    raise NotImplementedError

  def ConflictWithExisting(self, other: 'Converter') -> bool:
    """Checks if this and other converter might cause ambiguity in matching."""
    raise NotImplementedError


class FieldNameConverter(Converter):

  def __init__(self, identifier: str, field_name_map: Mapping[AVLAttrs, str]):
    super().__init__(identifier)
    self._field_name_map = field_name_map

  @classmethod
  def FromFieldMap(
      cls, identifier: str,
      field_name_map: Mapping[AVLAttrs, str]) -> 'FieldNameConverter':
    return cls(identifier, field_name_map)

  @property
  def field_name_map(self):
    return self._field_name_map

  def Convert(self,
              probe_info: stubby_pb2.ProbeInfo) -> Optional[_ConvertedValues]:
    translated: _ConvertedValues = {}
    probe_info_values = {}

    for param in probe_info.probe_parameters:
      if param.HasField('string_value'):
        probe_info_values[param.name] = param.string_value
      elif param.HasField('int_value'):
        probe_info_values[param.name] = converter_types.IntValueType(
            param.int_value)

    for name, translated_key in self._field_name_map.items():
      value = probe_info_values.get(name)
      if value is not None:
        translated[translated_key] = value
      else:
        return None
    return translated

  def Match(self, comp_values: Mapping[str, Any],
            probe_info: stubby_pb2.ProbeInfo) -> ProbeValueMatchStatus:
    converted = self.Convert(probe_info)
    if not converted:
      return ProbeValueMatchStatus.INCONVERTIBLE
    if not converted.keys() <= comp_values.keys():
      return ProbeValueMatchStatus.KEY_UNMATCHED
    if not converted.items() <= comp_values.items():
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

  def Match(self, comp_values: Mapping[str, Any],
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
