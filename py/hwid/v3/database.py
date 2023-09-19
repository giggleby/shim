# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Database classes for HWID v3 operation.

The HWID database for a Chromebook project defines how to generate (or
to say, encode) a HWID encoded string for the Chromebook.  The HWID database
contains many parts:

  1. `components` lists information of all hardware components.
  2. `encoded_fields` maps each hardware component's name to a number to be
     encoded into the HWID encoded string.
  3. `pattern` records the ways to union all numbers together to form an unique
     fixed-bit-length number which responses to a set of hardware components.
     `pattern` records many different ways to union numbers because the
     bit-length of the number might not be enough after new hardware
     components are added into the Database.
  4. `image_id` lists all possible image ids.  An image id consists of an
     index (start from 0) and a human-readable name.  The name of an image id
     often looks similar to the factory build stage, but it's not necessary.
     There's an one-to-one mapping relation between the index of an image id
     and the pattern so that we know which pattern to apply for encode/decode
     the numbers/HWID encode string.
  5. `encoded_patterns` is a reserved bit and it can only be 0 now.
  6. `project` records the name of the Chromebook project.
  7. `checksum` records a checksum string to make sure that the Database is not
     modified.
  8. `rules` records a list of rules to be evaluated during generating the HWID
     encoded string.

This package implements some basic methods for manipulating a HWID database
and the loader to load the database from a file.  The classes in this package
represents to each part of the HWID database listed above.  The detail of
each part is described in the class' document.
"""

import abc
import collections
import copy
import enum
import hashlib
import itertools
import logging
import re
from typing import Any, DefaultDict, List, Mapping, MutableMapping, NamedTuple, Optional, Sequence, Set, Tuple, Union

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import rule as v3_rule
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import file_utils
from cros.factory.utils import schema
from cros.factory.utils import type_utils


_DUMMY_CHECKSUM = 'DUMMY'


class MagicPlaceholderComponentOptions(NamedTuple):
  """Options to replace a component name and status by magic placeholders."""
  # If set, it specifies the replacement for the component name.
  magic_component_name: Optional[str]
  # If set, it specifies the replacement for the component support status.
  magic_support_status: Optional[str]


class MagicPlaceholderOptions(NamedTuple):
  """Options to replace some parts of HWID DB payload by magic placeholders."""
  # Magic placeholder options for component names and status.  It maps
  # the (component_class, component_name) to the option class.
  components: Mapping[Tuple[str, str], MagicPlaceholderComponentOptions]


class BitEntry(NamedTuple):
  field: str
  bit_offset: int


class PatternField(NamedTuple):
  name: str
  bit_length: int


class PatternDatum(NamedTuple):
  idx: int
  encoding_scheme: str
  fields: Sequence[PatternField]


class ComponentInfo:

  def __init__(self, values: Optional[Mapping[str, Any]],
               status: Union[str, common.ComponentStatus],
               information: Optional[Mapping[str, Any]] = None,
               bundle_uuids: Optional[Sequence[str]] = None):
    self._values = values
    # Casts status to str type for avoiding yaml dump error.
    self._status = str(status)
    self._information = information
    self._bundle_uuids = bundle_uuids or []
    self._comp_hash = hashlib.sha1(
        yaml.safe_dump(
            self.Export(sort_values_by_key=True), default_flow_style=False,
            internal=True).encode('utf8')).hexdigest()

  def __eq__(self, rhs: Any) -> bool:
    return (self._values == rhs._values and self._status == rhs._status and
            self._information == rhs._information and
            set(self._bundle_uuids) == set(rhs._bundle_uuids))

  def Export(self, suppress_support_status: bool = False,
             override_support_status: Optional[str] = None,
             is_default_comp: bool = False, sort_values_by_key: bool = False):

    def _ExportDict(values):
      if not sort_values_by_key:
        return values
      if v3_rule.IsComponentValueNone(values):
        return None
      sorted_values = yaml.Dict(sorted(values.items()))
      if not isinstance(values, v3_rule.AVLProbeValue):
        return sorted_values
      return v3_rule.AVLProbeValue(values.converter_identifier,
                                   values.probe_value_matched, sorted_values)

    if self.bundle_uuids:
      component_dict = v3_rule.FromFactoryBundle(self.bundle_uuids)
    else:
      component_dict = yaml.Dict()
    if not suppress_support_status or (self._status !=
                                       common.ComponentStatus.supported):
      component_dict['status'] = override_support_status or self._status
    component_dict['values'] = _ExportDict(self._values)
    if is_default_comp:
      component_dict['default'] = True
    if self._information:
      component_dict['information'] = _ExportDict(self._information)
    return component_dict

  def Replace(self, **kwargs) -> 'ComponentInfo':
    """Creates a new ComponentInfo instance with optional replaced fields."""
    return ComponentInfo(
        kwargs.get('values', self.values), kwargs.get('status', self.status),
        kwargs.get('information', self.information),
        kwargs.get('bundle_uuids', self.bundle_uuids))

  @property
  def values(self) -> Optional[Mapping[str, Any]]:
    return self._values

  @property
  def status(self) -> str:
    return self._status

  @property
  def information(self) -> Optional[Mapping[str, Any]]:
    return self._information

  @property
  def comp_hash(self) -> str:
    return self._comp_hash

  @property
  def bundle_uuids(self) -> Sequence[str]:
    return self._bundle_uuids

  @property
  def value_is_none(self) -> bool:
    return v3_rule.IsComponentValueNone(self._values)


class Database(abc.ABC):
  """A class for reading in, parsing, and obtaining information of the given
  device-specific component database.

  Attributes:
    _project: A string indicating the project name.
    _encoding_patterns: An EncodingPatterns object.
    _image_id: An ImageId object.
    _pattern: A Pattern object.
    _encoded_fields: An EncodedFields object.
    _components: A Components object.
    _rules: A Rules object.
    _checksum: None or a string of the value of the checksum field.
    _framework_version: An integer of the framework version.
  """

  @abc.abstractmethod
  def __init__(self, project: str, encoding_patterns: 'EncodingPatterns',
               image_id: 'ImageId', pattern: 'Pattern',
               encoded_fields: 'EncodedFields', components: 'Components',
               rules: 'Rules', checksum: Optional[str], framework_version: int):
    """Constructor.

    This constructor should be only called by subclasses.
    """
    super().__init__()
    self._project = project
    self._encoding_patterns = encoding_patterns
    self._image_id = image_id
    self._pattern = pattern
    self._encoded_fields = encoded_fields
    self._components = components
    self._rules = rules
    self._checksum = checksum
    self._framework_version = framework_version

    self._SanityChecks()

  def __eq__(self, rhs):
    return (isinstance(rhs, Database) and self._project == rhs._project and
            self._encoding_patterns == rhs._encoding_patterns and
            self._image_id == rhs._image_id and
            self._pattern == rhs._pattern and
            self._encoded_fields == rhs._encoded_fields and
            self._components == rhs._components and
            self._rules == rhs._rules and
            self._framework_version == rhs._framework_version)

  def __ne__(self, rhs):
    return not self == rhs

  @classmethod
  def LoadFile(cls, file_name: str, verify_checksum: bool = True) -> 'Database':
    """Loads a device-specific component database from the given file and
    parses it to a Database object.

    Args:
      file_name: A path to a device-specific component database.
      verify_checksum: Whether to verify the checksum of the database.

    Returns:
      A Database object containing all the settings in the database file.

    Raises:
      HWIDException if there is missing field in the database.
    """
    return cls.LoadData(
        file_utils.ReadFile(file_name),
        expected_checksum=(cls.Checksum(file_name)
                           if verify_checksum else None))

  @classmethod
  def Checksum(cls, file_name: str) -> str:
    """Computes a SHA1 digest as the checksum of the given database file.

    Args:
      file_name: A path to a device-specific component database.

    Returns:
      The computed checksum as a string.
    """
    return cls.ChecksumForText(file_utils.ReadFile(file_name))

  @classmethod
  def ChecksumForText(cls, db_text: str) -> str:
    """Computes a SHA1 digest as the checksum of the given database string.

    Args:
      db_text: The database as a string.

    Returns:
      The computed checksum as a string.
    """
    # Ignore the 'checksum: <hash value>\n' line when calculating checksum.
    db_text = re.sub(r'^checksum:.*$\n?', '', db_text, flags=re.MULTILINE)
    return hashlib.sha1(db_text.encode('utf-8')).hexdigest()

  @classmethod
  def LoadData(cls, raw_data: str,
               expected_checksum: Optional[str] = None) -> 'Database':
    """Loads a device-specific component database from the given database data.

    Args:
      raw_data: The database in string.
      expected_checksum: The checksum value to verify the loaded data with.
          A value of None disables checksum verification.

    Returns:
      A Database object containing all the settings in the database file.

    Raises:
      HWIDException if there is missing field in the database, or database
      integrity verification fails.
    """
    return WritableDatabase.LoadData(raw_data, expected_checksum)

  def DumpDataWithoutChecksum(
      self, suppress_support_status: bool = True,
      magic_placeholder_options: Optional[MagicPlaceholderOptions] = None,
      internal: bool = False) -> str:
    all_parts = [
        ('checksum', _DUMMY_CHECKSUM),
        ('project', self._project),
        ('encoding_patterns', self._encoding_patterns.Export()),
        ('image_id', self._image_id.Export()),
        ('pattern', self._pattern.Export()),
        ('encoded_fields',
         self._encoded_fields.Export(magic_placeholder_options)),
        ('components',
         self._components.Export(suppress_support_status,
                                 magic_placeholder_options)),
        ('rules', self._rules.Export()),
    ]
    if self._framework_version != common.OLDEST_FRAMEWORK_VERSION:
      all_parts.append(('framework_version', self._framework_version))

    return '\n'.join([
        yaml.safe_dump({key: value}, default_flow_style=False,
                       internal=internal) for key, value in all_parts
    ])

  def DumpFileWithoutChecksum(self, path: str, internal: bool = False):
    file_utils.WriteFile(path, self.DumpDataWithoutChecksum(internal=internal))

  @property
  def can_encode(self) -> bool:
    return self._components.can_encode and self._encoded_fields.can_encode

  @property
  def region_field_legacy_info(self) -> Mapping[str, bool]:
    return self._encoded_fields.region_field_legacy_info

  @property
  def project(self) -> str:
    return self._project

  @property
  def checksum(self) -> Optional[str]:
    return self._checksum

  @property
  def encoding_patterns(self) -> Sequence[int]:
    return list(self._encoding_patterns)

  @property
  def image_ids(self) -> Sequence[int]:
    return list(self._image_id)

  @property
  def max_image_id(self) -> int:
    return self._image_id.max_image_id

  @property
  def rma_image_id(self) -> Optional[int]:
    return self._image_id.rma_image_id

  @property
  def is_initial(self) -> bool:
    return not self.GetPattern(pattern_idx=0).fields

  def GetImageName(self, image_id: int) -> str:
    return self._image_id[image_id]

  def GetImageIdByName(self, image_name: str) -> int:
    return self._image_id.GetImageIdByName(image_name)

  def GetEncodingScheme(self, image_id: Optional[int] = None) -> str:
    return self._pattern.GetEncodingScheme(image_id)

  def GetTotalBitLength(self, image_id: Optional[int] = None) -> int:
    return self._pattern.GetTotalBitLength(image_id=image_id)

  def GetEncodedFieldsBitLength(
      self, image_id: Optional[int] = None,
      pattern_idx: Optional[int] = None) -> Mapping[str, int]:
    return self._pattern.GetFieldsBitLength(image_id=image_id,
                                            pattern_idx=pattern_idx)

  def GetBitMapping(self, image_id: Optional[int] = None,
                    pattern_idx: Optional[int] = None,
                    max_bit_length: Optional[int] = None) -> Sequence[BitEntry]:
    # TODO(yhong): Consider move `GetBitMapping()` and other similar methods
    #    into `PatternDatum` class to separate the logic of identifying the
    #    pattern out from the rest tasks.
    return self._pattern.GetBitMapping(image_id=image_id,
                                       pattern_idx=pattern_idx,
                                       max_bit_length=max_bit_length)

  def GetPattern(self, image_id: Optional[int] = None,
                 pattern_idx: Optional[int] = None) -> PatternDatum:
    """Get the pattern by the given image id or the pattern's numerical index.

    Args:
      image_id: An integer of the image id to query.  If not given, the latest
          image id would be used.
      pattern_idx: The index of the pattern.

    Returns:
      The `PatternDatum` object.
    """
    return self._pattern.GetPattern(image_id=image_id, pattern_idx=pattern_idx)

  def GetPatternCount(self) -> int:
    return self._pattern.num_patterns

  @property
  def encoded_fields(self) -> Sequence[str]:
    return self._encoded_fields.encoded_fields

  def GetEncodedField(
      self, encoded_field_name) -> Mapping[int, Mapping[str, Sequence[str]]]:
    return self._encoded_fields.GetField(encoded_field_name)

  def GetComponentClasses(self, encoded_field_name: Optional[str] = None,
                          image_id: Optional[int] = None) -> Set[str]:
    """Returns a set of component class names with optional conditions.

    If `encoded_field_name` or `image_id` is specified, this function only
    returns the component classes which will be encoded by the specific encoded
    field or image_id.
    If both `encoded_field_name` and `image_id` are not specified, this function
    returns all component classes recorded by the database.

    Note that the iteration order of the return value may differ between two
    python script runs.

    Args:
      encoded_field_name: None of a string of the name of the encoded field.
      image_id: An optional image id to restrict the component classes visible
        at that image. Not filter if set to None.

    Returns:
      A set of component class names.

    Raises:
      HWIDException when both encoded_field_name and image_id are set.
    """
    if encoded_field_name and image_id is not None:
      raise common.HWIDException(
          '`encoded_field_name` and `image_id` cannot be set at the same time.')

    if encoded_field_name:
      return self._encoded_fields.GetComponentClasses(encoded_field_name)

    if image_id is not None:
      return {
          comp_cls
          for encoded_field_name in self._pattern.GetFieldsBitLength(image_id)
          for comp_cls in self._encoded_fields.GetComponentClasses(
              encoded_field_name)
      }

    ret = set(self._components.component_classes)
    for e in self.encoded_fields:
      ret |= set(self._encoded_fields.GetComponentClasses(e))

    return ret

  def GetEncodedFieldForComponent(self, comp_cls: str) -> Optional[str]:
    return self._encoded_fields.GetFieldForComponent(comp_cls)

  def GetComponents(
      self, comp_cls: str,
      include_default: bool = True) -> Mapping[str, ComponentInfo]:
    """Gets the components of the specific component class.

    Args:
      comp_cls: A string of the name of the component class.
      include_default: True to include the default component (the component
          which values is `None` instead of a dictionary) in the return
          components.

    Returns:
      A dict which maps a string of component name to a `ComponentInfo` object,
      which is a named tuple contains two attributes:
        values: A string-to-string dict of expected probed results.
        status: One of `common.ComponentStatus`.
        information: optional dict, these data will be used to further help
                     Runtime Probe and Hardware Verifier have more information
                     to handle miscellaneous probe issues.
    """
    comps = self._components.GetComponents(comp_cls)
    if not include_default:
      comps = {
          name: info
          for name, info in comps.items()
          if not info.value_is_none
      }
    return comps

  def GetDefaultComponent(self, comp_cls: str) -> Optional[str]:
    return self._components.GetDefaultComponent(comp_cls)

  @property
  def device_info_rules(self) -> Sequence[v3_rule.Rule]:
    return self._rules.device_info_rules

  @property
  def verify_rules(self) -> Sequence[v3_rule.Rule]:
    return self._rules.verify_rules

  def GetActiveComponentClasses(self,
                                image_id: Optional[int] = None) -> Set[str]:
    ret = set()
    for encoded_field_name in self.GetEncodedFieldsBitLength(
        image_id=image_id).keys():
      ret |= self.GetComponentClasses(encoded_field_name)

    return ret

  def GetComponentNameByHash(self, comp_cls: str, comp_hash: str) -> str:
    return self._components.GetComponentNameByHash(comp_cls, comp_hash)

  def GetRegionComponents(self) -> Mapping[str, ComponentInfo]:
    region_comps = self._components.GetComponents('region')
    ret = {}
    for region_field_name, is_legacy in self.region_field_legacy_info.items():
      if is_legacy:
        continue
      for region in self.GetEncodedField(region_field_name).values():
        for region_name in region['region']:
          ret[region_name] = region_comps[region_name]
    return ret

  @property
  def framework_version(self) -> int:
    return self._framework_version

  def _SanityChecks(self):
    # Each image id should have a corresponding pattern.
    if set(self.image_ids) != set(self._pattern.all_image_ids):
      raise common.HWIDException(
          'Each image id should have a corresponding pattern.')

    # Encoded fields should be well defined.
    for image_id in self.image_ids:
      for encoded_field_name in self.GetEncodedFieldsBitLength(
          image_id=image_id):
        if encoded_field_name not in self.encoded_fields:
          raise common.HWIDException(
              f'The encoded field {encoded_field_name!r} is not defined in '
              '`encoded_fields` part.')
    # The last encoded patterns should always contain enough bits for all
    # fields.
    for encoded_field_name, bit_length in self.GetEncodedFieldsBitLength(
        image_id=self.max_image_id).items():
      max_index = max(self.GetEncodedField(encoded_field_name))
      if max_index.bit_length() > bit_length:
        raise common.HWIDException(
            f'Number of allocated bits ({int(bit_length)}) for field '
            f'{encoded_field_name!r} is not enough in the encoded patterns for '
            f'image id {self.max_image_id!r}')
    # TODO(yhong): Perform stricter check against the encoded fields that are
    #     excluded in the latest encoded pattern.  Currently it's allowed as
    #     this feature is often applied to solve exceptional HWID submission
    #     flows like b/124414887.

    # Each encoded field should be well defined.
    for encoded_field_name in self.encoded_fields:
      for comps in self.GetEncodedField(encoded_field_name).values():
        for comp_cls, comp_names in comps.items():
          missing_comp_names = (
              set(comp_names) - set(self.GetComponents(comp_cls).keys()))
          if missing_comp_names:
            raise common.HWIDException(
                f'The components {missing_comp_names!r} are not defined in '
                '`components` part.')

    # Only initial DB could have empty bit patterns.
    has_empty_field = any(not self.GetPattern(pattern_idx=i).fields
                          for i in range(self.GetPatternCount()))
    if has_empty_field:
      if self.GetPatternCount() > 1:
        raise common.HWIDException(
            'Only initial DB could have empty bit patterns.')
      if self.image_ids != [0]:
        raise common.HWIDException(
            'Only image id 0 is allowed in an initial DB.')


class WritableDatabase(Database):

  # Override the abstract method from parent class on purpose.
  # pylint: disable=useless-super-delegation
  def __init__(self, project: str, encoding_patterns: 'EncodingPatterns',
               image_id: 'ImageId', pattern: 'Pattern',
               encoded_fields: 'EncodedFields', components: 'Components',
               rules: 'Rules', checksum: Optional[str], framework_version: int):
    """Initializer.

    This constructor should not be called by other modules.
    """
    super().__init__(project, encoding_patterns, image_id, pattern,
                     encoded_fields, components, rules, checksum,
                     framework_version)

  @classmethod
  def LoadFile(cls, file_name: str,
               verify_checksum: bool = True) -> 'WritableDatabase':
    """Loads a device-specific component database from the given file and
    parses it to a WritableDatabase object.

    Args:
      file_name: A path to a device-specific component database.
      verify_checksum: Whether to verify the checksum of the database.

    Returns:
      A WritableDatabase object containing all the settings in the database
      file.

    Raises:
      HWIDException if there is missing field in the database.
    """
    return cls.LoadData(
        file_utils.ReadFile(file_name),
        expected_checksum=(cls.Checksum(file_name)
                           if verify_checksum else None))

  @classmethod
  def LoadData(cls, raw_data: str,
               expected_checksum: Optional[str] = None) -> 'WritableDatabase':
    """Loads a device-specific component database from the given database data.

    Args:
      raw_data: The database in string.
      expected_checksum: The checksum value to verify the loaded data with.
          A value of None disables checksum verification.

    Returns:
      A WritableDatabase object containing all the settings in the database
      file.

    Raises:
      HWIDException if there is missing field in the database, or database
      integrity verification fails.
    """
    yaml_obj = yaml.safe_load(raw_data)

    if not isinstance(yaml_obj, dict):
      raise common.HWIDException('Invalid HWID database')

    if 'board' in yaml_obj and 'project' not in yaml_obj:
      yaml_obj['project'] = yaml_obj['board']

    for key in [
        'project', 'encoding_patterns', 'image_id', 'pattern', 'encoded_fields',
        'components', 'rules', 'checksum'
    ]:
      if key not in yaml_obj:
        raise common.HWIDException(f'{key!r} is not specified in HWID database')

    project = yaml_obj['project'].upper()
    if project != yaml_obj['project']:
      logging.warning('The project name should be in upper cases, but got %r.',
                      yaml_obj['project'])

    # Verify database integrity.
    if (expected_checksum is not None and
        yaml_obj['checksum'] != expected_checksum):
      raise common.HWIDException(
          f'HWID database {project!r} checksum verification failed')

    return cls(
        project, EncodingPatterns(yaml_obj['encoding_patterns']),
        ImageId(yaml_obj['image_id']), Pattern(yaml_obj['pattern']),
        EncodedFields(yaml_obj['encoded_fields']),
        Components(yaml_obj['components']), Rules(yaml_obj['rules']),
        yaml_obj.get('checksum'),
        yaml_obj.get('framework_version', common.OLDEST_FRAMEWORK_VERSION))

  def AddImage(self, image_id: int, image_name: str, encoding_scheme: str,
               new_pattern: bool = False,
               reference_image_id: Optional[int] = None,
               pattern_idx: Optional[int] = None) -> int:
    """Adds an image associated with an optionally new pattern.

    Args:
      image_id: The image id.
      image_name: The image name.
      encoding_scheme: The encoding scheme.
      new_pattern: A bool indicating if this image points to a new pattern.
      reference_image_id: The optional image id of the pattern this new image id
        will be associated with.
      pattern_idx: The optional index of pattern this new image id will be
        associated with.
    Returns:
      The associated pattern index.
    """
    if new_pattern:
      if pattern_idx is not None or reference_image_id is not None:
        raise ValueError('None of image_id and reference_image_id can be set '
                         'when new_pattern is set to True.')
      associated_pattern_idx = self._pattern.AddEmptyPattern(
          image_id, encoding_scheme)
    else:
      if pattern_idx is not None and reference_image_id is not None:
        # Both pattern_idx and reference_image_id are set.
        raise ValueError(
            'At most one of pattern_idx and reference_image_id can be set.')
      if pattern_idx is not None:
        associated_pattern_idx = self._pattern.AddImageId(
            image_id, pattern_idx=pattern_idx)
      elif reference_image_id is not None:
        associated_pattern_idx = self._pattern.AddImageId(
            image_id, reference_image_id=reference_image_id)
      else:  # Both are None, use max image id.
        associated_pattern_idx = self._pattern.AddImageId(
            image_id, reference_image_id=self.max_image_id)

    self._image_id[image_id] = image_name
    return associated_pattern_idx

  def AppendEncodedFieldBit(self, field_name: str, bit_length: int,
                            image_id: Optional[int] = None,
                            pattern_idx: Optional[int] = None):
    """Adds bits to a encoded field in a pattern.

    Args:
      field_name: The encoded field name.
      bit_length: The bit length to append to the specific pattern.
      image_id: The optional image id of the pattern.
      pattern_idx: The optional index of the pattern.
    """
    if field_name not in self.encoded_fields:
      raise common.HWIDException(f'The field {field_name!r} does not exist.')

    self._pattern.AppendField(field_name, bit_length, image_id=image_id,
                              pattern_idx=pattern_idx)

  def AddNewEncodedField(self, encoded_field_name: str,
                         components: Mapping[str, Sequence[str]]):
    self._VerifyEncodedFieldComponents(components)

    self._encoded_fields.AddNewField(encoded_field_name, components)

  def AddEncodedFieldComponents(self, encoded_field_name: str,
                                components: Mapping[str, Sequence[str]]):
    """Adds a combination of components in encoded fields.

    Args:
      encoded_field_name: The encoded field name.
      components: A mapping of comp_cls to a combination of components.
    """
    self._VerifyEncodedFieldComponents(components)

    self._encoded_fields.AddFieldComponents(encoded_field_name, components)

  def AddComponent(self, comp_cls: str, comp_name: str,
                   value: Mapping[str, Any], status: str,
                   information: Optional[Mapping[str, str]] = None):
    return self._components.AddComponent(comp_cls, comp_name, value, status,
                                         information)

  def SetComponentStatus(self, comp_cls: str, comp_name: str, status: str):
    return self._components.SetComponentStatus(comp_cls, comp_name, status)

  def SetLinkAVLProbeValue(self, comp_cls: str, comp_name: str,
                           converter_identifier: Optional[str],
                           probe_value_matched: bool):
    return self._components.SetLinkAVLProbeValue(
        comp_cls, comp_name, converter_identifier, probe_value_matched)

  def SetBundleUUIDs(self, comp_cls: str, comp_name: str,
                     bundle_uuids: Sequence[str]):
    return self._components.SetBundleUUIDs(comp_cls, comp_name, bundle_uuids)

  def UpdateComponent(self, comp_cls: str, old_name: str, new_name: str,
                      values: Optional[Mapping[str, Any]], support_status: str,
                      information: Optional[Mapping[str, Any]] = None,
                      bundle_uuids: Optional[Sequence[str]] = None):
    """Updates a component by name.

    This method will also update the component names in the encoded fields.

    Args:
      comp_cls: The component class name.
      old_name: The component name of the component to be updated.
      new_name: The updated component name.
      values: A dict of the probed results or None if the component is updated
        to a null component.
      support_status: One of `common.ComponentStatus`.
      information: Optional dict, these data will be used to further help
          Runtime Probe and Hardware Verifier have more information to handle
          miscellaneous probe issues.
      bundle_uuids: Optional list, indicate the uuid of which factory bundle
          extract this component.
    """
    self._components.UpdateComponent(comp_cls, old_name, new_name, values,
                                     support_status, information, bundle_uuids)
    if old_name != new_name:  # Update encoded_fields as well.
      self._encoded_fields.RenameComponent(comp_cls, old_name, new_name)

  def AddDeviceInfoRule(self, name_suffix, evaluate, **kwargs):
    self._rules.AddDeviceInfoRule(name_suffix, evaluate, **kwargs)

  def ReplaceRules(self, rule_expr_list: Mapping[str, Any]):
    """Replaces the entries in rules section.

    Args:
      rule_expr_list: A mapping of rules.
    """
    self._rules = Rules(rule_expr_list)

  def RenameImages(self, image_name_mapping: Mapping[int, str]):
    """Renames images according to the given mapping.

    This method renames images according to image_name_mapping.

    Args:
      image_name_mapping: The mapping of image IDs to desired image names.

    Raises:
      common.HWIDException if the given image ids does not exist.
    """
    unexpected_image_ids = set(image_name_mapping) - set(self._image_id)
    if unexpected_image_ids:
      raise common.HWIDException(
          f'Images ID(s) do not exist: {unexpected_image_ids}.')
    renamed = dict(self._image_id)
    renamed.update(image_name_mapping)
    self._image_id = ImageId(renamed)

  @property
  def raw_encoding_patterns(self):
    return self._encoding_patterns

  @property
  def raw_image_id(self):
    return self._image_id

  @property
  def raw_pattern(self):
    return self._pattern

  @property
  def raw_encoded_fields(self):
    return self._encoded_fields

  @property
  def raw_components(self):
    return self._components

  @property
  def raw_rules(self):
    return self._rules

  @property
  def framework_version(self) -> int:
    return self._framework_version

  @framework_version.setter
  def framework_version(self, new_framework_version: int):
    self._framework_version = new_framework_version

  def SanityChecks(self):
    self._SanityChecks()

  def _VerifyEncodedFieldComponents(self, components):
    for comp_cls, comp_names in components.items():
      for comp_name in comp_names:
        if comp_name not in self.GetComponents(comp_cls):
          raise common.HWIDException(
              f'The component {comp_name!r} is not recorded in `components` '
              'part.')


class _NamedNumber(dict):
  """A customized dictionary for `encoding_patterns` and `image_id` parts.

  This class limits some features of the build-in dict to keep the HWID
  database valid.  The restrictions are:
    1. Key of this dictionary must be an integer.
    2. Value of this dictionary must be an unique string.
    3. Existed key-value cannot be modified or be removed.
  """

  PART_TAG: Optional[str] = None
  NUMBER_RANGE: Optional[Sequence[int]] = None
  NUMBER_TAG: Optional[str] = None
  NAME_TAG: Optional[str] = None

  def __init__(self, source):
    super().__init__()

    if not isinstance(source, dict):
      raise common.HWIDException(
          f'Invalid source {source!r} for `{self.PART_TAG}` part of a HWID '
          'database.')

    for number, name in source.items():
      self[number] = name

  def Export(self):
    """Exports to a dictionary which can be saved into the database file."""
    return dict(self)

  def __getitem__(self, number):
    """Gets the name of the specific number.

    Raises:
      common.HWIDException if the given number is not recorded.
    """
    try:
      return super().__getitem__(number)
    except KeyError:
      raise common.HWIDException(
          f'The {self.NUMBER_TAG} {number!r} is not recorded.') from None

  def __setitem__(self, number, name):
    """Adds a new number or updates an existed number's name.

    Raises:
      common.HWIDException if failed.
    """
    # pylint:disable=unsupported-membership-test
    if number not in self.NUMBER_RANGE:
      raise common.HWIDException(
          f'The {self.NUMBER_TAG} should be one of {self.NUMBER_RANGE!r}, but '
          f'got {number!r}.')

    if not isinstance(name, str):
      raise common.HWIDException(
          f'The {self.NAME_TAG} should be a string, but got {name!r}.')

    if number in self:
      raise common.HWIDException(
          f'The {self.NUMBER_TAG} {number!r} already exists.')

    if name in self.values():
      raise common.HWIDException(
          f'The {self.NAME_TAG} {name!r} is already in used.')

    super().__setitem__(number, name)

  def __delitem__(self, key):
    raise common.HWIDException(
        f'Invalid operation: remove {self.NUMBER_TAG} {key!r}.')


class EncodingPatterns(_NamedNumber):
  """Class for holding `encoding_patterns` part in a HWID database.

  `encoding_patterns` part records all encoding pattern ids and their unique
  name.

  An encoding pattern id is either 0 or 1 (1 bit in width).  But since the
  encoding method is not defined for the encoding pattern id being 1, this
  value now can only be 0.

  In the HWID database file, `encoding_patterns` part looks like:

  ```yaml
  encoding_patterns:
    0: default  # 0 is the encoding pattern id, "default" is the
                # encoding pattern name.

  ```
  """
  PART_TAG = 'encoding_patterns'
  NUMBER_RANGE = [0]
  NUMBER_TAG = 'encoding pattern id'
  NAME_TAG = 'encoding pattern name'


class ImageId(_NamedNumber):
  """Class for holding `image_id` part in a HWID database.

  `image_id` part in a HWID database records all image ids and their name.

  An image id is an integer between 0~15 (4 bits in width).  Each image id has
  an unique name (called image name) in string.  This class is a dictionary
  mapping each image id to the corresponding image name.

  In the HWID database file, `image_id` part looks like:

  ```yaml
  image_id:
    0: PROTO    # 0 is the image id, "PROTO" is the image name.
    1: EVT      # 1 is another image id.
    2: EVT-99
    3: WA_LALA
    ...

  ```
  """
  PART_TAG = 'image_id'
  NUMBER_RANGE = list(range(1 << common.IMAGE_ID_BIT_LENGTH))
  NUMBER_TAG = 'image id'
  NAME_TAG = 'image name'

  RMA_IMAGE_ID = max(NUMBER_RANGE)
  """Preserve the max image ID for RMA pattern."""

  def GetImageIdByName(self, image_name):
    """Returns the image id of the given image name.

    Raises:
      common.HWIDException if the image id is not found.
    """
    for i, name in self.items():
      if name == image_name:
        return i

    raise common.HWIDException(f'The image name {image_name!r} is not valid.')

  @property
  def max_image_id(self):
    """Returns the maximum image id."""
    return self.GetMaxImageIDFromList(list(self))

  @property
  def rma_image_id(self):
    return self.GetRMAImageIDFromList(list(self))

  @classmethod
  def GetMaxImageIDFromList(cls, image_ids):
    return max(set(image_ids) - {cls.RMA_IMAGE_ID})

  @classmethod
  def GetRMAImageIDFromList(cls, image_ids):
    if cls.RMA_IMAGE_ID in image_ids:
      return cls.RMA_IMAGE_ID
    return None


class EncodedFields:
  """Class for holding `encoded_fields` part of a HWID database.

  `encoded_fields` part of a HWID database defines the way to convert
  hardware components to numbers (and then `pattern` part defines way to union
  all numbers (each encoded field generates a number) together).

  `encoded_fields` defines a set of encoded field.  Each encoded field contains
  a set of numbers.  A number then maps to a hardware component, or a set
  of hardware components.  For example, in the HWID database file, this part
  might look like:

  ```yaml
  encoded_fields:
    wireless_field:
      0:
        wireless: super_cool_wireless_component
      1:
        wireless: not_so_good_component
    dram_field:
      0:
        dram:
        - ram_4g_1
        - ram_4g_2
      1:
        dram:
        - ram_8g_1
        - ram_8g_2
    firmware_field:
      0:
        ec_firmware: ec_rev0
        main_firmware: main_rev0
      1:
        ec_firmware: ec_rev0
        main_firmware: main_rev1
      2:
        ec_firmware: ec_rev0
        main_firmware: main_rev2
    chassis_field:
      0:
        chassis: COOL_CHASSIS_ID
  ```
  If the Chromebook installs the wireless chip `super_cool_wireless_component`,
  the corresponding number of `wireless_field` is 0.  `dram_field` above is
  more tricky, 0 means two 4G ram being installed on the Chromebook; 1 means
  two 8G ram being installed on the Chromebook.  If the probed results tell
  us that one 4G and one 8G rams are installed, the program will fail to
  generate the HWID identity because the combination of dram doesn't meet
  any case.

  A number represents to a combination of a set of components, and it's even
  okey to be a set of different class of components like `firmware_field` in
  above example.  But for each class of components, it should belong to one
  `encoded_field`.  For example, below `encoded_fields` is invalid:

  ```yaml
  encoded_fields:
    aaa_field:
      0:
        class1: comp1
    bbb_field:
      0:
        class1: comp2
      1:
        class1: comp3
  ```

  The relationship between the encoded fields and the classes of components
  should form a `one-to-multi` mapping.

  Properties:
    _fields: A dictionary maps the encoded field name to the component
        combinations, which maps the encode index to a component combination.
        The component combination is a dictionary which maps the component
        class name to a list of component names.
    _field_to_comp_classes: A dictionary maps the encoded field name to a set
        of component class.
    _can_encode: True if this part works for encoding a BOM to the HWID string.
        Somehow there are some old, existed HWID databases which has an encoded
        field which maps two different indexes into exactly same component
        combinations.  In above case the database still works for decoding,
        but not encoding.
    _region_field_legacy_info: A dictionary that records whether it's legacy
        style of each region field.
  """

  _SCHEMA = schema.Dict(
      'encoded fields',
      key_type=schema.Scalar('field name', str),
      value_type=schema.Dict(
          'encoded field',
          key_type=schema.Scalar(
              'index number',
              int,
              # list(range(1024)) is just a big enough range to denote
              # that index numbers are non-negative integers.
              list(range(1024))),
          value_type=schema.Dict(
              'components', key_type=schema.Scalar('component class', str),
              value_type=schema.AnyOf([
                  schema.Scalar('empty list', type(None)),
                  schema.Scalar('component name', str),
                  schema.List('list of component name',
                              element_type=schema.Scalar('component name', str))
              ])),
          min_size=1))

  def __init__(self, encoded_fields_expr):
    """Initializer.

    This constructor shouldn't be called by other modules.
    """
    self._SCHEMA.Validate(encoded_fields_expr)

    # Verify the input by constructing the encoded fields from scratch
    # because all checks are implemented in the manipulating methods.
    self._fields = yaml.Dict()
    self._field_to_comp_classes = {}
    self._can_encode = True
    self._region_field_legacy_info = {}

    for field_name, field_data in encoded_fields_expr.items():
      if isinstance(field_data, yaml.RegionField):
        self._region_field_legacy_info[field_name] = field_data.is_legacy_style
      self._RegisterNewEmptyField(field_name,
                                  list(next(iter(field_data.values()))))
      for index, comps in field_data.items():
        comps = yaml.Dict(
            [(c, self._StandardlizeList(n)) for c, n in comps.items()])
        self.AddFieldComponents(field_name, comps, _index=index)

    # Preserve the class type reported by the parser.
    self._fields = copy.deepcopy(encoded_fields_expr)

  def __eq__(self, rhs):
    return isinstance(rhs, EncodedFields) and self._fields == rhs._fields

  def __ne__(self, rhs):
    return not self == rhs

  @property
  def can_encode(self):
    return self._can_encode

  @property
  def region_field_legacy_info(self):
    return self._region_field_legacy_info

  def Export(self, magic_placeholder_options):
    """Exports to a dictionary so that it can be stored to the database file."""
    if magic_placeholder_options is None:
      return self._fields
    copied_fields = copy.deepcopy(self._fields)
    for comp_combination in itertools.chain.from_iterable(
        index_table.values() for index_table in copied_fields.values()):
      for comp_cls in comp_combination:
        comp_names = self._StandardlizeList(comp_combination[comp_cls])
        modified = False
        for i, comp_name in enumerate(comp_names):
          try:
            magic_component_name = magic_placeholder_options.components[(
                comp_cls, comp_name)].magic_component_name
            if magic_component_name is not None:
              comp_names[i] = magic_component_name
              modified = True
          except KeyError:
            pass
        if modified:
          comp_combination[comp_cls] = self._SimplifyList(comp_names)
    return copied_fields

  @property
  def encoded_fields(self):
    """Returns a list of encoded field names."""
    return list(self._fields)

  def GetField(self, field_name):
    """Gets the specific field.

    Args:
      field_name: A string of the name of the encoded field.

    Returns:
      A dictionary which maps each index number to the corresponding components
          combination (i.e. A dictionary of component class to a list of
          component names).
    """
    if field_name not in self._fields:
      raise common.HWIDException(f'The field name {field_name!r} is invalid.')

    ret: MutableMapping[int, Mapping[str, Sequence[str]]] = {}
    for index, comps in self._fields[field_name].items():
      ret[index] = {c: self._StandardlizeList(n)
                    for c, n in comps.items()}
    return ret

  def GetComponentClasses(self, field_name):
    """Gets the related component classes of a specific field.

    Args:
      field_name: A string of the name of the encoded field.

    Returns:
      A set of string of component classes.
    """
    if field_name not in self._fields:
      raise common.HWIDException(f'The field name {field_name!r} is invalid.')

    return self._field_to_comp_classes[field_name]

  def GetFieldForComponent(self, comp_cls):
    """Gets the field which encodes the specific component class.

    Args:
      comp_cls: A string of the component class.

    Returns:
      None if no field for that; otherwise a string of the field name.
    """
    for field_name, comp_cls_set in self._field_to_comp_classes.items():
      if comp_cls in comp_cls_set:
        return field_name
    return None

  def GetFieldsForComponent(self, comp_cls):
    """Gets the fields which encode the specific component class.

    Args:
      comp_cls: A string of the component class.

    Returns:
      List of field names including this component class.
    """
    return [
        field_name
        for field_name, comp_cls_set in self._field_to_comp_classes.items()
        if comp_cls in comp_cls_set
    ]

  def AddFieldComponents(self, field_name, components, _index=None):
    """Adds components combination to an existing encoded field.

    Args:
      field_name: A string of the name of the new encoded field.
      components: A dictionary which maps the component class to a list of
          component name.
      _index: Specify the index for the new component combination.
    """
    if field_name not in self._fields:
      raise common.HWIDException(f'Encoded field {field_name!r} does not exist')

    if field_name == 'region_field':
      if len(components) != 1 or list(components) != ['region']:
        raise common.HWIDException(
            'Region field should contain only region component.')

    if set(components.keys()) != self._field_to_comp_classes[field_name]:
      raise common.HWIDException('Each encoded field should encode a fixed set '
                                 'of component classes.')

    counters = {c: collections.Counter(n)
                for c, n in components.items()}
    for existing_index, existing_comps in self.GetField(field_name).items():
      if all(counter == collections.Counter(existing_comps[comp_cls])
             for comp_cls, counter in counters.items()):
        self._can_encode = False
        logging.warning(
            'The components combination %r already exists (at index %r).',
            components, existing_index)

    index = (
        _index if _index is not None else
        max(self._fields[field_name].keys() or [-1]) + 1)
    self._fields[field_name][index] = yaml.Dict(
        sorted([(c, self._SimplifyList(n)) for c, n in components.items()]))

  def AddNewField(self, field_name, components):
    """Adds a new field.

    Args:
      field_name: A string of the name of the new field.
      components: A dictionary which maps the component class to a list of
          component name.
    """
    if field_name in self._fields:
      raise common.HWIDException(f'Encoded field {field_name!r} already exists')

    if field_name == 'region_field' or 'region' in components:
      raise common.HWIDException(
          'Region field should always exist in the HWID database, it is '
          'prohibited to add a new field called "region_field".')

    self._RegisterNewEmptyField(field_name, list(components))

    self.AddFieldComponents(field_name, components)

  def RenameComponent(self, comp_cls: str, old_name: str, new_name: str):
    """Renames a component in encoded fields.

    Args:
      comp_cls: A string of the name of the component class.
      old_name: The component name to be updated.
      new_name: The updated component name.
    """

    field_names = self.GetFieldsForComponent(comp_cls)
    if not field_names:
      raise common.HWIDException(f'Comp class {comp_cls!r} not found in '
                                 'encoded fields')
    for field_name in field_names:
      for combination in self._fields[field_name].values():
        comp_names = self._StandardlizeList(combination[comp_cls])
        combination[comp_cls] = self._SimplifyList([
            new_name if comp_name == old_name else comp_name
            for comp_name in comp_names
        ])

  def _RegisterNewEmptyField(self, field_name, comp_classes):
    if not comp_classes:
      raise common.HWIDException(
          'An encoded field must includes at least one component class.')

    self._fields[field_name] = yaml.Dict()
    self._field_to_comp_classes[field_name] = set(comp_classes)

  @classmethod
  def _SimplifyList(cls, data):
    if not data:
      return None
    if len(data) == 1:
      return data[0]

    return sorted(data)

  @classmethod
  def _StandardlizeList(cls, data):
    return sorted(type_utils.MakeList(data)) if data is not None else []


class ComponentsStore(yaml.Dict):
  """A dictionary which supports looking up component name by the hash value of
  component info."""

  def __init__(self, comp_cls: str, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._comp_cls = comp_cls
    self._hash_mapping: MutableMapping[str, str] = {}

  def __setitem__(self, comp_name: str, val: ComponentInfo):
    if comp_name in self:
      self._hash_mapping.pop(self[comp_name].comp_hash, None)
    self._hash_mapping[val.comp_hash] = comp_name
    super().__setitem__(comp_name, val)

  def GetComponentNameByHash(self, comp_hash: str):
    return self._hash_mapping[comp_hash]

  def UpdateComponent(self, old_name: str, new_name: str,
                      new_comp_info: ComponentInfo):
    if old_name not in self:
      raise common.HWIDException(
          f'No such Component ({self._comp_cls!r}, {old_name!r}).')

    if old_name == new_name:  # Update in-place.
      self[old_name] = new_comp_info
    else:
      if new_name in self:
        raise common.HWIDException('Updated Component already exists '
                                   f'({self._comp_cls!r}, {new_name!r}).')
      # OrderedDict does not support updating key-value pair in-place without
      # modifying the order, so it's required to update the list of items and
      # update the dict.
      comp_list = list(self.items())
      self.clear()
      for idx, (comp_name, old_comp_info) in enumerate(comp_list):
        if comp_name == old_name:
          self._hash_mapping.pop(old_comp_info.comp_hash, None)
          comp_list[idx] = (new_name, new_comp_info)
          self._hash_mapping[new_comp_info.comp_hash] = new_name
          break
      self.update(comp_list)

  def __reduce__(self):
    state = list(super().__reduce__())
    state[1] = (self._comp_cls, ) + state[1]
    return tuple(state)


class Components:
  """Class for holding `components` part in a HWID database.

  `components` part in a HWID database records information of all components
  which might be found on the device.

  In the HWID database file, `components` part looks like:

  ```yaml
  components:
    <comonent_class_1_name>:
      items:
        <component_name>:
          value: <a_dict_of_expected_probed_result_values>|null
          status: unsupported|deprecated|unqualified|supported|duplicate
        <component_name>:
          value: <a_dict_of_expected_probed_result_values>
          status: unsupported|deprecated|unqualified|supported|duplicate
          information:
            comp_group: other_group_name
            alias: component name alias
        ...
    ...
  ```

  For example, it might look like:

  ```yaml
  components:
    battery:
      items:
        battery_small:
          status: deprecated
          values:
            tech: Battery Li-ion
            size: '2500000'
        battery_medium:
          status: unqualified
          values:
            tech: Battery Li-ion
            size: '123456789'
          information:
            comp_group: battery_regular
            alias: battery_vendor_a

    cellular:
      items:
        cellular_default:
          values: null
        cellular_0:
          values:
            idVendor: 89ab
            idProduct: abcd
            name: Cellular Card
  ```

  In above example, when we probe the battery of the device, if the probed
  result values contains {'tech': 'Battery Li-ion', size: '123456789'}, we
  consider as there's a component named "battery_small" installed on the device.

  A special case is "value: null", this means the component is a
  "default component".  In early build, sometime maybe the driver is not ready
  so we have to set a default component to mark that those device actually
  have the component.

  Valid status are: supported, unqualified, deprecated, unsupported and
  duplicate.  Each value has its own meaning:
    * supported: This component is currently being used to build new units and
          allowed to be used in later build (PVT and later).
    * unqualified: The component is acceptable to be installed on the device in
          early normal build (before PVT, not included).
    * deprecated: This component is no longer being used to build new units,
          but is supported in RMA process.
    * unsupported: This component is not allowed to be used to build new units,
          and is not supported in RMA process.
    * duplicate: This component has been merged into another component.  This
          component won't be used to encode new HWID, but can still be used to
          decode.
  If not specified, status defaults to supported.

  After probing all kind of components, it results in a BOM list, which records
  a list of names of the installed components.  Then we generate the HWID
  encoded string by looking up the encoded fields to transfer the BOM list
  into numbers and union them.

  Attributes:
    _components: A dictionary which maps the component class name to a list
        of ComponentInfo object.
    _can_encode: True if the original data doesn't contain legacy information
        so that the whole database works for encoding a BOM to the HWID string.
        As the idea of non-probeable components are deprecated and the idea of
        default components are approached by rules, the HWID database contains
        non-probeable or default components will be mark as _can_encode=False.
    _default_comonents: A set of default components.
    _non_probeable_component_classes: A set of name of the non-probeable
        component class.
  """
  _SCHEMA = schema.Dict(
      'components', key_type=schema.Scalar('component class', str),
      value_type=schema.FixedDict(
          'component description', items={
              'items':
                  schema.Dict(
                      'components', key_type=schema.Scalar(
                          'component name', str),
                      value_type=schema.FixedDict(
                          'component attributes', items={
                              'values':
                                  schema.AnyOf([
                                      schema.Dict(
                                          'probed key-value pairs',
                                          key_type=schema.Scalar(
                                              'probed key', str),
                                          value_type=schema.AnyOf([
                                              schema.Scalar(
                                                  'probed value', str),
                                              schema.Scalar(
                                                  'probed value', bytes),
                                              schema.Scalar(
                                                  'probed value regex',
                                                  v3_rule.Value)
                                          ]), min_size=1),
                                      schema.Scalar('none', type(None))
                                  ])
                          }, optional_items={
                              'default':
                                  schema.Scalar(
                                      'is default component item (deprecated)',
                                      bool),
                              'status':
                                  schema.Scalar('item status', str,
                                                choices=common.ComponentStatus),
                              'information':
                                  schema.AnyOf([
                                      schema.Dict(
                                          'extra information',
                                          key_type=schema.Scalar(
                                              'info key',
                                              str), value_type=schema.Scalar(
                                                  'info value', str)),
                                      schema.Scalar('none', type(None))
                                  ]),
                          }))
          }, optional_items={
              'probeable':
                  schema.Scalar('is component probeable (deprecate)', bool)
          }))

  _DUMMY_KEY = 'dummy_probed_value_key'

  def __init__(self, components_expr):
    """Constructor.

    This constructor shouldn't be called by other modules.
    """
    # To avoid failing validation when values is None wrapped by AVLProbeValue,
    # we only validate the external format.
    external_components_expr = yaml.safe_load(
        yaml.safe_dump(components_expr, default_flow_style=False))
    self._SCHEMA.Validate(external_components_expr)

    self._region_component_expr = copy.deepcopy(components_expr.get('region'))
    self._components = yaml.Dict()

    self._can_encode = True
    self._default_components = set()
    self._non_probeable_component_classes = set()

    for comp_cls, comps_data in components_expr.items():
      self._components[comp_cls] = ComponentsStore(comp_cls)
      for comp_name, comp_attr in comps_data['items'].items():
        self._AddComponent(
            comp_cls, comp_name, comp_attr['values'],
            comp_attr.get('status', common.ComponentStatus.supported),
            comp_attr.get('information'))

        if comp_attr.get('default') is True:
          # We now use "values: null" to indicate a default component and
          # ignore the "default: True" field.
          self._default_components.add((comp_cls, comp_name))

        if isinstance(comp_attr, v3_rule.FromFactoryBundle):
          self.SetBundleUUIDs(comp_cls, comp_name, comp_attr.bundle_uuids)

      if comps_data.get('probeable') is False:
        logging.info(
            'Found non-probeable component class %r, mark can_encode=False.',
            comp_cls)
        self._can_encode = False
        self._non_probeable_component_classes.add(comp_cls)

  def __eq__(self, rhs):
    return isinstance(rhs, Components) and self._components == rhs._components

  def __ne__(self, rhs):
    return not self == rhs

  def Export(self, suppress_support_status, magic_placeholder_options):
    """Exports into a serializable dictionary which can be stored into a HWID
    database file."""
    components_expr = yaml.Dict()
    magic_placeholder_comps = (
        magic_placeholder_options.components
        if magic_placeholder_options else {})
    for comp_cls in self.component_classes:
      if comp_cls == 'region':
        components_expr[comp_cls] = self._region_component_expr
        continue
      components_expr[comp_cls] = yaml.Dict()
      if comp_cls in self._non_probeable_component_classes:
        components_expr[comp_cls]['probeable'] = False
      components_dict = components_expr[comp_cls]['items'] = yaml.Dict()
      for comp_name, comp_info in self.GetComponents(comp_cls).items():
        try:
          replace_info = magic_placeholder_comps[(comp_cls, comp_name)]
        except KeyError:
          comp_name_in_expr = comp_name
          support_status = comp_info.status
        else:
          comp_name_in_expr = replace_info.magic_component_name
          support_status = replace_info.magic_support_status
        is_default_comp = (comp_cls, comp_name) in self._default_components
        components_dict[comp_name_in_expr] = comp_info.Export(
            suppress_support_status, support_status, is_default_comp)
    return components_expr

  @property
  def can_encode(self):
    """Returns true if the components is not the legacy one which let the whole
    database unable to encode the BOM."""
    return self._can_encode

  @property
  def component_classes(self):
    """Returns a list of string of the component class names."""
    return list(self._components)

  def GetComponents(self, comp_cls):
    """Gets the components of the specific component class.

    Args:
      comp_cls: A string of the name of the component class.

    Returns:
      A dict which maps a string of component name to a `ComponentInfo` object,
      which is a named tuple contains two attributes:
        values: A string-to-string dict of expected probed results.
        status: One of `common.ComponentStatus`.
        information: optional dict, these data will be used to further help
                     Runtime Probe and Hardware Verifier have more information
                     to handle miscellaneous probe issues.
    """
    return self._components.get(comp_cls, {})

  def GetComponentNameByHash(self, comp_cls: str, comp_hash: str) -> str:
    return self._components[comp_cls].GetComponentNameByHash(comp_hash)

  def GetDefaultComponent(self, comp_cls):
    """Gets the default components of the specific component class if exists.

    Args:
      comp_cls: A string of the name of the component class.

    Returns:
      None or a string of the component name.
    """
    for comp_name, comp_info in self._components.get(comp_cls, {}).items():
      if comp_info.value_is_none:
        return comp_name
    return None

  def AddComponent(self, comp_cls, comp_name, values, status, information=None):
    """Adds a new component.

    Args:
      comp_cls: A string of the component class.
      comp_name: A string of the name of the component.
      values: A dict of the expected probed results.
      status: One of `common.ComponentStatus`.
      information: optional dict, these data will be used to further help
          Runtime Probe and Hardware Verifier have more information to handle
          miscellaneous probe issues.
    """
    if comp_cls == 'region':
      raise common.HWIDException('Region component class is not modifiable.')

    self._AddComponent(comp_cls, comp_name, values, status, information)

  def SetComponentStatus(self, comp_cls, comp_name, status):
    """Sets the status of a specific component.

    Args:
      comp_cls: The component class name.
      comp_name: The component name.
      status: One of `common.ComponentStatus`.
    """
    if comp_cls == 'region':
      raise common.HWIDException('Region component class is not modifiable.')

    self._SCHEMA.value_type.items['items'].value_type.optional_items[
        'status'].Validate(status)

    if comp_name not in self._components.get(comp_cls, {}):
      raise common.HWIDException(
          f'Component ({comp_cls!r}, {comp_name!r}) is not recorded.')

    comp_info = self._components[comp_cls][comp_name]
    self._components[comp_cls][comp_name] = comp_info.Replace(status=status)

  def _AddComponent(self, comp_cls, comp_name, values, status, information):
    # To avoid failing validation when values is None wrapped by AVLProbeValue,
    # we only validate the external format.
    external_values = yaml.safe_load(
        yaml.safe_dump(values, default_flow_style=False))
    self._SCHEMA.value_type.items['items'].value_type.items['values'].Validate(
        external_values)
    self._SCHEMA.value_type.items['items'].value_type.optional_items[
        'status'].Validate(status)
    self._SCHEMA.value_type.items['items'].value_type.optional_items[
        'information'].Validate(information)

    if comp_name in self.GetComponents(comp_cls):
      raise common.HWIDException(
          f'Component ({comp_cls!r}, {comp_name!r}) already exists.')

    value_is_none = v3_rule.IsComponentValueNone(values)
    if value_is_none and any(
        c.values is None for c in self.GetComponents(comp_cls).values()):
      logging.warning(
          'Found more than one default component of %r, '
          'mark can_encode=False.', comp_cls)
      self._can_encode = False

    for existed_comp_name, existed_comp_info in self.GetComponents(
        comp_cls).items():
      existed_comp_values = existed_comp_info.values
      # At here, we only complain if two components are exactly the same.  There
      # is another case that is not caught here: at least one of the component
      # is using regular expression, and the intersection of two components is
      # not empty set.  Currently,
      # `cros.factory.hwid.v3.probe.GenerateBOMFromProbedResults` will raise an
      # exception when the probed result indeed matches two or more components.
      if values == existed_comp_values:
        if common.ComponentStatus.duplicate not in (status,
                                                    existed_comp_info.status):
          logging.warning('Probed values %r is ambiguous with %r', values,
                          existed_comp_name)
          logging.warning('Did you merge two components? You should set status '
                          'of the duplicate one "duplicate".')
          self._can_encode = False

    self._components.setdefault(comp_cls, ComponentsStore(comp_cls))
    self._components[comp_cls][comp_name] = ComponentInfo(
        values, status, information)

  def SetLinkAVLProbeValue(self, comp_cls: str, comp_name: str,
                           converter_identifier: Optional[str],
                           probe_value_matched: bool):
    """Sets the tag of the component as !link_avl

    Args:
      comp_cls: The component class name.
      comp_name: The component name.
      converter_identifier: The AVL converter identifier, None if no converter
          is available.
      probe_value_matched: A bool indicating whether the probe value of the
          component matches the values in AVL.
    """
    if comp_cls == 'region':
      raise common.HWIDException('Region component class is not modifiable.')

    if comp_name not in self._components.get(comp_cls, {}):
      raise common.HWIDException(
          f'Component ({comp_cls!r}, {comp_name!r}) is not recorded.')

    comp_info = self._components[comp_cls][comp_name]

    values = None if comp_info.value_is_none else comp_info.values
    self._components[comp_cls][comp_name] = comp_info.Replace(
        values=v3_rule.AVLProbeValue(converter_identifier, probe_value_matched,
                                     values))

  def SetBundleUUIDs(self, comp_cls: str, comp_name: str,
                     bundle_uuids: Sequence[str]):
    """Set uuid of factory bundles to the component"""
    comp_info = self._components[comp_cls][comp_name]
    self._components[comp_cls][comp_name] = comp_info.Replace(
        bundle_uuids=bundle_uuids)

  def UpdateComponent(self, comp_cls: str, old_name: str, new_name: str,
                      values: Optional[Mapping[str, Any]], support_status: str,
                      information: Optional[Mapping[str, Any]] = None,
                      bundle_uuids: Optional[Sequence[str]] = None):
    """Updates a component by name.

    This method will also update the component names in the encoded fields.

    Args:
      comp_cls: The component class name.
      old_name: The component name of the component to be updated.
      new_name: The updated component name.
      values: A dict of the probed results or None if the component is updated
        to a null component.
      support_status: One of `common.ComponentStatus`.
      information: Optional dict, these data will be used to further help
          Runtime Probe and Hardware Verifier have more information to handle
          miscellaneous probe issues.
      bundle_uuids: Optional list, indicate the uuid of which factory bundle
          extract this component.
    """
    self._SCHEMA.value_type.items['items'].value_type.items['values'].Validate(
        values)
    self._SCHEMA.value_type.items['items'].value_type.optional_items[
        'status'].Validate(support_status)
    self._SCHEMA.value_type.items['items'].value_type.optional_items[
        'information'].Validate(information)
    self._components[comp_cls].UpdateComponent(
        old_name, new_name,
        ComponentInfo(values, support_status, information, bundle_uuids))


class Pattern:
  """A class for parsing and obtaining information of a pre-defined encoding
  pattern.

  The `pattern` part of a HWID database records a list of patterns.  Each
  pattern records:
    1. `image_ids`: A list of image id for this pattern.  When we are decoding
       a HWID identity, we will use the pattern which `image_ids` field
       includes the image id in the HWID identity.
    2. `encoding_scheme`: Either "base32" or "base8192".  This is the name of
       the algorithm to encoding/decoding the binary string.
    3. `fields`: Bit positions of each type of components.  Since the hardware
       component might be added into the HWID database in anytime and we can
       only append extra bits to the components bitset at the end so that
       old HWID identity can be decoded by the same pattern, the index number
       of the installed component might have to be split into multiple part
       when we union all numbers into a big binary string.  For example, if the
       `fields` defines:

       ```yaml
       - battery: 2
       - cpu: 1
       - battery 3
       ```

       Then the first 2 bits of the components bitset are the least 2 bits of
       the index of the battery.  The 4~6 bits of the components bitset are the
       3~5 bits of the index of the battery.  Here is the corresponding mapping
       between the components bitset and the index of the battery of above
       example.  (note that the bit for cpu is marked as "?" because it is not
       related to the battery.)

         bitset  battery_index    bitset  battery_index
         00?000  0                00?100  16
         01?000  1                01?100  17
         10?000  2                10?100  18
         11?000  3                11?100  19
         00?001  4                00?101  20
         01?001  5                01?101  21
         10?001  6                10?101  22
         11?001  7                11?101  23
         00?010  8                00?110  24
         01?010  9                01?110  25
         10?010  10               10?110  26
         11?010  11               11?110  27
         00?011  12               00?111  28
         01?011  13               01?111  29
         10?011  14               10?111  30
         11?011  15               11?111  31

  The format of `pattern` part in the HWID database file is:

  ```yaml
  pattern:
  - image_ids: <a_list_of_image_ids>
  - encoding_scheme: <base32_or_base8192>
  - fields:
    - <component_class_name>: <number_of_bits>
    - <component_class_name>: <number_of_bits>
    ...

  - image_ids: <a_list_of_image_ids>
  - encoding_scheme: <base32_or_base8192>
  - fields:
    - <component_class_name>: <number_of_bits>
    - <component_class_name>: <number_of_bits>
    ...
  ...

  ```

  """

  _SCHEMA = schema.List(
      'pattern list', element_type=schema.FixedDict(
          'pattern', items={
              'image_ids':
                  schema.List(
                      'image ids', element_type=schema.Scalar(
                          'image id', int, choices=ImageId.NUMBER_RANGE),
                      min_length=1),
              'encoding_scheme':
                  schema.Scalar('encoding scheme', str,
                                choices=common.EncodingScheme),
              'fields':
                  schema.List(
                      'encoded fields',
                      schema.Dict(
                          'pattern field', key_type=schema.Scalar(
                              'encoded index', str), value_type=schema.Scalar(
                                  'bit offset', int, list(range(128))),
                          min_size=1, max_size=1))
          }), min_length=1)

  def __init__(self, pattern_list_expr):
    """Constructor.

    This constructor shouldn't be called by other modules.
    """
    self._SCHEMA.Validate(pattern_list_expr)

    self._image_id_to_pattern: MutableMapping[int, int] = {}
    self._patterns = []

    for pattern_expr in pattern_list_expr:
      pattern_obj = PatternDatum(self.num_patterns,
                                 pattern_expr['encoding_scheme'], [])
      for field_expr in pattern_expr['fields']:
        pattern_obj.fields.append(
            PatternField(list(field_expr)[0], next(iter(field_expr.values()))))

      for image_id in pattern_expr['image_ids']:
        if image_id in self._image_id_to_pattern:
          raise common.HWIDException(
              'One image id should map to one pattern, but image id '
              f'{image_id!r} maps to multiple patterns.')

        self._image_id_to_pattern[image_id] = self.num_patterns
      self._patterns.append(pattern_obj)

  def __eq__(self, rhs):
    return (isinstance(rhs, Pattern) and
            self._image_id_to_pattern == rhs._image_id_to_pattern and
            self._patterns == rhs._patterns)

  def __ne__(self, rhs):
    return not self == rhs

  def Export(self):
    """Exports this `pattern` part of HWID database into a serializable object
    which can be stored into a HWID database file."""
    inverse_mapping: DefaultDict[int, List[int]] = collections.defaultdict(list)
    for image_id, pattern_idx in self._image_id_to_pattern.items():
      inverse_mapping[pattern_idx].append(image_id)

    pattern_list = []
    for seq, pattern in enumerate(self._patterns):
      pattern_list.append(
          yaml.Dict([('image_ids', inverse_mapping[seq]),
                     ('encoding_scheme', pattern.encoding_scheme),
                     ('fields', [{
                         field.name: field.bit_length
                     } for field in pattern.fields])]))
    return pattern_list

  @property
  def all_image_ids(self):
    """Returns all image ids."""
    return list(self._image_id_to_pattern)

  def AddEmptyPattern(
      self, image_id, encoding_scheme: Union[str,
                                             common.EncodingScheme]) -> int:
    """Adds a new empty pattern.

    Args:
      image_id: The image id of the new pattern.
      encoding_sheme: The encoding scheme of the new pattern.
    Returns:
      The associated pattern index.
    """
    # Casts encoding_scheme to str type for avoiding yaml dump error.
    encoding_scheme = str(encoding_scheme)
    self._SCHEMA.element_type.items['image_ids'].element_type.Validate(image_id)
    self._SCHEMA.element_type.items['encoding_scheme'].Validate(encoding_scheme)

    if image_id in self._image_id_to_pattern:
      raise common.HWIDException(
          f'The image id {image_id!r} is already in used.')

    associated_pattern_idx = self.num_patterns
    new_pattern = PatternDatum(associated_pattern_idx, encoding_scheme, [])
    self._image_id_to_pattern[image_id] = associated_pattern_idx
    self._patterns.append(new_pattern)
    return associated_pattern_idx

  def AddImageId(self, image_id: int, reference_image_id: Optional[int] = None,
                 pattern_idx: Optional[int] = None) -> int:
    """Adds an image id to a pattern by the specific image id.

    Args:
      reference_image_id: An integer of the image id.  If not given, the latest
          image id would be used.
      image_id: The image id to be added.
      pattern_idx: The index of the pattern to be associated to image_id.
    Returns:
      The associated pattern index.
    """
    self._SCHEMA.element_type.items['image_ids'].element_type.Validate(image_id)

    if (reference_image_id is None) == (pattern_idx is None):
      raise common.HWIDException('Please specify exactly one of '
                                 "'reference_image_id' and 'pattern_idx'")

    if image_id in self._image_id_to_pattern:
      raise common.HWIDException(
          f'The image id {image_id!r} has already been in used.')

    if reference_image_id is not None:
      if reference_image_id not in self._image_id_to_pattern:
        raise common.HWIDException(
            f'No pattern for image id {reference_image_id}.')
      pattern_idx = self._image_id_to_pattern[reference_image_id]

    if pattern_idx >= self.num_patterns:
      raise common.HWIDException(f'No such pattern at position {pattern_idx}.')
    self._image_id_to_pattern[image_id] = pattern_idx
    return pattern_idx

  def AppendField(self, field_name, bit_length, image_id=None,
                  pattern_idx=None):
    """Append a field to the pattern.

    Args:
      field_name: Name of the field.
      bit_length: Bit width to add.
      image_id: An integer of the image id. If not given, the latest image id
          would be used.
      pattern_idx: The index of the pattern.
    """
    self._SCHEMA.element_type.items['fields'].element_type.key_type.Validate(
        field_name)
    self._SCHEMA.element_type.items['fields'].element_type.value_type.Validate(
        bit_length)

    self.GetPattern(image_id=image_id, pattern_idx=pattern_idx).fields.append(
        PatternField(field_name, bit_length))

  def GetEncodingScheme(self, image_id=None):
    """Gets the encoding scheme recorded in the pattern.

    Args:
      image_id: An integer of the image id to query. If not given, the latest
          image id would be used.

    Returns:
      Either "base32" or "base8192".
    """
    return self.GetPattern(image_id).encoding_scheme

  def GetTotalBitLength(self, image_id=None, pattern_idx=None):
    """Gets the total bit length defined by the pattern.

    Args:
      image_id: An integer of the image id to query. If both image_id and
          pattern_idx are not given, the latest image id would be used.
      pattern_idx: The index of the pattern.

    Returns:
      A int indicating the total bit length.
    """
    pattern = self.GetPattern(image_id=image_id, pattern_idx=pattern_idx)
    return sum(field.bit_length for field in pattern.fields)

  def GetFieldsBitLength(self, image_id: Optional[int] = None,
                         pattern_idx: Optional[int] = None):
    """Gets a map for the bit length of each encoded fields defined by the
    pattern. Scattered fields with the same field name are aggregated into one.

    Args:
      image_id: An integer of the image id to query. If both image_id and
          pattern_idx are not given, the latest image id would be used.
      pattern_idx: The index of the pattern.

    Returns:
      A dict mapping each encoded field to its bit length.
    """
    ret = collections.defaultdict(int)
    for field in self.GetPattern(image_id=image_id,
                                 pattern_idx=pattern_idx).fields:
      ret[field.name] += field.bit_length
    return dict(ret)

  def GetBitMapping(self, image_id=None, pattern_idx=None, max_bit_length=None):
    """Gets a list indicating the mapping target (field name and the offset) of
    each bit in the components bitset.

    For example, the returned map may say that bit 5 in the components bitset
    corresponds to the least significant bit of encoded field 'cpu'.

    Args:
      image_id: An integer of the image id to query. If both image_id and
          pattern_idx are not given, the latest image id would be used.
      pattern_idx: The index of the pattern.
      max_bit_length: The max length of the return list.  If given, it is used
          to check against the encoding pattern to see if there is an incomplete
          bit chunk.

    Returns:
      A list of BitEntry objects indexed by bit position in the components
          bitset.  Each BitEntry object has attributes (field, bit_offset)
          indicating which bit_offset of field this particular bit corresponds
          to. For example, if ret[6] has attributes (field='cpu', bit_offset=1),
          then it means that bit position 6 of the binary string corresponds
          to the bit offset 1 (which is the second least significant bit)
          of encoded field 'cpu'.
    """

    total_bit_length = self.GetTotalBitLength(image_id=image_id,
                                              pattern_idx=pattern_idx)
    if max_bit_length is None:
      max_bit_length = total_bit_length
    else:
      max_bit_length = min(max_bit_length, total_bit_length)

    ret = []
    field_offset_map = collections.defaultdict(int)
    for name, bit_length in self.GetPattern(image_id=image_id,
                                            pattern_idx=pattern_idx).fields:
      # Normally when one wants to extend bit length of a field, one should
      # append new pattern field instead of expanding the last field.
      # However, for some project, we already have cases where last pattern
      # fields were expanded directly. See crosbug.com/p/30266.
      #
      # Ignore extra bits if we have reached `max_bit_length` so that we can
      # generate the correct bit mapping in previous versions whose total
      # bit length is smaller.
      remaining_length = max_bit_length - len(ret)
      if remaining_length <= 0:
        break
      real_length = min(bit_length, remaining_length)

      # Big endian.
      for offset_delta in range(real_length - 1, -1, -1):
        ret.append(BitEntry(name, offset_delta + field_offset_map[name]))

      field_offset_map[name] += real_length

    return ret

  def GetPattern(self, image_id: Optional[int] = None,
                 pattern_idx: Optional[int] = None) -> PatternDatum:
    """Get the pattern by the given image id or the pattern's numerical index.

    Args:
      image_id: An integer of the image id to query.  If not given, the latest
          image id would be used.
      pattern_idx: The index of the pattern.

    Returns:
      The `PatternDatum` object.
    """
    if pattern_idx is not None:
      if pattern_idx >= self.num_patterns:
        raise common.HWIDException(
            f'No such pattern at position {pattern_idx}.')
      return self._patterns[pattern_idx]

    if image_id is None:
      return self._patterns[self._image_id_to_pattern[self._max_image_id]]

    if image_id not in self._image_id_to_pattern:
      raise common.HWIDException(f'No pattern for image id {image_id!r}.')

    return self._patterns[self._image_id_to_pattern[image_id]]

  @property
  def _max_image_id(self):
    return ImageId.GetMaxImageIDFromList(list(self._image_id_to_pattern))

  @property
  def num_patterns(self):
    return len(self._patterns)


class Rules:
  """A class for parsing rules defined in the database.

  The `rules` part of a HWID database consists of a list of rules to be
  evaluate.  There's two kind of rules:

    1. `device_info`: This kind of rules will be evaluated before encoding the
       BOM object into the HWID identity.  While generating the HWID identity,
       we probe the Chromebook to know what components are installed on the
       Chromebook and store the component list as a BOM object.  But since
       some unprobeable information is also needed to be encoded into The HWID
       identity (such as `image_id`), the BOM object is "incomplete".
       The `device_info` rules then will fill those unprobeable information into
       the BOM object so that it can be encoded into a HWID identity.
    2. `verify`: This kind of rules will be evaluated when we want to verify
       whether a HWID identity is valid (for example, after a HWID identity is
       generated).  Sometimes we might find that two specific hardware
       components living together would crash the Chromebook, then we have to
       avoid this combination.  That's one example of when to use the `verify`
       rules.  The `verify` rules allow developers to specify some customized
       verifying process.

  The format of `rules` part in the HWID database file is:

  ```
  rules:
  - name: <name>
    evaluate: <expressions>
    when: <when_expression>     # This field is optional.
    otherwise: <expressions>    # This field is optional.
  ...

  ```

  <name> can be any string starts with either "device_info." or "verify.".

  <expressions> can be a string of python expression, or a list of string of
  python expression, see below for detail descrption.

  <when_expression> is a string of python expression.

  `when:` field is optional, it is used for condition evaluating, the
  <expressions> specified in `evaluate:` field will be run only if the
  evaluated value of <when_expression> is true.

  `otherwise` field is also optional, but shouldn't exist if there's no `when:`
  field.  <expressions> specified in this field will be run if the evaluated
  value of <when_expression> is false.

  `cros.factory.hwid.v3.common_rule_functions` and
  `cros.factory.hwid.v3.hwid_rule_functions` packages have already defined a
  series of functions which can be called in <expressions>.

  An example of `rules` part in a HWID database is:
  ```
  rules:
  - name: device_info.set_image_id
    evaluate: SetImageId('PVT')

  - name: device_info.component.has_cellular
    when: GetDeviceInfo('component.has_cellular')
    evaluate: Assert(ComponentEq('cellular', 'foxconn_novatel'))
    otherwise: Assert(ComponentEq('cellular', None))

  - name: device_info.component.keyboard
    when: GetOperationMode() != 'rma'
    evaluate: |
        SetComponent(
            'keyboard', LookupMap(GetDeviceInfo('component.keyboard'), {
                'US_API': 'us_darfon',
                'UK_API': 'gb_darfon',
                'FR_API': 'fr_darfon',
                'DE_API': 'de_darfon',
                'SE_API': 'se_darfon',
                'NL_API': 'us_intl_darfon',
            }))

  - name: verify.vpd.ro
    evaluate:
    - Assert(ValidVPDValue('ro', 'serial_number'))
  ```

  Properties:
    rules: A list of Rule instances, which include both type of rules.
    device_info_rules: A list of `device_info` type of rules.
    verify_rules: A list of `verify` type of rules.

  """

  class _RuleTypes(str, enum.Enum):
    verify = 'verify'
    device_info = 'device_info'

    def __str__(self):
      return self.name

  _EXPRESSIONS_SCHEMA = schema.AnyOf([
      schema.Scalar('rule expression', str),
      schema.List('list of rule expressions',
                  schema.Scalar('rule expression', str))
  ])
  _RULE_SCHEMA = schema.FixedDict(
      'rule', items={
          'name': schema.Scalar('rule name', str),
          'evaluate': _EXPRESSIONS_SCHEMA
      }, optional_items={
          'when': schema.Scalar('expression', str),
          'otherwise': _EXPRESSIONS_SCHEMA
      })

  def __init__(self, rule_expr_list):
    """Constructor.

    This constructor shouldn't be called from other modules.
    """
    if not isinstance(rule_expr_list, list):
      raise common.HWIDException(
          '`rules` part of a HWID database should be a list, but got '
          f'{rule_expr_list!r}')

    self._rules = []

    for rule_expr in rule_expr_list:
      self._RULE_SCHEMA.Validate(rule_expr)

      rule = v3_rule.Rule.CreateFromDict(rule_expr)
      if not any(rule.name.startswith(x + '.') for x in self._RuleTypes):
        raise common.HWIDException(
            f'Invalid rule name {rule.name!r}; rule name must be prefixed with '
            '"device_info." (evaluated when generating HWID) or "verify." '
            '(evaluated when verifying HWID)')

      self._rules.append(rule)

  def __eq__(self, rhs):
    return isinstance(rhs, Rules) and self._rules == rhs._rules

  def __ne__(self, rhs):
    return not self == rhs

  def Export(self):
    """Exports the `rule` part into a list of dictionary object which can be
    saved to the HWID database file."""

    def _TransToOrderedDict(rule_dict):
      ret = yaml.Dict([('name', rule_dict['name']),
                       ('evaluate', rule_dict['evaluate'])])
      for key in ['when', 'otherwise']:
        if key in rule_dict:
          ret[key] = rule_dict[key]
      return ret

    return [_TransToOrderedDict(rule.ExportToDict()) for rule in self._rules]

  @property
  def device_info_rules(self):
    return self._GetRules(self._RuleTypes.device_info + '.')

  @property
  def verify_rules(self):
    return self._GetRules(self._RuleTypes.verify + '.')

  def AddDeviceInfoRule(self, name_suffix, evaluate, **kwargs):
    """Adds a device info type rule.

    Args:
      name_suffix: A string of the suffix of the rule name, the actual rule name
          will be "device_info.<name_suffix>".
      **kwargs:
        position:  None to append the rule at the end of all rules; otherwise
          if the value is N, the rule will be inserted right before the N-th
          device_info rule.
        other arguments: Arguments needed by the Rule class' constructor.
      position:
    """
    position = kwargs.pop('position', None)
    self._AddRule(self._RuleTypes.device_info, position, name_suffix, evaluate,
                  **kwargs)

  def _GetRules(self, prefix):
    return [rule for rule in self._rules if rule.name.startswith(prefix)]

  def _AddRule(self, rule_type, position, name_suffix, evaluate, **kwargs):
    rule_obj = v3_rule.Rule(rule_type + '.' + name_suffix, evaluate, **kwargs)

    if position is not None:
      order = -1
      for index, existed_rule_obj in enumerate(self._rules):
        if not existed_rule_obj.name.startswith(rule_type):
          continue
        order += 1
        if order == position:
          self._rules.insert(index, rule_obj)
          return

    self._rules.append(rule_obj)
