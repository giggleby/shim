# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Change unit related utilities."""

import abc
import collections
import enum
import functools
import itertools
from typing import Any, Callable, DefaultDict, Deque, Iterable, Mapping, MutableMapping, MutableSequence, NamedTuple, Optional, Sequence, Set, Tuple, Type, Union
import uuid

from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import name_pattern_adapter


# Shorter identifiers.
_HWIDComponentAnalysisResult = contents_analyzer.HWIDComponentAnalysisResult

ChangeUnitIdentity = str


class SplitChangeUnitException(Exception):
  """Raised when the predefined change units can't frame the DB change."""


class ApplyChangeUnitException(Exception):
  """Raised when a change unit cannot be applied."""


class _ApprovalStatusUnsetException(Exception):
  """Raised when the approval status of a change unit has not been set."""


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
        'Extracting changes of encoded fields with multiple component classes '
        'is unsupported.')
  return next(iter(comp_classes))


def _IsNewlyCreatedOrRenamedComp(
    analysis_result: _HWIDComponentAnalysisResult) -> bool:
  return (analysis_result.is_newly_added or
          analysis_result.diff_prev.name_changed)


class ChangeUnitDepSpec:
  """Using fields to represent or filter change units.

  Every change unit instance will expose the following:
    * its dependency spec for other to select
    * a list of dependency spec that filters the depended change units
  """

  def __init__(self, cu_cls: Type['ChangeUnit'],
               *spec_tuple: Union[type(None), str, int, bool]):
    self._spec_tuple = (cu_cls, *spec_tuple)

  def __eq__(self, rhs: Any) -> bool:
    return self._spec_tuple == rhs._spec_tuple

  def __hash__(self) -> int:
    return hash(self._spec_tuple)


class ChangeUnit(abc.ABC):
  """Base class of change units."""

  def __init__(self, dep_spec: ChangeUnitDepSpec):
    """Initializer.

    Args:
      dep_spec: The spec of this change unit for other change units to find
        dependency.
    """

    self._identity = ChangeUnitIdentity(uuid.uuid4())
    self._dep_spec = dep_spec

  @abc.abstractmethod
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """Patches the change to the builder.

    Raises:
      ApplyChangeUnitException: Raised if this change unit cannot be applied.
    """

  def __repr__(self) -> str:
    """A string describing this change unit.

    Not that this string is to be debug/test only and not guaranteed to be
    unique.
    """
    return self.__class__.__name__

  @property
  def dep_spec(self) -> ChangeUnitDepSpec:
    return self._dep_spec

  @abc.abstractmethod
  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    """The depended specs."""

  @property
  def identity(self) -> ChangeUnitIdentity:
    """The identity used in dependency graph."""
    return self._identity


# A special instance to filter all other change units.
_ALL_OTHER_CHANGE_UNIT_DEP_SPEC = ChangeUnitDepSpec(ChangeUnit)


class CompChange(ChangeUnit):
  """A change unit to frame component changes.

  A CompChange instance includes component changes of creations or
  modifications.  Since change units should be independent, name collisions
  might occur.  In this case, we append the sequence number of the components to
  the component name to make it unique.
  """

  def __init__(self, analysis_result: _HWIDComponentAnalysisResult,
               probe_values: Optional[builder.ProbedValueType],
               information: Optional[Mapping[str, Any]], comp_hash: str,
               bundle_uuids: Optional[Sequence[str]] = None):
    super().__init__(
        self.CreateDepSpec(analysis_result.comp_cls, comp_hash,
                           _IsNewlyCreatedOrRenamedComp(analysis_result)))
    self._analysis_result = analysis_result
    self._probe_values = probe_values
    self._information = information
    self._comp_hash = comp_hash
    self._bundle_uuids = bundle_uuids

  def __repr__(self) -> str:
    comp_cls = self._analysis_result.comp_cls
    new = '(new)' if self._analysis_result.is_newly_added else ''
    comp_name = self._analysis_result.comp_name
    return f'{super().__repr__()}:{comp_cls}:{comp_name}{new}'

  @property
  def comp_analysis(self):
    return self._analysis_result

  @classmethod
  def CreateDepSpec(cls, comp_cls: str, comp_hash: str,
                    new_or_renamed: bool) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls, comp_cls, comp_hash, new_or_renamed)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    comp_name = name_pattern_adapter.TrimSequenceSuffix(
        self._analysis_result.comp_name)
    comp_cls = self._analysis_result.comp_cls
    comps = db_builder.GetComponents(comp_cls)
    if self._analysis_result.is_newly_added:
      if comp_name in comps:
        # Name collision, add sequence suffix.
        comp_name = name_pattern_adapter.AddSequenceSuffix(
            comp_name,
            len(db_builder.GetComponents(comp_cls)) + 1)
      db_builder.AddComponent(comp_cls, comp_name, self._probe_values,
                              self._analysis_result.support_status,
                              self._information)
    else:  # Update component in-place.
      if (comp_name in comps and
          comp_name != self._analysis_result.diff_prev.prev_comp_name):
        # Name collision while renaming component to an existing name.
        comp_name = name_pattern_adapter.AddSequenceSuffix(
            comp_name, self._analysis_result.seq_no)
      db_builder.UpdateComponent(
          comp_cls, self._analysis_result.diff_prev.prev_comp_name, comp_name,
          self._probe_values, self._analysis_result.support_status,
          self._information, self._bundle_uuids)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    # Adding/Updating components does not depend on other change units.
    yield from ()


class AddEncodingCombination(ChangeUnit):
  """A change unit to frame encoding combination addition.

  The first combination in an encoded field could not be reordered to other
  position due to the default component behavior.  This class uses _is_first
  field to ensure the following combinations must depend on the first if exists.
  """

  def __init__(
      self,
      is_first: bool,
      encoded_field_name: str,
      comp_cls: str,
      comp_hashes: Sequence[str],
      comp_analyses: Sequence[_HWIDComponentAnalysisResult],
  ):
    super().__init__(self.CreateDepSpec(is_first, encoded_field_name))
    self._is_first = is_first
    self._encoded_field_name = encoded_field_name
    self._comp_cls = comp_cls
    self._comp_hashes = comp_hashes
    self._comp_analyses = comp_analyses

  @property
  def comp_cls(self):
    return self._comp_cls

  @property
  def comp_analyses(self):
    return self._comp_analyses

  def __repr__(self) -> str:
    encoded_field_name = (f'{self._encoded_field_name}'
                          f"{'(first)' if self._is_first else ''}")
    comp_cls = self._comp_cls
    comp_names = ','.join(info.comp_name for info in self._comp_analyses)
    return f'{super().__repr__()}:{encoded_field_name}-{comp_cls}:{comp_names}'

  @classmethod
  def CreateDepSpec(cls, is_first: bool,
                    encoded_field_name: str) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls, is_first, encoded_field_name)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    comp_names = [
        db_builder.GetComponentNameByHash(self._comp_cls, comp_hash)
        for comp_hash in self._comp_hashes
    ]

    if self._is_first:
      db_builder.AddNewEncodedField(self._comp_cls, comp_names,
                                    self._encoded_field_name)
    else:
      db_builder.AddEncodedFieldComponents(self._encoded_field_name,
                                           self._comp_cls, comp_names)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    # Combinations depend on the mentioned components.
    yield from (CompChange.CreateDepSpec(self._comp_cls, comp_hash, True)
                for comp_hash in self._comp_hashes)
    if not self._is_first:
      # The first combination of a certain encoded field might be used as the
      # default component, so other components depend on such change unit if
      # exists.
      yield self.CreateDepSpec(True, self._encoded_field_name)


class PadEncodingBits(ChangeUnit):
  """A change unit to frame padding bits changes.

  This change unit is responsible for padding bits in image patterns to ensure
  the coverage of all encoded fields.
  """

  def __init__(
      self,
      encoded_field_name: str,
      pattern_idxes: Sequence[int],
  ):
    super().__init__(self.CreateDepSpec())
    self._encoded_field_name = encoded_field_name
    self._pattern_idxes = pattern_idxes

  def __repr__(self) -> str:
    pattern_idxes_str = ','.join(str(i) for i in self._pattern_idxes)
    return (f'{super().__repr__()}:{self._encoded_field_name}-'
            f'{pattern_idxes_str}')

  @classmethod
  def CreateDepSpec(cls) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""
    db_builder.FillEncodedFieldBit(self._encoded_field_name,
                                   self._pattern_idxes)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    # Padding pattern bits depend on AddEncodingCombination change units of the
    # encoded field.
    yield AddEncodingCombination.CreateDepSpec(True, self._encoded_field_name)
    yield AddEncodingCombination.CreateDepSpec(False, self._encoded_field_name)


class NewImageIdToExistingEncodingPattern(ChangeUnit):
  """A change unit to frame new image id added into an existing pattern."""

  def __init__(self, image_name: str, image_id: int, pattern_idx: int,
               last: bool):
    super().__init__(self.CreateDepSpec(last))
    self._image_name = image_name
    self._image_id = image_id
    self._pattern_idx = pattern_idx
    self._last = last

  @property
  def image_name(self):
    return self._image_name

  def __repr__(self) -> str:
    image_name = self._image_name
    image_id = self._image_id
    last = '(last)' if self._last else ''
    return f'{super().__repr__()}:{image_name}({image_id}){last}'

  @classmethod
  def CreateDepSpec(cls, last: bool) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls, last)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    db_builder.AddImage(image_id=self._image_id, image_name=self._image_name,
                        new_pattern=False, pattern_idx=self._pattern_idx)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    yield RenameImages.CreateDepSpec()
    if self._last:
      # The max image ID (except RMA) will be used as the default image to
      # perform encoding process.
      yield self.CreateDepSpec(False)
      yield AssignBitMappingToEncodingPattern.CreateDepSpec(False)


class ImageDesc(NamedTuple):
  id: int
  name: str


class _NewImage:

  def __init__(self, image_descs: MutableSequence[ImageDesc],
               bit_mapping: Sequence[database.PatternField]):
    self.image_descs = image_descs
    self.bit_mapping = bit_mapping
    self.contains_last = False


class AssignBitMappingToEncodingPattern(ChangeUnit):
  """A change unit to frame bit patterns assignment.

  This change unit applies to two cases:
    1. Add a new pattern with multiple (image_id, image_name) pairs.
    2. Append bit patterns to an existing pattern of the DB.  In this
       case the image_descs must only contain the associated image desc and the
       reused_pattern_idx must not be None.
  Note that the case 2. the (image_id, image_name) is an existed image desc and
  will not be added into the DB.
  """

  def __init__(self, image_descs: Sequence[ImageDesc],
               bit_mapping: Sequence[database.PatternField],
               contains_last: bool, reused_pattern_idx: Optional[int] = None):
    super().__init__(self.CreateDepSpec(contains_last))
    if reused_pattern_idx is not None and len(image_descs) != 1:
      raise ValueError('An AssignBitMappingToEncodingPattern change unit with '
                       'reused_pattern_idx must only have the associated image '
                       'desc.')
    self._image_descs = image_descs
    self._bit_mapping = bit_mapping
    self._contains_last = contains_last
    self._reused_pattern_idx = reused_pattern_idx

  @property
  def image_descs(self):
    return self._image_descs

  def __repr__(self) -> str:
    if self._reused_pattern_idx is None:
      image_desc = self._image_descs[0]
      contains_last = '(last)' if self._contains_last else ''
      return (f'{super().__repr__()}:{image_desc.name}({image_desc.id})'
              f'{contains_last}')
    return f'{super().__repr__()}:reused_pattern_id:{self._reused_pattern_idx}'

  @classmethod
  def CreateDepSpec(cls, contains_last: bool) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls, contains_last)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    if self._reused_pattern_idx is None:
      if len(self._image_descs) != len(
          set(desc.id for desc in self._image_descs)):
        raise ApplyChangeUnitException('Image IDs should be distinct.')
      if len(self._image_descs) != len(
          set(desc.name for desc in self._image_descs)):
        raise ApplyChangeUnitException('Image names should be distinct.')
      image_desc_iter = iter(self._image_descs)
      first_image_id, first_image_name = next(image_desc_iter)
      pattern_idx = db_builder.AddImage(image_id=first_image_id,
                                        image_name=first_image_name,
                                        new_pattern=True)
      for image_id, image_name in image_desc_iter:
        db_builder.AddImage(image_id=image_id, image_name=image_name,
                            new_pattern=False,
                            reference_image_id=first_image_id)
    else:
      pattern_idx = self._reused_pattern_idx
    for pattern_field in self._bit_mapping:
      db_builder.AppendEncodedFieldBit(
          pattern_field.name, pattern_field.bit_length, pattern_idx=pattern_idx)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    if self._reused_pattern_idx is None:
      # The RenameImages change unit should be applied before new image names
      # are added into DB to avoid name collision.
      yield RenameImages.CreateDepSpec()
    if self._contains_last:
      # The max image ID (except RMA) will be used as the default image to
      # perform encoding process.
      yield self.CreateDepSpec(False)
      yield NewImageIdToExistingEncodingPattern.CreateDepSpec(False)
    # Change units of first combination of an encoded field should be patched
    # before patching bit patterns including them.
    yield from set(
        AddEncodingCombination.CreateDepSpec(True, pattern_field.name)
        for pattern_field in self._bit_mapping)


class ReplaceRules(ChangeUnit):
  """A change unit to replace rules section."""

  def __init__(self, rule_expr_list: Mapping[str, Any]):
    super().__init__(self.CreateDepSpec())
    self._rule_expr_list = rule_expr_list

  @classmethod
  def CreateDepSpec(cls) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""

    db_builder.ReplaceRules(self._rule_expr_list)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    # Rules must be patched last.  Note that the self-reference will be skipped
    # in ChangeUnitManager._SetDependency().
    yield _ALL_OTHER_CHANGE_UNIT_DEP_SPEC


class RenameImages(ChangeUnit):
  """A change unit to rename a image."""

  def __init__(self, target_image_mapping: Mapping[int, str]):
    super().__init__(self.CreateDepSpec())
    self._target_image_mapping = target_image_mapping

  @classmethod
  def CreateDepSpec(cls) -> ChangeUnitDepSpec:
    return ChangeUnitDepSpec(cls)

  @_UnifyException
  def Patch(self, db_builder: builder.DatabaseBuilder):
    """See base class."""
    db_builder.RenameImages(self._target_image_mapping)

  def GetDependedSpecs(self) -> Iterable[ChangeUnitDepSpec]:
    # Rename all existing image names does not depend on other change units.
    yield from ()


def _ExtractCompChanges(analysis_mapping: MutableMapping[Tuple[
    str, str], _HWIDComponentAnalysisResult],
                        new_db: database.Database) -> Iterable[CompChange]:
  for (comp_cls, comp_name), comp_analysis in analysis_mapping.items():
    if comp_analysis.is_newly_added or not comp_analysis.diff_prev.unchanged:
      comp_info = new_db.GetComponents(comp_cls)[comp_name]
      yield CompChange(comp_analysis, comp_info.values, comp_info.information,
                       comp_info.comp_hash, comp_info.bundle_uuids)


def _ExtractEncodingRelatedChanges(
    analysis_mapping: MutableMapping[Tuple[str, str],
                                     _HWIDComponentAnalysisResult],
    old_db: database.Database,
    new_db: database.Database,
) -> Iterable[Union[AddEncodingCombination, PadEncodingBits]]:

  if old_db.is_initial:
    common_pattern_idxes = range(1, old_db.GetPatternCount())
  else:
    common_pattern_idxes = range(old_db.GetPatternCount())

  def _GetPatternIdxesToFill(encoded_field_name: str) -> Sequence[int]:
    """Gets the indices of common patterns requiring bit filling.

    Returns:
      Indices of patterns including the specified encoded field in new_db.
    """

    return [
        pattern_idx for pattern_idx in common_pattern_idxes
        if encoded_field_name in new_db.GetEncodedFieldsBitLength(
            pattern_idx=pattern_idx)
    ]

  def _GetPatternIdxesWithNewEncodedFields(
      encoded_field_name: str) -> Sequence[int]:
    """Gets the indices of common patterns requiring bit filling.

    Returns:
      Indices of patterns including the specified encoded field in new_db but
      not in old_db.
    """

    return [
        pattern_idx for pattern_idx in common_pattern_idxes
        if encoded_field_name in new_db.GetEncodedFieldsBitLength(
            pattern_idx=pattern_idx) and encoded_field_name not in
        old_db.GetEncodedFieldsBitLength(pattern_idx=pattern_idx)
    ]

  def _GetComponentHashes(comp_cls: str,
                          comp_names: Iterable[str]) -> Sequence[str]:
    components_store = new_db.GetComponents(comp_cls)
    return [components_store[comp_name].comp_hash for comp_name in comp_names]

  old_encoded_fields = set(old_db.encoded_fields)
  new_encoded_fields = set(new_db.encoded_fields)

  if old_db.GetPatternCount() > new_db.GetPatternCount():
    raise SplitChangeUnitException('Change of pattern removal is unsupported.')

  if not old_encoded_fields.issubset(new_encoded_fields):
    raise SplitChangeUnitException(
        'Renaming/Removing encoded field is unsupported.')

  for extra_encoded_field in new_encoded_fields - old_encoded_fields:
    comp_cls = _GetExactlyOneComponentClassFromEncodedField(
        new_db, extra_encoded_field)

    # Only fill bits in existing patterns that include this encoded field.
    pattern_idxes_to_fill = _GetPatternIdxesToFill(extra_encoded_field)
    if pattern_idxes_to_fill:
      yield PadEncodingBits(extra_encoded_field, pattern_idxes_to_fill)

    for idx, combination in new_db.GetEncodedField(extra_encoded_field).items():
      component_hashes = _GetComponentHashes(comp_cls, combination[comp_cls])
      comp_analyses = [
          analysis_mapping[comp_cls, comp_name]
          for comp_name in combination[comp_cls]
      ]
      yield AddEncodingCombination(idx == 0, extra_encoded_field, comp_cls,
                                   component_hashes, comp_analyses)

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
        old_comp_idxes = sorted(old_rev_comp_idx[comp_cls][comp_name]
                                for comp_name in old_comb_mapping[comp_cls])
        new_comp_idxes = sorted(new_rev_comp_idx[comp_cls][comp_name]
                                for comp_name in new_comb_mapping[comp_cls])
        if old_comp_idxes != new_comp_idxes:
          raise SplitChangeUnitException(
              'Modifying existing combinations is unsupported.')

    if old_comb_idx_set < new_comb_idx_set:
      # Only fill bits in existing patterns that include this encoded field.
      pattern_idxes_to_fill = _GetPatternIdxesToFill(encoded_field)
      if pattern_idxes_to_fill:
        yield PadEncodingBits(encoded_field, pattern_idxes_to_fill)
      comp_cls = _GetExactlyOneComponentClassFromEncodedField(
          new_db, encoded_field)
      for i in new_comb_idx_set - old_comb_idx_set:  # new combinations
        comb = new_combinations[i][comp_cls]
        component_hashes = _GetComponentHashes(comp_cls, comb)
        comp_analyses = [
            analysis_mapping[comp_cls, comp_name] for comp_name in comb
        ]
        yield AddEncodingCombination(False, encoded_field, comp_cls,
                                     component_hashes, comp_analyses)
    else:
      # A pattern introduces an existing encoded field without combinations
      # changed.
      pattern_idxes_to_fill = _GetPatternIdxesWithNewEncodedFields(
          encoded_field)
      if pattern_idxes_to_fill:
        yield PadEncodingBits(encoded_field, pattern_idxes_to_fill)


def _ExtractRenameImages(old_db: database.Database,
                         new_db: database.Database) -> Iterable[ChangeUnit]:
  if old_db.raw_image_id.items() <= new_db.raw_image_id.items():
    return
  removed_image_ids = set(old_db.image_ids) - set(new_db.image_ids)
  if removed_image_ids:
    raise SplitChangeUnitException(
        f'Image IDs are removed: {removed_image_ids}')
  yield RenameImages({
      image_id: new_db.GetImageName(image_id)
      for image_id in old_db.image_ids
  })


def _ExtractNewImageIds(old_db: database.Database,
                        new_db: database.Database) -> Iterable[ChangeUnit]:

  new_images: MutableMapping[int, _NewImage] = {}

  old_image_ids = set(old_db.image_ids)
  new_image_ids = set(new_db.image_ids)
  max_image_id = new_db.max_image_id

  for extra_image_id in new_image_ids - old_image_ids:
    pattern = new_db.GetPattern(image_id=extra_image_id)
    image_name = new_db.GetImageName(extra_image_id)
    if pattern.idx < old_db.GetPatternCount():  # Existing pattern.
      yield NewImageIdToExistingEncodingPattern(image_name, extra_image_id,
                                                pattern.idx,
                                                extra_image_id == max_image_id)
    else:  # New pattern.
      if pattern.idx not in new_images:
        new_images[pattern.idx] = _NewImage(image_descs=[],
                                            bit_mapping=list(pattern.fields))
      if extra_image_id == max_image_id:
        new_images[pattern.idx].contains_last = True
      new_images[pattern.idx].image_descs.append(
          ImageDesc(extra_image_id, image_name))
  for new_image in new_images.values():
    yield AssignBitMappingToEncodingPattern(
        new_image.image_descs, new_image.bit_mapping, new_image.contains_last)

  if old_db.is_initial:  # old_db is an initial DB.
    first_bit_pattern_in_new_db = new_db.GetPattern(pattern_idx=0)
    if not first_bit_pattern_in_new_db.fields:
      raise SplitChangeUnitException('Empty bit pattern in the upload change.')
    yield AssignBitMappingToEncodingPattern(
        image_descs=[ImageDesc(0, new_db.GetImageName(0))],
        bit_mapping=list(first_bit_pattern_in_new_db.fields),
        contains_last=(max_image_id == 0), reused_pattern_idx=0)


def _ExtractReplaceRules(old_db: database.Database,
                         new_db: database.Database) -> Iterable[ReplaceRules]:

  if old_db.raw_rules != new_db.raw_rules:
    yield ReplaceRules(new_db.raw_rules.Export())


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


class ApprovalStatus(enum.IntEnum):
  """The approval status of change units."""

  AUTO_APPROVED = enum.auto()
  DONT_CARE = enum.auto()
  MANUAL_REVIEW_REQUIRED = enum.auto()
  REJECTED = enum.auto()


class DependencyNode:
  """Represents a graph node in change unit selection with topological sort."""

  def __init__(self, identity: ChangeUnitIdentity):
    self._identity = identity
    self.n_prerequisites = 0
    self.approval_status: Optional[ApprovalStatus] = None
    self.dependents: Set['DependencyNode'] = set()

  @property
  def identity(self):
    return self._identity

  def __hash__(self):
    return hash(self._identity)

  def __eq__(self, rhs: Any) -> bool:
    return self._identity == rhs._identity

  @property
  def auto_mergeable(self) -> bool:
    if self.approval_status is None:
      raise _ApprovalStatusUnsetException(
          f'The approval status of change unit {self!r} is unset.')
    return self.independent and self.approval_status in (
        ApprovalStatus.AUTO_APPROVED, ApprovalStatus.DONT_CARE)

  @property
  def independent(self) -> bool:
    return not self.n_prerequisites


class ChangeSplitResult(NamedTuple):
  auto_mergeable_db: database.Database
  auto_mergeable_change_unit_identities: Sequence[str]
  review_required_db: database.Database
  review_required_change_unit_identities: Sequence[str]

  @property
  def auto_mergeable_noop(self) -> bool:
    return not self.auto_mergeable_change_unit_identities

  @property
  def review_required_noop(self) -> bool:
    return not self.review_required_change_unit_identities


class ChangeUnitManager:
  """Supports topological sort of change units and splitting the HWID change."""

  def __init__(
      self, old_db: database.Database, new_db: database.Database,
      skip_avl_check_checker: Optional[Callable[[str, database.ComponentInfo],
                                                bool]] = None):
    """Initializer.

    Raises:
      SplitChangeUnitException: If the DB change cannot be splitted.
    """
    self._old_db = old_db
    self._new_db = new_db
    self._change_units: MutableMapping[ChangeUnitIdentity, ChangeUnit] = {}
    self._by_dep_spec: DefaultDict[ChangeUnitDepSpec,
                                   Set[ChangeUnitIdentity]] = (
                                       collections.defaultdict(set))
    self._dep_nodes: MutableMapping[ChangeUnitIdentity, DependencyNode] = {}
    change_units = self._ExtractChangeUnits(skip_avl_check_checker)
    self._BuildDependencies(change_units)

  def _ExtractChangeUnits(
      self,
      skip_avl_check_checker: Optional[Callable[[str, database.ComponentInfo],
                                                bool]] = None
  ) -> Iterable[ChangeUnit]:
    """Extracts change units from two HWID DBs.

    Args:
      skip_avl_check_checker: An optional checker to determine if a component
        does not require AVL check.

    Returns:
      An iterable of change units.

    Raises:
      SplitChangeUnitException: If the DB change cannot be splitted.
    """
    analyzer = contents_analyzer.ContentsAnalyzer(
        self._new_db.DumpDataWithoutChecksum(internal=True), None,
        self._old_db.DumpDataWithoutChecksum(internal=True))
    analysis = analyzer.AnalyzeChange(
        None, False, skip_avl_check_checker=skip_avl_check_checker)
    analysis_mapping: MutableMapping[Tuple[str, str],
                                     _HWIDComponentAnalysisResult] = {}
    for comp_analysis in analysis.hwid_components.values():
      analysis_mapping[comp_analysis.comp_cls, comp_analysis.comp_name] = (
          comp_analysis)

    yield from itertools.chain(
        _ExtractCompChanges(analysis_mapping, self._new_db),
        _ExtractEncodingRelatedChanges(analysis_mapping, self._old_db,
                                       self._new_db),
        _ExtractRenameImages(self._old_db, self._new_db),
        _ExtractNewImageIds(self._old_db, self._new_db),
        _ExtractReplaceRules(self._old_db, self._new_db))

  def _BuildDependencies(self, change_units: Iterable[ChangeUnit]):
    for change_unit in change_units:
      identity = change_unit.identity
      self._dep_nodes[identity] = DependencyNode(identity)
      self._change_units[change_unit.identity] = change_unit
      self._by_dep_spec[change_unit.dep_spec].add(change_unit.identity)
      if _ALL_OTHER_CHANGE_UNIT_DEP_SPEC not in change_unit.GetDependedSpecs():
        self._by_dep_spec[_ALL_OTHER_CHANGE_UNIT_DEP_SPEC].add(
            change_unit.identity)

    for change_unit in self._change_units.values():
      for depended_spec in change_unit.GetDependedSpecs():
        for depended_id in self._GetChangeUnitIdentitiesByDepSpec(
            depended_spec):
          self._SetDependency(self._dep_nodes[change_unit.identity],
                              self._dep_nodes[depended_id])

  def ExportDependencyGraph(
      self) -> Mapping[ChangeUnitIdentity, Set[ChangeUnitIdentity]]:
    """Export the dependencies of the change units by ChangeUnitIdentity."""
    return {
        repr(self._change_units[dep_identity]): {
            repr(self._change_units[dependent.identity])
            for dependent in depended.dependents
        }
        for dep_identity, depended in self._dep_nodes.items()
    }

  def SetApprovalStatus(self, approval_status: Mapping[ChangeUnitIdentity,
                                                       ApprovalStatus]):
    """Sets the approval status for every change unit."""

    for identity, status in approval_status.items():
      assert status != ApprovalStatus.REJECTED
      self._dep_nodes[identity].approval_status = status

  def _GetChangeUnitIdentitiesByDepSpec(
      self, spec: ChangeUnitDepSpec) -> Iterable[ChangeUnitIdentity]:
    yield from self._by_dep_spec[spec]

  def GetChangeUnits(self) -> Mapping[ChangeUnitIdentity, ChangeUnit]:
    """Gets the mapping of identity -> change unit."""

    return self._change_units

  def _SetDependency(self, dependent: DependencyNode, depended: DependencyNode):
    if dependent not in depended.dependents:
      depended.dependents.add(dependent)
      dependent.n_prerequisites += 1

  def _PatchInTopologicalOrder(
      self, db_data: str, condition: Callable[[DependencyNode], bool],
      remaining: Set[ChangeUnitIdentity]
  ) -> Tuple[database.Database, Sequence[str]]:

    patched_change_unit_identities = []
    q: Deque[DependencyNode] = collections.deque()
    for identity in remaining:
      node = self._dep_nodes[identity]
      if condition(node):
        q.append(node)

    with builder.DatabaseBuilder.FromDBData(db_data) as db_builder:
      while q:
        node = q.popleft()
        remaining.remove(node.identity)
        patched_change_unit_identities.append(node.identity)
        self._change_units[node.identity].Patch(db_builder)
        for dependent in node.dependents:
          dependent.n_prerequisites -= 1
          if condition(dependent):
            q.append(dependent)

    return db_builder.Build(), patched_change_unit_identities

  def SplitChange(self) -> ChangeSplitResult:
    """Splits HWID DB change by dependency relation and approval status.

    This method picks auto-mergeable change units topologically to create first
    Database instance with maximal change units which has AUTO_APPROVED or
    DONT_CARE approval status and no dependencies to the remaining ones.  The
    rest change units will again be patched topologically to create another DB
    where the diff between the two could be used to create a CL requiring
    reviews.

    Returns:
      An instance of ChangeSplitResult.
    Raises:
      SplitChangeUnitException: If the DB change cannot be splitted.
      ApplyChangeUnitException: If the extracted change units cannot be applied
        to the DB.
    """

    remaining = set(self._change_units)

    try:
      auto_mergeable_db, auto_mergeable_change_unit_identities = (
          self._PatchInTopologicalOrder(
              self._old_db.DumpDataWithoutChecksum(internal=True),
              lambda node: node.auto_mergeable, remaining))
    except _ApprovalStatusUnsetException as ex:
      raise SplitChangeUnitException(str(ex)) from None

    review_required_db, review_required_change_unit_identities = (
        self._PatchInTopologicalOrder(
            auto_mergeable_db.DumpDataWithoutChecksum(internal=True),
            lambda node: node.independent, remaining))

    if remaining:
      raise SplitChangeUnitException('Unexpected cyclic dependency detected.')

    return ChangeSplitResult(
        auto_mergeable_db, auto_mergeable_change_unit_identities,
        review_required_db, review_required_change_unit_identities)
