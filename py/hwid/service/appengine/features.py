# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import collections
import enum
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


class VirtualDIMMProperty(NamedTuple):
  """Holds virtual DIMM properties related to versioned features.

  Attributes:
    size_in_mb: The DIMM size in MB.
  """
  size_in_mb: int


class StorageFunctionProperty(NamedTuple):
  """Holds storage function properties related to versioned features.

  Attributes:
    size_in_gb: The storage size in GB.
  """
  size_in_gb: int


class DisplayPanelType(enum.Enum):
  """Enumerates the known display panel types."""
  TN = enum.auto()
  OTHER = enum.auto()


class DisplayProperty(NamedTuple):
  """Holds display panel properties related to versioned features.

  Attributes:
    panel_type: The panel type.
    horizontal_resolution: The horizontal resolution in pixel.
    vertical_resolution: The vertical resolution in pixel.
  """
  panel_type: DisplayPanelType
  horizontal_resolution: int
  vertical_resolution: int


class CameraProperty(NamedTuple):
  """Holds camera properties related to versioned features.

  Attributes:
    is_user_facing: Whether this camera is user facing on the device.
    has_tnr: Whether the TNR feature is enabled.
    horizontal_resolution: The horizontal resolution in pixel.
    vertical_resolution: The vertical resolution in pixel.
  """
  is_user_facing: bool
  has_tnr: bool
  horizontal_resolution: int
  vertical_resolution: int


class DLMComponentEntry(NamedTuple):
  """Represents one single DLM component entry.

  Attributes:
    dlm_id: The entry ID.
    cpu_property: The CPU related properties if the entry supports the CPU
      functionality.
    virtual_dimm_property: The DIMM related properties if the entry supports the
      DRAM functionality (e.g. DRAM module / DRAM chip / eMCP).
    storage_function_property: The storage related properties if the entry
      supports the mass storage functionality (e.g. eMMC, NVMe,
      eMMC+eMMC_PCIe assembly).
    display_panel_property: The display panel properties if the entry supports
      the display functionality.
    camera_property: The camera properties if the entry supports the camera
      functionality.
  """
  dlm_id: DLMComponentEntryID
  cpu_property: Optional[CPUProperty]
  virtual_dimm_property: Optional[VirtualDIMMProperty]
  storage_function_property: Optional[StorageFunctionProperty]
  display_panel_property: Optional[DisplayProperty]
  camera_property: Optional[CameraProperty]


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


class MemoryV1Spec(HWIDSpec):
  """Holds the DRAM spec for feature v1.

  It states that the HWID is compatible to v1 feature only if the DRAM encoded
  field shows that the total memory size is 8GB or more.
  """

  _MIN_MEMORY_SIZE_IN_MB = 1024 * 8
  _DRAM_FIELD_NAME = 'dram_field'
  _DRAM_COMPONENT_TYPE = 'dram'

  def __init__(self):
    self._name_pattern = npa_module.NamePatternAdapter().GetNamePattern(
        self._DRAM_COMPONENT_TYPE)

  def _GetVirtualDIMMSizeInMB(self, hwid_component_name: str,
                              dlm_db: DLMComponentDatabase) -> int:
    name_info = self._name_pattern.Matches(hwid_component_name)
    if not name_info:
      return 0
    dlm_id = DLMComponentEntryID(name_info.cid, name_info.qid or None)
    if dlm_id not in dlm_db or not dlm_db[dlm_id].virtual_dimm_property:
      return 0
    return dlm_db[dlm_id].virtual_dimm_property.size_in_mb

  def GetName(self) -> str:
    return 'MemoryV1'

  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """See base class."""
    if self._DRAM_FIELD_NAME not in db.encoded_fields:
      return {}

    compliant_encoded_values = []
    for encoded_value, component_combo in db.GetEncodedField(
        self._DRAM_FIELD_NAME).items():
      if (len(component_combo) != 1 or
          self._DRAM_COMPONENT_TYPE not in component_combo):
        raise HWIDDBNotSupportError(
            f'Unexpected components in {self._DRAM_FIELD_NAME} in HWID DB.')
      total_memory_size = sum(
          self._GetVirtualDIMMSizeInMB(comp_name, dlm_db)
          for comp_name in component_combo[self._DRAM_COMPONENT_TYPE])
      if total_memory_size >= self._MIN_MEMORY_SIZE_IN_MB:
        compliant_encoded_values.append(encoded_value)

    return ({
        self._DRAM_FIELD_NAME: compliant_encoded_values
    } if compliant_encoded_values else {})


class StorageV1Spec(HWIDSpec):
  """Holds the storage spec for feature v1.

  It states that the HWID is compatible to v1 feature only if the storage size
  is at least 128GB.
  """

  class _StorageV1SatisfiedEncodedFieldValueResolver(
      _SatisfiedEncodedValueResolver):
    _STORAGE_COMPONENT_TYPES = ('storage', 'storage_bridge')
    _MIN_STORAGE_SIZE_IN_GB = 128

    @classmethod
    def _GetComponentTypesToCheck(cls) -> Collection[str]:
      """See base class."""
      return cls._STORAGE_COMPONENT_TYPES

    def _IdentifyDLMComponentCompatibility(
        self, dlm_entry: DLMComponentEntry) -> bool:
      """See base class."""
      return bool(dlm_entry.storage_function_property) and (
          dlm_entry.storage_function_property.size_in_gb >=
          self._MIN_STORAGE_SIZE_IN_GB)

  def GetName(self) -> str:
    return 'StorageV1'

  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """See base class."""
    resolver = self._StorageV1SatisfiedEncodedFieldValueResolver(db, dlm_db)
    return resolver.FindSatisfiedEncodedValues()


class DisplayPanelV1Spec(HWIDSpec):
  """Holds the display panel spec for feature v1.

  It states that the HWID is compatible to v1 feature only if the display panel
  resolution is FHD or above and also the panel type must not be TN.
  """

  class _DisplayV1SatisfiedEncodedFieldValueResolver(
      _SatisfiedEncodedValueResolver):
    _DISPLAY_COMPONENT_TYPE = 'display_panel'
    _FHD_HORIZONTAL_RESOLUTION = 1920
    _FHD_VERTICAL_RESOLUTION = 1080

    @classmethod
    def _GetComponentTypesToCheck(cls) -> Collection[str]:
      """See base class."""
      return (cls._DISPLAY_COMPONENT_TYPE, )

    def _IdentifyDLMComponentCompatibility(
        self, dlm_entry: DLMComponentEntry) -> bool:
      """See base class."""
      if not dlm_entry.display_panel_property:
        return False
      properties = dlm_entry.display_panel_property
      return all((
          properties.panel_type != DisplayPanelType.TN,
          properties.horizontal_resolution >= self._FHD_HORIZONTAL_RESOLUTION,
          properties.vertical_resolution >= self._FHD_VERTICAL_RESOLUTION,
      ))

  def GetName(self) -> str:
    return 'DisplayPanelV1'

  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """See base class."""
    resolver = self._DisplayV1SatisfiedEncodedFieldValueResolver(db, dlm_db)
    return resolver.FindSatisfiedEncodedValues()


class CameraV1Spec(HWIDSpec):
  """Holds the camera spec for feature v1.

  It states that the HWID is compatible to v1 feature only if the UFC camera
  is FHD or above and has TNR enabled.
  """

  class _CameraV1SatisfiedEncodedFieldValueResolver(
      _SatisfiedEncodedValueResolver):
    _CAMERA_COMPONENT_TYPES = ('camera', 'video')
    _MIN_HORIZONTAL_RESOLUTION = 1920
    _MIN_VERTICAL_RESOLUTION = 1080

    @classmethod
    def _GetComponentTypesToCheck(cls) -> Collection[str]:
      """See base class."""
      return cls._CAMERA_COMPONENT_TYPES

    def _IdentifyDLMComponentCompatibility(
        self, dlm_entry: DLMComponentEntry) -> bool:
      """See base class."""
      if not dlm_entry.camera_property:
        return False
      properties = dlm_entry.camera_property
      return all((
          properties.has_tnr,
          properties.is_user_facing,
          properties.horizontal_resolution >= self._MIN_HORIZONTAL_RESOLUTION,
          properties.vertical_resolution >= self._MIN_VERTICAL_RESOLUTION,
      ))

  def GetName(self) -> str:
    return 'CameraV1'

  def FindSatisfiedEncodedValues(
      self, db: db_module.Database,
      dlm_db: DLMComponentDatabase) -> Mapping[str, Collection[int]]:
    """See base class."""
    resolver = self._CameraV1SatisfiedEncodedFieldValueResolver(db, dlm_db)
    return resolver.FindSatisfiedEncodedValues()


class V1HWIDRequirementResolver(HWIDRequirementResolver):
  """The HWID requirement resolver for feature v1."""

  def __init__(self):
    """Initializer."""
    super().__init__((CPUV1Spec, MemoryV1Spec, StorageV1Spec,
                      DisplayPanelV1Spec, CameraV1Spec))
