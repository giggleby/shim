# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Change unit related utilities."""

import abc
import collections
import functools
from typing import Any, List, Mapping, MutableMapping, MutableSequence, NamedTuple, Optional, Sequence

from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database

# Shorter identifiers.
_HWIDComponentAnalysisResult = contents_analyzer.HWIDComponentAnalysisResult


class SplitChangeUnitException(Exception):
  """Raised when the DB change cannot be framed in the predefined change
  units."""


class ApplyChangeUnitException(Exception):
  """Raised when a change unit cannot be applied."""


def _UnifyException(func):

  @functools.wraps(func)
  def _Wrapper(self, *args, **kwargs):
    try:
      return func(self, *args, **kwargs)
    except (common.HWIDException, builder.BuilderException) as e:
      raise ApplyChangeUnitException(
          f'Cannot apply change unit {self!r}.') from e

  return _Wrapper


def _GetExactlyOneComponentClassFromEncodedField(db: database.Database,
                                                 encoded_field_name: str):
  comp_classes = db.GetComponentClasses(encoded_field_name)
  if len(comp_classes) != 1:
    raise SplitChangeUnitException(
        'Extracting changes of encoded fields with multiple component classs '
        'is unsupported.')
  return comp_classes.pop()


#TODO(clarkchung): Add dependencies to change units.
class ChangeUnit(abc.ABC):
  """Base class of change units."""

  @abc.abstractmethod
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """Patches the change to the builder.

    Raises:
      ApplyChangeUnitException: Raised if this change unit cannot be applied.
    """


class CompChange(ChangeUnit):
  """A change unit to frame component changes.

  A CompChange instance includes component changes of creations or
  modifications.
  """

  def __init__(self, analysis_result: _HWIDComponentAnalysisResult,
               probe_values: Optional[builder.ProbedValueType],
               information: Optional[Mapping[str, Any]]):
    super().__init__()
    self._analysis_result = analysis_result
    self._probe_values = probe_values
    self._information = information

  # TODO: Enforce the updated name suffixed by '#<seq>'
  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    if self._analysis_result.is_newly_added:
      db_builder.AddComponent(
          self._analysis_result.comp_cls, self._analysis_result.comp_name,
          self._probe_values, self._analysis_result.support_status,
          self._information)
    else:  # Update component in-place
      db_builder.UpdateComponent(
          self._analysis_result.comp_cls,
          self._analysis_result.diff_prev.prev_comp_name,
          self._analysis_result.comp_name, self._probe_values,
          self._analysis_result.support_status, self._information)


class AddEncodingCombination(ChangeUnit):
  """A change unit to frame encoding combination addition.

  The first combination in an encoded field could not be reordered to other
  position due to the default component behavior.  This class uses _is_first
  field to ensure the following combinations must depend on the first if exists.
  """

  def __init__(self, is_first: bool, encoded_field_name: str, comp_cls: str,
               comp_names: Sequence[str], pattern_idxes: Sequence[int]):
    super().__init__()
    self._is_first = is_first
    self._encoded_field_name = encoded_field_name
    self._comp_cls = comp_cls
    self._comp_names = comp_names
    self._pattern_idxes = pattern_idxes

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    if self._is_first:
      db_builder.AddNewEncodedField(self._comp_cls, self._comp_names,
                                    self._encoded_field_name)
    else:
      db_builder.AddEncodedFieldComponents(self._encoded_field_name,
                                           self._comp_cls, self._comp_names)
    db_builder.FillEncodedFieldBit(self._encoded_field_name,
                                   self._pattern_idxes)


class NewImageIdToExistingEncodingPattern(ChangeUnit):
  """A change unit to frame new image id added into an existing pattern."""

  def __init__(self, image_name: str, image_id: int, pattern_idx: int):
    super().__init__()
    self._image_name = image_name
    self._image_id = image_id
    self._pattern_idx = pattern_idx

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    db_builder.AddImage(image_id=self._image_id, image_name=self._image_name,
                        new_pattern=False, pattern_idx=self._pattern_idx)


class ImageDesc(NamedTuple):
  id: int
  name: str


class _NewImage(NamedTuple):
  image_descs: List[ImageDesc]
  bit_mapping: List[database.PatternField]


class NewImageIdToNewEncodingPattern(ChangeUnit):
  """A change unit to frame new image id added with a new pattern."""

  def __init__(self, image_descs: Sequence[ImageDesc],
               bit_mapping: Sequence[database.PatternField]):
    super().__init__()
    self._image_descs = image_descs
    self._bit_mapping = bit_mapping

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    if len(self._image_descs) != len(
        set(desc.id for desc in self._image_descs)):
      raise ApplyChangeUnitException('Image IDs should be distinct.')
    if len(self._image_descs) != len(
        set(desc.name for desc in self._image_descs)):
      raise ApplyChangeUnitException('Image names should be distinct.')
    first_image_id, first_image_name = self._image_descs[0]
    db_builder.AddImage(image_id=first_image_id, image_name=first_image_name,
                        new_pattern=True)
    for image_id, image_name in self._image_descs[1:]:
      db_builder.AddImage(image_id=image_id, image_name=image_name,
                          new_pattern=False, reference_image_id=first_image_id)
    for pattern_field in self._bit_mapping:
      db_builder.AppendEncodedFieldBit(
          pattern_field.name, pattern_field.bit_length, image_id=first_image_id)


class ReplaceRules(ChangeUnit):
  """A change unit to replacing rules section."""

  def __init__(self, rule_expr_list: Mapping[str, Any]):
    super().__init__()
    self._rule_expr_list = rule_expr_list

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    db_builder.ReplaceRules(self._rule_expr_list)


# TODO(b/232063010): Return a generator which emits change units one-by-one
# in topological ordering after the dependency mechanism has been implemented.
def ExtractChangeUnitsFromDBChanges(
    old_db: database.Database,
    new_db: database.Database) -> Sequence[ChangeUnit]:
  """Extracts all change units from DBs."""
  change_units: MutableSequence[ChangeUnit] = []
  change_units += _ExtractCompChanges(old_db, new_db)
  change_units += _ExtractAddEncodingCombination(old_db, new_db)
  change_units += _ExtractNewImageIds(old_db, new_db)
  change_units += _ExtractReplaceRules(old_db, new_db)
  return change_units


def _ExtractCompChanges(old_db: database.Database,
                        new_db: database.Database) -> Sequence[CompChange]:
  change_units: MutableSequence[CompChange] = []
  analyzer = contents_analyzer.ContentsAnalyzer(
      new_db.DumpDataWithoutChecksum(), None, old_db.DumpDataWithoutChecksum())
  analysis = analyzer.AnalyzeChange(None, False)
  for comp_analysis in analysis.hwid_components.values():
    if comp_analysis.is_newly_added or not comp_analysis.diff_prev.unchanged:
      comp_name = comp_analysis.comp_name
      comp_info = new_db.GetComponents(comp_analysis.comp_cls)[comp_name]
      change_units.append(
          CompChange(comp_analysis, comp_info.values, comp_info.information))
  return change_units


def _ExtractAddEncodingCombination(
    old_db: database.Database,
    new_db: database.Database) -> Sequence['AddEncodingCombination']:

  common_pattern_idxes = range(old_db.GetPatternCount())

  def _GetPatternIdxesToFill(encoded_field_name: str) -> Sequence[int]:
    """Gets the indices of common patterns that include the given encoded field
    from new_db."""

    return [
        pattern_idx for pattern_idx in common_pattern_idxes
        if encoded_field_name in new_db.GetEncodedFieldsBitLength(
            pattern_idx=pattern_idx)
    ]

  change_units: List['AddEncodingCombination'] = []
  old_encoded_fields = set(old_db.encoded_fields)
  new_encoded_fields = set(new_db.encoded_fields)

  if old_db.GetPatternCount() > new_db.GetPatternCount():
    raise SplitChangeUnitException('Change of pattern removal is unsupported.')


  if not old_encoded_fields.issubset(new_encoded_fields):
    raise SplitChangeUnitException('Renaming encoded field is unsupported.')

  for extra_encoded_field in new_encoded_fields - old_encoded_fields:
    comp_cls = _GetExactlyOneComponentClassFromEncodedField(
        new_db, extra_encoded_field)

    # Only fill bits in existing patterns that include this encoded field.
    pattern_idxes_to_fill = _GetPatternIdxesToFill(extra_encoded_field)

    for idx, combination in new_db.GetEncodedField(extra_encoded_field).items():
      change_units.append(
          AddEncodingCombination(idx == 0, extra_encoded_field, comp_cls,
                                 combination[comp_cls], pattern_idxes_to_fill))

  old_rev_comp_idx = _ReverseCompIdxMapping(old_db)
  new_rev_comp_idx = _ReverseCompIdxMapping(new_db)

  # Existing encoded fields.
  for encoded_field in old_encoded_fields:
    old_combinations = old_db.GetEncodedField(encoded_field)
    new_combinations = new_db.GetEncodedField(encoded_field)
    # Not all fields indexed from 0 ~ len(combination) - 1 are defined for
    # region fields.
    old_comb_idx_set = set(old_combinations)
    new_comb_idx_set = set(new_combinations)
    if not old_comb_idx_set.issubset(new_comb_idx_set):
      raise SplitChangeUnitException('Some combinations are removed.')

    for i, old_comb_mapping in old_combinations.items():  # Common combinations.
      new_comb_mapping = new_combinations[i]
      if set(old_comb_mapping) != set(new_comb_mapping):
        raise SplitChangeUnitException(
            'Modifying component classes set of combinations is unsupported.')
      for comp_cls in old_comb_mapping:
        old_comp_idxes = set(old_rev_comp_idx[comp_cls][comp_name]
                             for comp_name in old_comb_mapping[comp_cls])
        new_comp_idxes = set(new_rev_comp_idx[comp_cls][comp_name]
                             for comp_name in new_comb_mapping[comp_cls])
        if old_comp_idxes != new_comp_idxes:
          raise SplitChangeUnitException(
              'Modifying existing combinations is unsupported.')

    # Only fill bits in existing patterns that include this encoded field.
    pattern_idxes_to_fill = _GetPatternIdxesToFill(encoded_field)

    if old_comb_idx_set < new_comb_idx_set:
      comp_cls = _GetExactlyOneComponentClassFromEncodedField(
          new_db, encoded_field)
      for i in new_comb_idx_set - old_comb_idx_set:  # new combinations
        comb = new_combinations[i][comp_cls]
        change_units.append(
            AddEncodingCombination(False, encoded_field, comp_cls, comb,
                                   pattern_idxes_to_fill))

  return change_units


def _ExtractNewImageIds(old_db: database.Database,
                        new_db: database.Database) -> Sequence[ChangeUnit]:

  change_units: MutableSequence[ChangeUnit] = []
  new_images: MutableMapping[int, _NewImage] = {}

  if not old_db.raw_image_id.items() <= new_db.raw_image_id.items():
    raise SplitChangeUnitException('Only image id/name addition is supported.')

  old_image_ids = set(old_db.image_ids)
  new_image_ids = set(new_db.image_ids)

  for extra_image_id in new_image_ids - old_image_ids:
    pattern = new_db.GetPattern(image_id=extra_image_id)
    image_name = new_db.GetImageName(extra_image_id)
    if pattern.idx < old_db.GetPatternCount():  # Existing pattern.
      change_units.append(
          NewImageIdToExistingEncodingPattern(image_name, extra_image_id,
                                              pattern.idx))
    else:  # New pattern.
      if pattern.idx not in new_images:
        new_images[pattern.idx] = _NewImage(image_descs=[],
                                            bit_mapping=list(pattern.fields))
      new_images[pattern.idx].image_descs.append(
          ImageDesc(extra_image_id, image_name))
  for new_image in new_images.values():
    change_units.append(
        NewImageIdToNewEncodingPattern(new_image.image_descs,
                                       new_image.bit_mapping))
  return change_units


def _ExtractReplaceRules(old_db: database.Database,
                         new_db: database.Database) -> Sequence[ReplaceRules]:

  change_units: MutableSequence[ReplaceRules] = []
  if old_db.raw_rules != new_db.raw_rules:
    change_units.append(ReplaceRules(new_db.raw_rules.Export()))
  return change_units


def _ReverseCompIdxMapping(
    db: database.Database) -> Mapping[str, Mapping[str, int]]:
  """Builds a mapping of (comp_cls, comp_name) -> idx.

  To compare combinations consistently, we should use the index in component
  list instead of the component name which could differ in HWID DB changes.

  Args:
    db: The database instance.

  Returns:
    A mapping of comp_cls -> (a mapping of comp name -> idx)
  """
  rev_comp_idx: MutableMapping[str, MutableMapping[str, int]] = (
      collections.defaultdict(dict))
  for comp_cls in db.GetComponentClasses():
    for i, comp_name in enumerate(db.GetComponents(comp_cls)):
      rev_comp_idx[comp_cls][comp_name] = i
  return rev_comp_idx
