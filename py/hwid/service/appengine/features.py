# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import collections
import itertools
from typing import Container, Generic, Iterable, Mapping, NamedTuple, Optional, Sequence, Sized, TypeVar, Union

from cros.factory.hwid.v3 import common as hwid_common
from cros.factory.hwid.v3 import database as db_module
from cros.factory.hwid.v3 import name_pattern_adapter as npa_module


_CollectionElementType = TypeVar('_CollectionElementType')


class Collection(abc.ABC, Generic[_CollectionElementType],
                 Container[_CollectionElementType], Sized,
                 Iterable[_CollectionElementType]):
  """A custom alias of `typing.Collection` to avoid `pylint`'s false alarms."""
  # The current `pylint` reports false alarm "unsubscriptable-object: Value
  # 'Collection' is unsubscriptable" because it fails to treat the built-in
  # one as a type.  This replacement helps `pylint` correctly recognize the
  # data type.
  # TODO(yhong): Use the built-in `typing.Collection` after the
  #    [fix](https://github.com/PyCQA/pylint/issues/2377) is adopted to the
  #    repository.


class DLMComponentEntryID(NamedTuple):
  """Identifier of a DLM component entry.

  Attributes:
    cid: The DLM component ID.
    qid: The DLM qualification ID if the target entry is a qualification.
  """
  cid: int
  qid: Optional[int]


class CPUProperty(NamedTuple):
  """Holds CPU properties related to versioned features.

  Attributes:
    compatible_versions: A set of feature versions this CPU is compatible to.
  """
  compatible_versions: Collection[int]


class DLMComponentEntry(NamedTuple):
  """Represents one single DLM component entry.

  Attributes:
    dlm_id: The entry ID.
    cpu_property: The CPU related properties if the entry supports the CPU
      functionality.
  """
  dlm_id: DLMComponentEntryID
  cpu_property: Optional[CPUProperty]
  # TODO(yhong): Add more component properties on need.


DLMComponentDatabase = Mapping[DLMComponentEntryID, DLMComponentEntry]


class HWIDSpec(abc.ABC):
  """Interface of a scoped HWID spec for a certain feature version."""

  @abc.abstractmethod
  def GetName(self) -> str:
    """Returns a name identifier."""

  @abc.abstractmethod
  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """Finds and returns all HWID encoded values that satisfy the spec.

    If a HWID string contains any of the returned encoded field value, that
    HWID is considered compliant to this spec. For example, assuming that the
    return value is the following.

      {
          'storage_field': [2, 4],
          'storage_bridge_field': [1, 2, 5],
      }

    Then if decoding the HWID, one get
    `storage_field: 0, storage_bridge_field: 2`, then the source HWID is
    considered compliant.  But if the decoded result shows that `storage_field`
    value is neither 2 nor 4 while `storage_bridge_field` is neither 1, 2, nor
    5, then the HWID is not satisfied.

    Args:
      db: The HWID DB that records the encoding info.
      dlm_db: The DLM component database that contains component's properties.

    Returns:
      A dictionary that maps the encoded field name to all compliant encoded
      field values.

    Raises:
      HWIDDBNotSupportError: if the HWID DB scheme is incompatible to this
        spec implementation.
    """


class HWIDBitStringRequirement(NamedTuple):
  """Represents a simple requirement to the HWID bit string.

  Specifically, it requires that the HWID bit string should fulfill the
  following condition:

    <VALUE> in `.required_values`, where
    <VALUE> := sum((hwid_bit_string[bit_position] << offset)
                   for offset, bit_position in enumerate(`.bit_positions`))

  Attributes:
    description: Briefly describes the rationale of this requirement.
    bit_positions: A ordered non-empty sequence of bit locations to check.
    required_values: The non-empty expected value sets of the specified bits.
  """
  description: str
  bit_positions: Sequence[int]
  required_values: Collection[int]


class HWIDDBNotSupportError(Exception):
  """The HWID DB scheme is incompatible to the HWID requirement resolver."""


_ALWAYS_FULFILL = object()


def _RearrangeValueBits(value: int, bit_offsets: Sequence[int]) -> int:
  """Converts the integer value by rearranging the bits.

  Essentially, it reorders the bits so that the i-th bit in the result comes
  from the `bit_offsets[i]`-th bit in the given `value`.

  Args:
    value: The value to convert.
    bit_offsets: The bit mapping.

  Returns:
    The converted value.
  """
  return sum(((value >> bit_offset) & 1) << bit_index
             for bit_index, bit_offset in enumerate(bit_offsets))


class _HWIDSpecBitStringRequirementResolver:
  """Helps deduce the HWID bit string requirements for spec satisfation."""

  def __init__(self, spec: HWIDSpec):
    self._spec = spec

  def _GetHWIDBitStringRequirementForEncodedField(
      self, db: db_module.Database, pattern_idx: int, encoded_field_name: str,
      encoded_field_values: Collection[int]
  ) -> Union[bool, HWIDBitStringRequirement]:
    """Derives the HWID bit string requirement for the encoded field value.

    Args:
      db: The HWID DB instance that contains the bit pattern info.
      pattern_idx: The index of the bit pattern in the HWID DB.
      encoded_field_name: The name of the encoded field.
      encoded_field_values: The acceptable encoded field values.

    Returns:
      If no any HWID string from the specified pattern can encode the acceptable
      encoded field values, it returns `False`.  If all of the HWID strings
      from the specified pattern can encode any of the encoded field value,
      it returns `True`.  Otherwise, it returns the corresponding HWID bit
      string requirement.
    """
    field_bit_lengths = db.GetEncodedFieldsBitLength(pattern_idx=pattern_idx)
    if encoded_field_name not in field_bit_lengths:
      return False

    field_bit_length = field_bit_lengths[encoded_field_name]
    if field_bit_length == 0:
      return 0 in encoded_field_values

    bit_positions = []
    bit_offsets = []
    for bit_position, (field_name, bit_offset) in enumerate(
        db.GetBitMapping(pattern_idx=pattern_idx)):
      if field_name == encoded_field_name:
        bit_positions.append(hwid_common.HEADER_BIT_LENGTH + bit_position)
        bit_offsets.append(bit_offset)

    bit_values = [_RearrangeValueBits(encoded_field_value, bit_offsets)
                  for encoded_field_value in encoded_field_values
                  if encoded_field_value.bit_length() <= field_bit_length]
    if not bit_values:
      return False
    return HWIDBitStringRequirement(
        description=(
            f'{self._spec.GetName()},encoded_field={encoded_field_name}'),
        bit_positions=bit_positions, required_values=bit_values)

  def DeduceRequirementCandidates(
      self, db: db_module.Database, pattern_idx: int,
      dlm_db: DLMComponentDatabase
  ) -> Union[type(_ALWAYS_FULFILL), Sequence[HWIDBitStringRequirement]]:
    """Deduce the HWID bit string requirement candidates for the given pattern.

    Args:
      db: The HWID DB instance that contains the bit pattern info.
      pattern_idx: The index of the bit pattern in the HWID DB.
      dlm_db: The DLM entry database that contains components' properties.

    Returns:
      If no HWID string from the specified pattern is ever compliant to the
      spec, it returns an empty container.  If all HWID strings of the specific
      pattern are compliant to the spec, this method returns `_ALWAYS_FULFILL`.
      Otherwise, it returns a set of HWID bit string requirements that if the
      HWID string fulfills any of the requirement, it is considered compliant
      to the spec.

    Raises:
      HWIDDBNotSupportError: If the HWID DB scheme is incompatible to any of
        the underlying spec implementation.
    """
    encoded_values = self._spec.FindSatisfiedEncodedValues(db, dlm_db)
    result_requirements = []
    for encoded_field_name, encoded_field_values in encoded_values.items():
      result = self._GetHWIDBitStringRequirementForEncodedField(
          db, pattern_idx, encoded_field_name, encoded_field_values)
      if result is True:
        return _ALWAYS_FULFILL
      if result is False:
        continue
      result_requirements.append(result)
    return result_requirements


class HWIDRequirement(NamedTuple):
  """Represents all requisite requirements to the HWID.

  Attributes:
    description: Briefly describes the rationale of this requirement set.
    bit_string_prerequisites: The requisite bit string requirements.  An empty
      container represents the fact that any HWID string can fulfill this
      requirement.
  """
  description: str
  bit_string_prerequisites: Collection[HWIDBitStringRequirement]


class _HWIDRequirementResolverForEncodedFieldPart:
  """Deduces HWID requirements for the encoded field part."""

  def __init__(self, specs: Sequence[HWIDSpec], db: db_module.Database,
               dlm_db: DLMComponentDatabase):
    """Initializer.

    Args:
      specs: The specs of the target versioned feature.
      db: The HWID DB to check.
      dlm_db: The DLM entry database that contains components' properties.
    """
    self._requirement_resolvers = [
        _HWIDSpecBitStringRequirementResolver(spec) for spec in specs
    ]
    self._db = db
    self._dlm_db = dlm_db

  def DeduceHWIDRequirementCandidates(
      self, pattern_idx: int) -> Collection[HWIDRequirement]:
    """Deduces all HWID requirement candidates under the given pattern index.

    Args:
      pattern_idx: The specified HWID DB pattern index.

    Returns:
      All HWID requirement candidates.  If a HWID string is covered by the
      specified pattern and fulfills at least one of the returned requirement,
      the HWID string is considered compatible for the versioned feature.

    Raises:
      HWIDDBNotSupportError: If the HWID DB scheme is incompatible to any of
        the underlying spec implementation.
    """
    per_spec_requirement_candidates = []
    for requirement_resolver in self._requirement_resolvers:
      result = requirement_resolver.DeduceRequirementCandidates(
          self._db, pattern_idx, self._dlm_db)
      if not result:
        return []
      if result is _ALWAYS_FULFILL:
        continue
      per_spec_requirement_candidates.append(result)

    if not per_spec_requirement_candidates:
      return [HWIDRequirement(description='', bit_string_prerequisites=[])]

    indices_with_multiple_requirement_candidates = [
        i for i, candidates in enumerate(per_spec_requirement_candidates)
        if len(candidates) > 1
    ]

    result_hwid_requirement_candidates = []
    for bit_string_requirements in itertools.product(
        *per_spec_requirement_candidates):
      if indices_with_multiple_requirement_candidates:
        description = 'variant=' + ','.join(
            f'({bit_string_requirements[i].description})'
            for i in indices_with_multiple_requirement_candidates)
      else:
        description = ''
      result_hwid_requirement_candidates.append(
          HWIDRequirement(description=description,
                          bit_string_prerequisites=bit_string_requirements))
    return result_hwid_requirement_candidates


class HWIDRequirementResolver:
  """Of a specific feature version, it deduces the HWID requirement."""

  def __init__(self, specs: Sequence[HWIDSpec]):
    """Initializer.

    Args:
      specs: The specs of the target versioned feature.
    """
    self._spec = specs

  def _GetImageIDRequirement(
      self, image_ids: Collection[int]) -> HWIDBitStringRequirement:
    return HWIDBitStringRequirement(
        description='image_id', bit_positions=tuple(
            range(hwid_common.HEADER_BIT_LENGTH - 1, -1, -1)),
        required_values=image_ids)

  def DeduceHWIDRequirementCandidates(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Collection[HWIDRequirement]:
    """Deduces all HWID requirement candidates.

    A HWID string is considered versioned feature compatible only if it fulfills
    at least one requirement.

    Args:
      db: The HWID DB to check.
      dlm_db: The DLM entry database that contains component's properties.

    Returns:
      All candidates of HWID requirements.

    Raises:
      HWIDDBNotSupportError: If the HWID DB scheme is incompatible to any of
        the underlying spec implementation.
    """
    image_ids_of_pattern_idx = collections.defaultdict(list)
    for image_id in db.image_ids:
      pattern_idx = db.GetPattern(image_id=image_id).idx
      image_ids_of_pattern_idx[pattern_idx].append(image_id)

    helper = _HWIDRequirementResolverForEncodedFieldPart(self._spec, db, dlm_db)

    all_requirements = []
    for pattern_idx, image_ids in image_ids_of_pattern_idx.items():
      image_id_prerequisites = [self._GetImageIDRequirement(image_ids)]
      for candidate in helper.DeduceHWIDRequirementCandidates(pattern_idx):
        description = f'pattern_idx={pattern_idx}'
        if candidate.description:
          description = f'{description},{candidate.description}'
        all_requirements.append(
            HWIDRequirement(
                description=description, bit_string_prerequisites=tuple(
                    itertools.chain(image_id_prerequisites,
                                    candidate.bit_string_prerequisites))))
    return all_requirements


class _SatisfiedEncodedValueResolver(abc.ABC):
  """A class method to help find all satisfied encoded values for a spec."""

  def __init__(self, db: db_module.Database, dlm_db: DLMComponentDatabase):
    self._db = db
    self._dlm_db = dlm_db
    self._compatibility_of_hwid_component = {}
    self._compatibility_of_dlm_id = {}
    self._name_pattern_adapter = npa_module.NamePatternAdapter()
    self._name_patterns = {}

  @abc.abstractmethod
  def _IdentifyDLMComponentCompatibility(self,
                                         dlm_entry: DLMComponentEntry) -> bool:
    """Checks whether the given DLM entry is a feature-compatible one.

    Args:
      dlm_entry: The DLM component entry.

    Returns:
      Whether the entry is feature-compatible.
    """
    raise NotImplementedError

  @classmethod
  @abc.abstractmethod
  def _GetComponentTypesToCheck(cls) -> Collection[str]:
    """Returns all HWID component types to check."""

  def _IsDLMComponentCompatible(self, dlm_id: DLMComponentEntryID) -> bool:
    cached_value = self._compatibility_of_dlm_id.get(dlm_id)
    if cached_value is not None:
      return cached_value
    dlm_entry = self._dlm_db.get(dlm_id)
    is_compatible = (False if not dlm_entry else
                     self._IdentifyDLMComponentCompatibility(dlm_entry))
    self._compatibility_of_dlm_id[dlm_id] = is_compatible
    return is_compatible

  def _IsHWIDComponentCompatible(self, component_type: str,
                                 component_name: str) -> bool:
    cache_key = (component_type, component_name)
    cached_answer = self._compatibility_of_hwid_component.get(cache_key)
    if cached_answer is not None:
      return cached_answer

    if component_type not in self._name_patterns:
      self._name_patterns[component_type] = (
          self._name_pattern_adapter.GetNamePattern(component_type))
    name_info = self._name_patterns[component_type].Matches(component_name)
    if not name_info:
      is_compatible = False
    else:
      dlm_id = DLMComponentEntryID(cid=name_info.cid, qid=name_info.qid or None)
      is_compatible = self._IsDLMComponentCompatible(dlm_id)
    self._compatibility_of_hwid_component[cache_key] = is_compatible
    return is_compatible

  def FindSatisfiedEncodedValues(self) -> Mapping[str, Collection[int]]:
    """Finds and returns all HWID encoded values that satisfy the spec.

    See `HWIDSpec.FindSatisfiedEncodedValues` for more details.

    Returns:
      See `HWIDSpec.FindSatisfiedEncodedValues` for more details.
    """
    field_values = collections.defaultdict(set)
    component_types = self._GetComponentTypesToCheck()
    for field_name in self._db.encoded_fields:
      for field_value, comps in self._db.GetEncodedField(field_name).items():
        if any(self._IsHWIDComponentCompatible(component_type, component_name)
               for component_type in component_types
               for component_name in comps.get(component_type, [])):
          field_values[field_name].add(field_value)
    return field_values


class CPUV1Spec(HWIDSpec):
  """Holds the CPU spec for feature v1.

  It states that the HWID is compatible to v1 feature only if the encoded
  CPU has the corresponding `1` listed in the `compatible_versions` on DLM.
  """

  class _CPUV1SatisfiedEncodedFieldValueResolver(
      _SatisfiedEncodedValueResolver):
    _TARGET_VERSION = 1
    _CPU_COMPONENT_TYPE = 'cpu'

    @classmethod
    def _GetComponentTypesToCheck(cls) -> Collection[str]:
      """See base class."""
      return (cls._CPU_COMPONENT_TYPE, )

    def _IdentifyDLMComponentCompatibility(
        self, dlm_entry: DLMComponentEntry) -> bool:
      """See base class."""
      return bool(dlm_entry.cpu_property) and (
          self._TARGET_VERSION in dlm_entry.cpu_property.compatible_versions)

  def GetName(self) -> str:
    return 'CPUv1'

  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """See base class."""
    resolver = self._CPUV1SatisfiedEncodedFieldValueResolver(db, dlm_db)
    return resolver.FindSatisfiedEncodedValues()
