# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import functools
import hashlib
import itertools
import logging
import re
import textwrap
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Union

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import probe
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import json_utils


# The components that are added in order if they exist in the probe results.
PRIORITY_COMPS = collections.OrderedDict(
    [(common.FirmwareComps.RO_MAIN_FIRMWARE, 5),
     (common.FirmwareComps.FIRMWARE_KEYS, 3),
     (common.FirmwareComps.RO_EC_FIRMWARE, 5)])

ProbedValueType = Dict[str, Union[List, None, 'ProbedValueType', bool, float,
                                  int, str]]


class BuilderException(Exception):
  """Raised when the operation of the builder is invalid."""


def GetDeterministicHash(value: ProbedValueType) -> bytes:
  """Returns a hash value of value.

  Args:
    value: An object of type ProbedValueType.

  Returns:
    A bytes object with length hashlib.sha256().digest_size.
  """
  json_value = json_utils.DumpStr(value, sort_keys=True)
  return hashlib.sha256(json_value.encode()).digest()


def FilterSpecialCharacter(string: str) -> str:
  """Filters special cases and converts all separation characters to underlines.
  """
  string = re.sub(r'[: .-]+', '_', string)
  string = re.sub(r'[^A-Za-z0-9_]+', '', string)
  string = re.sub(r'[_]+', '_', string)
  string = re.sub(r'^_|_$', '', string)
  if not string:
    string = 'unknown'
  return string


def DetermineComponentName(comp_cls: str, value: ProbedValueType,
                           name_list=None):
  comp_name = _DetermineComponentName(comp_cls, value)
  if name_list is None:
    name_list = []
  return HandleCollisionName(comp_name, name_list)


def HandleCollisionName(comp_name, name_list):
  # To prevent name collision, add "_n" if the name already exists.
  if name_list is None:
    name_list = []
  if comp_name in name_list:
    suffix_num = 1
    while f'{comp_name}_{int(suffix_num)}' in name_list:
      suffix_num += 1
    comp_name = f'{comp_name}_{int(suffix_num)}'
  return comp_name


def _DetermineFeatureManagementComponentName(comp_cls: str,
                                             value: ProbedValueType) -> str:
  # See context for naming strategy in b/274033956.
  postfix = []
  if value.get('is_chassis_branded', '0') != '0':
    postfix.append('chassis_branded')
  else:
    postfix.append('not_chassis_branded')

  if value.get('hw_compliance_version', '0') != '0':
    postfix.append('hw_compliant')
  else:
    postfix.append('hw_incompliant')
  postfix_str = '_'.join(postfix)
  return f'{comp_cls}_{postfix_str}'


def _DetermineFirmwareComponentName(unused_comp_cls: str,
                                    value: ProbedValueType) -> str:
  if 'devkeys' in value['key_root']:
    return 'firmware_keys_dev'
  return 'firmware_keys_non_dev'


def _DetermineSkuIdComponentName(unused_comp_cls: str,
                                 value: ProbedValueType) -> str:
  return f'sku_{value["sku_id"]}'


def _DetermineComponentName(comp_cls: str, value: ProbedValueType):
  """Determines the component name by the value.

  For some specific components, we can determine a meaningful name by the
  component value. For example the value contains the vendor name, or the part
  number. But some components value don't, so we just use UUID.
  Note that the function doesn't guarantee the name is unique.

  Args:
    comp_cls: the component class name.
    value: the probed value of the component item.

  Returns:
    the component name.
  """
  component_name_generators = {
      'feature_management_flags': _DetermineFeatureManagementComponentName,
      'firmware_keys': _DetermineFirmwareComponentName,
      'sku_id': _DetermineSkuIdComponentName,
  }

  if comp_cls in component_name_generators:
    return component_name_generators[comp_cls](comp_cls, value)

  # General components.
  if len(value) == 1:
    return FilterSpecialCharacter(str(next(iter(value.values()))))
  try:
    return f"{value['part']}_{value['size']}mb_{value['slot']}"
  except KeyError:
    pass
  for key in [
      'id', 'version', 'model', 'manufacturer', 'part', 'name', 'compact_str'
  ]:
    if key in value:
      return FilterSpecialCharacter(str(value[key]))

  suffix = GetDeterministicHash(value)[:4].hex()
  return f'{comp_cls}_{suffix}'


def PromptAndAsk(question_str, default_answer=True):
  """Prompts the question and asks user to decide yes or no.

  If the first character user enter is not 'y' nor 'n', the method returns the
  default answer.

  Args:
    question_str: the question prompted to ask the user.
    default_answer: the default answer of the question.
  """
  hint_str = ' [Y/n] ' if default_answer else ' [y/N] '
  input_str = input(question_str + hint_str)
  if input_str and input_str[0].lower() in ['y', 'n']:
    ret = input_str[0].lower() == 'y'
  else:
    ret = default_answer
  logging.info('You chose: %s', 'Yes' if ret else 'No')
  return ret


def ChecksumUpdater():
  """Finds the checksum updater in the chromium source tree.

  Returns:
    a update_checksum module if found. otherwise return None.
  """
  try:
    from cros.chromeoshwid import update_checksum
    return update_checksum
  except ImportError:
    logging.error('checksum_update is not found.')
    return None


def _EnsureInBuilderContext(method):

  @functools.wraps(method)
  def _Wrapper(self, *args, **kwargs):
    if not self.in_context:
      raise BuilderException(
          'Modification of DB should be called within builder context')
    return method(self, *args, **kwargs)

  return _Wrapper


class DatabaseBuilder:
  """A helper class for updating a HWID WritableDatabase object.

  properties:
    db: The WritableDatabase object this class manipulates on.
    _from_empty_database: True if this builder is for creating a new database.
  """

  _DEFAULT_COMPONENT_SUFFIX = '_default'

  def __init__(self, db: database.WritableDatabase, from_empty_database: bool,
               auto_decline_essential_prompt: Optional[Sequence[str]] = None):
    """Initializer.

    Args:
      db: A cros.factory.hwid.v3.database.WritableDatabase Object.
      from_empty_database: True if this builder is for creating a new database.
      auto_decline_essential_prompt: A list of essential components that will
        automatically decline the prompt if an essential component is absent.
    """
    self._database = db
    self._from_empty_database = from_empty_database
    self._auto_decline_essential_prompt = set(auto_decline_essential_prompt or
                                              [])
    self._in_context = False

  def __enter__(self):
    self._in_context = True
    return self

  def __exit__(self, exc_type, unused_exc_value, unused_traceback):
    if exc_type is None:  # Exit the context without errors.
      self._database.SanityChecks()
    self._in_context = False

  @property
  def in_context(self):
    return self._in_context

  @classmethod
  def FromFilePath(
      cls, db_path: str,
      auto_decline_essential_prompt: Optional[Sequence[str]] = None
  ) -> 'DatabaseBuilder':
    """Create a builder from a path of an existing DB."""

    db = database.WritableDatabase.LoadFile(db_path, verify_checksum=False)
    if not db.can_encode:
      raise ValueError(f'The given HWID database {db_path} is legacy and not '
                       'supported by DatabaseBuilder.')
    return cls(db=db, from_empty_database=False,
               auto_decline_essential_prompt=auto_decline_essential_prompt)

  @classmethod
  def FromExistingDB(
      cls, db: database.Database,
      auto_decline_essential_prompt: Optional[Sequence[str]] = None
  ) -> 'DatabaseBuilder':
    """Create a builder from an existing DB."""

    if not isinstance(db, database.WritableDatabase):
      raise ValueError('The database is not writable.')
    return cls(db=db, from_empty_database=False,
               auto_decline_essential_prompt=auto_decline_essential_prompt)

  @classmethod
  def FromEmpty(
      cls, project: str, image_name: str,
      auto_decline_essential_prompt: Optional[Sequence[str]] = None
  ) -> 'DatabaseBuilder':
    """Create a builder to building an empty DB."""

    db = cls._BuildEmptyDatabase(project.upper(), image_name)
    return cls(db=db, from_empty_database=True,
               auto_decline_essential_prompt=auto_decline_essential_prompt)

  @classmethod
  def FromDBData(
      cls, db_data: str,
      auto_decline_essential_prompt: Optional[Sequence[str]] = None
  ) -> 'DatabaseBuilder':
    """Create a builder from DB data of an existing DB."""

    db = database.WritableDatabase.LoadData(db_data, expected_checksum=None)
    return cls(db=db, from_empty_database=False,
               auto_decline_essential_prompt=auto_decline_essential_prompt)

  @_EnsureInBuilderContext
  def AddFeatureManagementFlagComponents(self):
    """Adds component items and encoded bits for feature management flags."""

    comp_cls = 'feature_management_flags'
    existed_comps = self._database.GetComponents(comp_cls)

    if existed_comps:
      raise BuilderException(
          'Already have existed feature management components in database.'
          'Use only when updating the database for the first time.')

    # ('is_chassis_branded', 'hw_compliance_version')
    valid_feature_flag_pairs = [('0', '0'), ('0', '1'), ('1', '1')]
    for chassis_branded, hw_compliance_version in valid_feature_flag_pairs:
      value = {
          'hw_compliance_version': hw_compliance_version,
          'is_chassis_branded': chassis_branded
      }
      self.AddComponentCheck(comp_cls, value)

    existed_comp_names = self._database.GetComponents(comp_cls).keys()
    field_name = f'{comp_cls}_field'
    for idx, name in enumerate(existed_comp_names):
      if idx:
        self.AddEncodedFieldComponents(field_name, comp_cls, [name])
      else:
        self.AddNewEncodedField(comp_cls, [name])

  @_EnsureInBuilderContext
  def UprevFrameworkVersion(self, new_framework_version):
    if new_framework_version < self._database.framework_version:
      raise ValueError(
          'The HWID framework cannot be downgraded, please consider upgrading '
          'the toolkit on DUT before collecting materials.')
    self._database.framework_version = new_framework_version

  @_EnsureInBuilderContext
  def AddDefaultComponent(self, comp_cls):
    """Adds a default component item and corresponding rule to the database.

    Args:
      comp_cls: The component class.
    """
    logging.info('Component [%s]: add a default item.', comp_cls)

    if self._database.GetDefaultComponent(comp_cls) is not None:
      raise ValueError(
          f'The component class {comp_cls!r} already has a default component.')

    comp_name = comp_cls + self._DEFAULT_COMPONENT_SUFFIX
    self._database.AddComponent(comp_cls, comp_name, None,
                                common.ComponentStatus.unqualified)

  @_EnsureInBuilderContext
  def AddNullComponent(self, comp_cls):
    """Updates the database to be able to encode a device without specific
    component class.

    Args:
      comp_cls: A string of the component class name.
    """
    field_name = self._database.GetEncodedFieldForComponent(comp_cls)
    if not field_name:
      self.AddNewEncodedField(comp_cls, [])
      return

    if len(self._database.GetComponentClasses(field_name)) > 1:
      raise ValueError(
          f'The encoded field {field_name!r} for component {comp_cls!r} encodes'
          ' more than one component class so it\'s not trivial to mark a null '
          f'{comp_cls!r} component. Please update the database by a real probed'
          ' results.')
    if all(comps[comp_cls]
           for comps in self._database.GetEncodedField(field_name).values()):
      self._database.AddEncodedFieldComponents(field_name, {comp_cls: []})

  @_EnsureInBuilderContext
  def AddFirmwareComponent(self, comp_cls, value, comp_name,
                           supported=False) -> database.ComponentInfo:
    # Rename instead of add if any old component has same probed value
    for old_comp_name, comp_info in self.GetComponents(comp_cls).items():
      if (value and not comp_info.value_is_none and
          dict.__eq__(comp_info.values, value)):
        status = (
            common.ComponentStatus.supported if supported else comp_info.status)
        self.UpdateComponent(comp_cls, old_comp_name, comp_name,
                             comp_info.values, status, comp_info.information,
                             comp_info.bundle_uuids)
        return self.GetComponents(comp_cls)[comp_name]

    field_name = f'{comp_cls}_field'

    # Append null comp for new firmware comp, otherwise the index 0 will be
    # decoded by default and break the existing devices.
    if (not self._database.is_initial and
        comp_cls not in self._database.GetComponentClasses()):
      self.AddNullComponent(comp_cls)
      self.AppendEncodedFieldBit(field_name, 1)

    comp_info = self.AddComponentCheck(comp_cls, value, comp_name,
                                       supported=supported)

    # Get the comp_name by hash again since it may be renamed if there's
    # a collision
    comp_name = self.GetComponentNameByHash(comp_cls, comp_info.comp_hash)
    if field_name not in self._database.encoded_fields:
      self.AddNewEncodedField(comp_cls, [comp_name])
    else:
      self.AddEncodedFieldComponents(field_name, comp_cls, [comp_name])
    # Skip updating pattern to initial DB since it swill cause error due to
    # missing essential comps.
    if not self._database.is_initial:
      self.FillEncodedFieldBit(field_name)

    return comp_info

  @_EnsureInBuilderContext
  def AddRegions(self, new_regions, region_field_name='region_field'):
    if self._database.GetComponentClasses(region_field_name) != set(['region']):
      raise ValueError(
          f'"{region_field_name}" is not a valid region field name.')

    added_regions = set()
    for region_comp in self._database.GetEncodedField(
        region_field_name).values():
      if region_comp['region']:
        added_regions.add(region_comp['region'][0])

    for new_region in new_regions:
      if new_region in added_regions:
        logging.warning('The region %s is duplicated, skip to add again.',
                        new_region)
        continue
      added_regions.add(new_region)
      self._database.AddEncodedFieldComponents(region_field_name,
                                               {'region': [new_region]})
    self._UpdatePattern()

  def _AddSkuIds(self, sku_ids):
    field_name = 'sku_id_field'
    comp_cls = 'sku_id'
    existed_comps = self._database.GetComponents(comp_cls)
    existed_sku_ids = {int(e.values['sku_id'])
                       for e in existed_comps.values()}
    sku_ids = set(sku_ids)
    new_sku_ids = sorted(sku_ids - existed_sku_ids)
    if new_sku_ids:
      new_probed_values = [{
          'sku_id': str(sku_id)
      } for sku_id in new_sku_ids]
      self.AddNullComponent(comp_cls)
      self.AddComponents(comp_cls, new_probed_values)

    # Check if we need to update the encoded field.
    comp_to_sku_id = {
        comp_name: int(comp_info.values['sku_id'])
        for comp_name, comp_info in self._database.GetComponents(
            comp_cls).items()
    }
    for e in self._database.GetEncodedField(field_name).values():
      if e[comp_cls]:
        comp_to_sku_id.pop(e[comp_cls][0])

    new_comps = sorted(comp_to_sku_id.keys(), key=lambda x: comp_to_sku_id[x])
    for comp_name in new_comps:
      self._database.AddEncodedFieldComponents(field_name,
                                               {comp_cls: [comp_name]})

  @_EnsureInBuilderContext
  def UpdateByProbedResults(self, probed_results: Mapping, device_info: Mapping,
                            vpd: Mapping, sku_ids: Optional[Sequence[str]],
                            image_name: Optional[str] = None,
                            skip_firmware_components: bool = False,
                            form_factor: Optional[str] = None):
    """Updates the database by a real probed results.

    Args:
      probed_results: The probed result obtained by probing the device.
      device_info: An empty dict or a dict contains the device information.
      vpd: An empty dict or a dict contains the vpd values.
      sku_ids: A list of sku IDs
      image_name: image name to be updated
      skip_firmware_components: Skip update firmware components if True
      form_factor: Form factor of the device.
    """
    if self._from_empty_database and image_name:
      logging.warning('The argument `image_name` will be ignored when '
                      'DatabaseBuilder is creating the new database instead of '
                      'updating an existed database.')

    bom = self._UpdateComponents(probed_results, device_info, vpd, sku_ids,
                                 skip_firmware_components, form_factor)
    self._UpdateEncodedFields(bom)
    if not self._from_empty_database:
      self._MayAddNewPatternAndImage(image_name)
    self._UpdatePattern(form_factor=form_factor)

  def Render(self, database_path):
    """Renders the database to a yaml file.

    Args:
      database_path: the path of the output HWID database file.
    """
    if self._in_context:
      raise BuilderException(
          'Render should be called outside the builder context')
    self._database.DumpFileWithoutChecksum(database_path, internal=True)

    checksum_updater = ChecksumUpdater()
    if checksum_updater is None:
      logging.info('Checksum is not updated.')
    else:
      logging.info('Update the checksum.')
      checksum_updater.UpdateFile(database_path)

  def Build(self) -> database.Database:
    """Build the database."""

    if self._in_context:
      raise BuilderException(
          'Build should be called outside the builder context')
    # TODO(b/232063010): Consider returning a duplicate DB instance.
    return self._database

  @classmethod
  def _BuildEmptyDatabase(cls, project,
                          image_name) -> database.WritableDatabase:
    return database.WritableDatabase.LoadData(
        textwrap.dedent(f'''\
            checksum: None
            project: {project}
            encoding_patterns:
              0: default
            image_id:
              0: {image_name}
            pattern:
              - image_ids: [0]
                encoding_scheme: {common.EncodingScheme.base8192}
                fields: []
            encoded_fields:
              region_field: !region_field []
            components:
              region: !region_component
            rules: []
        '''))

  @_EnsureInBuilderContext
  def _DeprecateOldFirmwareComponent(self, comp_cls: str,
                                     probed_value: ProbedValueType):
    """Deprecates old firmware component by the given probed value.

    This method will get the firmware identity from version string, and
    deprecates all old firmware components with the same identity.

    Args:
      comp_cls: The component class.
      probed_value: The probed value of the component.
    """

    def _GetVersionStringIdentity(version_string):
      """Gets the identity from firmware version string.

      The format of firmware version:
        ro_main_firwamre: ${ID}.${VERSION}
        others: ${ID}_${VERSION}
      """
      if not version_string:
        return None
      if comp_cls == common.FirmwareComps.RO_MAIN_FIRMWARE:
        return version_string.split('.', 1)[0]
      return version_string.split('_', 1)[0]

    fw_identity = _GetVersionStringIdentity(probed_value.get('version'))

    def _IsPrePVTFirmwareKeys(comp_name):
      return (comp_cls == common.FirmwareComps.FIRMWARE_KEYS and
              re.match('firmware_keys_(dev|premp|mp_default)', comp_name))

    # Set old firmware components to deprecated.
    for comp_name, comp_info in self._database.GetComponents(comp_cls).items():
      if comp_info.status != common.ComponentStatus.supported:
        continue

      existing_fw_identity = _GetVersionStringIdentity(
          comp_info.values.get('version'))
      # Only deprecate pre-PVT firmware keys.
      if (_IsPrePVTFirmwareKeys(comp_name) or
          fw_identity and fw_identity == existing_fw_identity):
        self._database.SetComponentStatus(comp_cls, comp_name,
                                          common.ComponentStatus.deprecated)

  @_EnsureInBuilderContext
  def AddComponentCheck(self, comp_cls: str, probed_value: ProbedValueType,
                        set_comp_name: Optional[str] = None,
                        supported: bool = False) -> database.ComponentInfo:
    """Tries to add an item into the component.

    This method is called with probed value from factory process instead of
    existing HWID DB content, so it has to perform the following checks:

      1. Mark previously supported firmware components as deprecated.
      2. Generate component names by the info of probe values if not specified
         at the set_comp_name argument.
      3. Deprecate default component of the same component class.

    Args:
      comp_cls: The component class.
      probed_value: The probed value of the component.
      set_comp_name: Set component name for the item. If None is given, it will
        be determined automatically.
      supported: whether to mark the added component as supported.

    Returns:
      The added component info.
    """

    if common.FirmwareComps.has_value(comp_cls):
      self._DeprecateOldFirmwareComponent(comp_cls, probed_value)

    comps = list(self._database.GetComponents(comp_cls))
    comp_name = (
        HandleCollisionName(set_comp_name, comps) or
        DetermineComponentName(comp_cls, probed_value, comps))

    logging.info('Component %s: add an item "%s".', comp_cls, comp_name)
    status = (
        common.ComponentStatus.supported
        if supported else common.ComponentStatus.unqualified)
    self._database.AddComponent(comp_cls, comp_name, probed_value, status)

    # Deprecate the default component.
    default_comp_name = self._database.GetDefaultComponent(comp_cls)
    if default_comp_name is not None:
      self._database.SetComponentStatus(comp_cls, default_comp_name,
                                        common.ComponentStatus.unsupported)

    return self.GetComponents(comp_cls)[comp_name]

  @_EnsureInBuilderContext
  def AddComponent(self, comp_cls: str, comp_name: str,
                   probed_value: ProbedValueType, support_status: str,
                   information: Optional[Mapping[str, Any]] = None):
    """Add an item into the component without performing checks.

    Args:
      comp_cls: The component class.
      comp_name: Set component name for the item.
      probed_value: The probed value of the component.
      support_status: One of `common.ComponentStatus`.
      information: Optional dict, these data will be used to further help
          Runtime Probe and Hardware Verifier have more information to handle
          miscellaneous probe issues.
    """
    self._database.AddComponent(comp_cls, comp_name, probed_value,
                                support_status, information)

  @_EnsureInBuilderContext
  def AddComponents(self, comp_cls: str, probed_values: List[ProbedValueType]):
    """Adds a list of components to the database.

    Args:
      comp_cls: A string of the component class name.
      probed_values: A list of probed value from the device.
    """

    def _IsSubset(subset: Mapping[str, Any], superset: Mapping[str,
                                                               Any]) -> bool:
      return all(subset.get(key) == value for key, value in superset.items())

    # Only add the unique component to the database.
    # For example, if the given probed values are
    #   {"a": "A", "b": "B"},
    #   {"a": "A", "b": "B", "c": "C"},
    #   {"a": "A", "x": "X", "y": "Y"}
    # then we only add the first and the third components because the second
    # one is considered as the same as the first one.
    for i, probed_value_i in enumerate(probed_values):
      if (any(
          _IsSubset(probed_value_i, probed_values[j]) and
          probed_value_i != probed_values[j] for j in range(i)) or any(
              _IsSubset(probed_value_i, probed_values[j])
              for j in range(i + 1, len(probed_values)))):
        continue
      self.AddComponentCheck(comp_cls, probed_value_i)

  @_EnsureInBuilderContext
  def AddNewEncodedField(self, comp_cls: str, comp_names: Sequence[str],
                         encoded_field_name: Optional[str] = None):
    """Adds a new encoded field for the specific component class.

    Args:
      comp_cls: The component class.
      comp_names: A list of component name.
      encoded_field_name: Optional name of the encoded field.
    """
    field_name = encoded_field_name or HandleCollisionName(
        comp_cls + '_field', self._database.encoded_fields)
    self._database.AddNewEncodedField(field_name, {comp_cls: comp_names})

  @_EnsureInBuilderContext
  def AddEncodedFieldComponents(self, field_name: str, comp_cls: str,
                                comp_names: Sequence[str]):
    """See database.WritableDatabase.AddEncodedFieldComponents."""
    self._database.AddEncodedFieldComponents(field_name,
                                             {comp_cls: list(comp_names)})

  @_EnsureInBuilderContext
  def AddImage(self, image_id: int, image_name: str, new_pattern: bool = False,
               pattern_idx: Optional[int] = None,
               reference_image_id: Optional[int] = None) -> int:
    """See database.WritableDatabase.AddImage."""
    return self._database.AddImage(image_id, image_name,
                                   common.EncodingScheme.base8192, new_pattern,
                                   reference_image_id, pattern_idx)

  @_EnsureInBuilderContext
  def AppendEncodedFieldBit(self, field_name: str, bit_length: int,
                            image_id: Optional[int] = None,
                            pattern_idx: Optional[int] = None):
    """See database.WritableDatabase.AppendEncodedFieldBit."""
    self._database.AppendEncodedFieldBit(field_name, bit_length, image_id,
                                         pattern_idx)

  @_EnsureInBuilderContext
  def FillEncodedFieldBit(self, field_name: str,
                          pattern_idxes: Optional[Sequence[int]] = None):
    """Fills the bits to each encoded fields in all encoding patterns to cover
    the number of existing combinations.

    Args:
      field_name: The name of encoded field.
      pattern_idxes: The indices of the patterns to fill bit lengthss.  This
        method will fill bit lengths of patterns having this field if
        pattern_idxes is set to None.
    """

    bit_length = self._GetMinBitLength(field_name)
    skip_missing = False
    if pattern_idxes is None:
      pattern_idxes = range(self._database.GetPatternCount())
      skip_missing = True  # Only adds to patterns including the field.
    for pattern_idx in pattern_idxes:
      curr_bit_lengths = self._database.GetEncodedFieldsBitLength(
          pattern_idx=pattern_idx)
      if skip_missing and field_name not in curr_bit_lengths:
        continue
      curr_bit_length = curr_bit_lengths.get(field_name, 0)
      if field_name not in curr_bit_lengths or curr_bit_length < bit_length:
        self._database.AppendEncodedFieldBit(
            field_name, bit_length - curr_bit_length, pattern_idx=pattern_idx)

  def RenameImages(self, image_name_mapping: Mapping[int, str]):
    """See database.WritableDatabase.RenameImages."""
    return self._database.RenameImages(image_name_mapping)

  def _UpdateComponents(self, probed_results, device_info, vpd, sku_ids,
                        skip_firmware_components, form_factor):
    """Updates the component part of the database.

    This function update the database by trying to generate the BOM object
    and add mis-matched components on the probed results to the database.

    Args:
      probed_results: The probed results generated by probing the device.
      device_info: The device info object.
      vpd: A dict stores the vpd values.
      sku_ids: A list of sku IDs
      skip_firmware_components: Skip update firmware components if True
      form_factor: Form factor of the device.
    """
    # Add SKU IDs first.  If sku_ids is non-empty, it should contain the probed
    # SKU ID in probed_results.
    if sku_ids:
      self._AddSkuIds(sku_ids)

    if skip_firmware_components:
      probed_results = {
          comp_cls: values
          for comp_cls, values in probed_results.items()
          if not common.FirmwareComps.has_value(comp_cls)
      }

    # Add extra components.
    existed_comp_classes = self._database.GetComponentClasses()
    for comp_cls, probed_comps in probed_results.items():
      if comp_cls not in existed_comp_classes:
        # We only need the probe values here.
        probed_values = [probed_comp['values'] for probed_comp in probed_comps]
        if not probed_values:
          continue

        self.AddComponents(comp_cls, probed_values)

        if self._from_empty_database:
          continue

        add_null = PromptAndAsk(
            f'Found probed values of [{comp_cls}] component\n' + ''.join([
                '\n' + yaml.safe_dump(probed_value, default_flow_style=False)
                for probed_value in probed_values
            ]).replace('\n', '\n  ') + '\n' +
            'to be added to the database, please confirm that:\n' +
            f'If the device has a SKU without {comp_cls} component, ' +
            'please enter "Y".\n' +
            f'If the device always has {comp_cls} component, ' +
            'please enter "N".\n', default_answer=True)

        if add_null:
          self.AddNullComponent(comp_cls)

    # Add mismatched components to the database.
    bom, mismatched_probed_results = probe.GenerateBOMFromProbedResults(
        self._database, probed_results, device_info, vpd,
        common.OperationMode.normal, True)

    if mismatched_probed_results:
      for comp_cls, probed_comps in mismatched_probed_results.items():
        self.AddComponents(
            comp_cls, [probed_comp['values'] for probed_comp in probed_comps])

      bom = probe.GenerateBOMFromProbedResults(
          self._database, probed_results, device_info, vpd,
          common.OperationMode.normal, False)[0]

    # Ensure all essential components are recorded in the database.
    essential_comps = common.FORM_FACTOR_COMPS.get(form_factor,
                                                   common.ESSENTIAL_COMPS)
    for comp_cls in essential_comps:
      if comp_cls == 'region':
        # Skip checking the region because it's acceptable to have a null
        # region component.
        continue
      if not bom.components.get(comp_cls):
        field_name = self._database.GetEncodedFieldForComponent(comp_cls)
        if (field_name and any(
            not comps[comp_cls]
            for comps in self._database.GetEncodedField(field_name).values())):
          # Pass if the database says that device without this component is
          # acceptable.
          continue

        if comp_cls in self._auto_decline_essential_prompt:
          add_default = False
        else:
          # Ask user to add a default item or a null item.
          add_default = PromptAndAsk(
              f'Component [{comp_cls}] is essential but the probe result is '
              'missing. Do you want to add a default item?\n'
              'If the probed code is not ready yet, please enter "Y".\n'
              'If the device does not have the component, please enter "N".',
              default_answer=True)

        if add_default:
          self.AddDefaultComponent(comp_cls)

        else:
          # If there's already an encoded field for this component, leave
          # the work to `_UpdateEncodedFields` method and do nothing here.
          if not field_name:
            self.AddNullComponent(comp_cls)

    return probe.GenerateBOMFromProbedResults(
        self._database, probed_results, device_info, vpd,
        common.OperationMode.normal, False)[0]

  def _UpdateEncodedFields(self, bom):
    covered_comp_classes = set()
    for field_name in self._database.encoded_fields:
      comp_classes = self._database.GetComponentClasses(field_name)

      for comps in self._database.GetEncodedField(field_name).values():
        if all(comp_names == bom.components[comp_cls]
               for comp_cls, comp_names in comps.items()):
          break

      else:
        self._database.AddEncodedFieldComponents(
            field_name,
            {comp_cls: bom.components[comp_cls]
             for comp_cls in comp_classes})

      covered_comp_classes |= set(comp_classes)

    # Although the database allows a component recorded but not encoded by
    # any of the encoded fields, this builder always ensures that all components
    # will be encoded into the HWID string.
    for comp_cls in sorted(self._database.GetComponentClasses()):
      if comp_cls not in covered_comp_classes:
        self.AddNewEncodedField(comp_cls, bom.components[comp_cls])

  def ExtendEncodedFieldToFullCombination(self, field_name, num_components):
    """Extends the encoded field to cover full combination of the components.

    For example, if the `field_name` is `camera_field` and the HWID DB contains
    `N` "supported" or "unqualified" cameras, then this method ensures that
    `camera_field` covers all `C(N+num_components-1, num_components)`
    combinations of `num_components` cameras.

    Args:
      field_name: Name of the encoded field to extend.
      num_components: The number of component in the combination.

    Raises:
      ValueError: if the specified encoded field maps to multiple component
        classes.
    """
    comp_classes = self._database.GetComponentClasses(field_name)
    if len(comp_classes) != 1:
      raise ValueError(f'Cannot extend {field_name!r} to full combinations '
                       'because it contains multiple component classes.')
    comp_class = next(iter(comp_classes))
    acceptable_status = (common.ComponentStatus.supported,
                         common.ComponentStatus.unqualified)
    candidate_comp_names = sorted(
        comp_name for comp_name, comp_info in self._database.GetComponents(
            comp_class).items() if comp_info.status in acceptable_status)

    all_existing_comp_names = set(
        tuple(sorted(encoded_field[comp_class])) for encoded_field in
        self._database.GetEncodedField(field_name).values())
    comp_names_to_append = []
    for comp_names in itertools.combinations_with_replacement(
        candidate_comp_names, num_components):
      if comp_names not in all_existing_comp_names:
        comp_names_to_append.append(comp_names)
    if not comp_names_to_append:
      return
    confirmation = PromptAndAsk(
        f'WARNING: The following {len(comp_names_to_append)} component '
        'combinations will be appended, do you want to continue (Y/n)?'
        '\n' + str(comp_names_to_append), default_answer=True)
    if not confirmation:
      logging.info('Skipped appending full component combination in %s.',
                   field_name)
      return
    logging.info('Appending full component combination in %s: %s.', field_name,
                 comp_names_to_append)
    for comp_names in comp_names_to_append:
      self.AddEncodedFieldComponents(field_name, comp_class, comp_names)
    self._UpdatePattern()

  def _MayAddNewPatternAndImage(self, image_name):
    if image_name in [
        self._database.GetImageName(image_id)
        for image_id in self._database.image_ids
    ]:
      if image_name != self._database.GetImageName(self._database.max_image_id):
        raise ValueError(
            f'image_name [{image_name}] is already in the database.')
      # Mark the image name to none if the given image name is the latest image
      # name so that the caller can specify that they don't want to create
      # an extra image by specifying the image_name to either none or the latest
      # image name.
      image_name = None

    # If the use case is to create a new HWID database, the only pattern
    # contained by the empty database is empty.
    if not self._database.GetEncodedFieldsBitLength():
      return

    extra_fields = set(self._database.encoded_fields) - set(
        self._database.GetEncodedFieldsBitLength().keys())
    if image_name:
      self._database.AddImage(self._database.max_image_id + 1, image_name,
                              common.EncodingScheme.base8192,
                              new_pattern=bool(extra_fields))

    elif extra_fields and PromptAndAsk(
        f'WARNING: Extra fields [{",".join(extra_fields)}] without assigning a '
        'new image_id.\nIf the fields are added into the current pattern, the '
        'index of these fields will be encoded to index 0 for all old HWID '
        'string. Enter "y" if you are sure all old devices with old HWID string'
        ' have the component with index 0.', default_answer=False) is False:
      raise ValueError(
          'Please assign a image_id by adding "--image-id" argument.')

  def _GetMinBitLength(self, field_name: str) -> int:
    return max(self._database.GetEncodedField(field_name)).bit_length()

  def _UpdatePattern(self, form_factor=None):
    """Updates the pattern so that it includes all encoded fields."""

    handled_comp_classes = set()
    handled_encoded_fields = set()

    # Put the important components at first if the pattern is a new one.
    if not self._database.GetEncodedFieldsBitLength():
      # Put the essential field first, and align the 5-3-5 bit field.
      bit_iter = itertools.cycle([5, 3, 5])
      next(bit_iter)  # Skip the first field, which is for image_id.
      essential_comps = common.FORM_FACTOR_COMPS.get(form_factor,
                                                     common.ESSENTIAL_COMPS)
      for comp_cls in essential_comps:
        if comp_cls in handled_comp_classes:
          continue

        field_name = self._database.GetEncodedFieldForComponent(comp_cls)

        bit_length = 0
        min_bit_length = max(self._GetMinBitLength(field_name), 1)
        while bit_length < min_bit_length:
          bit_length += next(bit_iter)
        self._database.AppendEncodedFieldBit(field_name, bit_length)

        handled_comp_classes |= set(
            self._database.GetComponentClasses(field_name))
        handled_encoded_fields.add(field_name)

      # Put the priority components.
      for comp_cls, bit_length in PRIORITY_COMPS.items():
        if comp_cls in handled_comp_classes:
          continue

        field_name = self._database.GetEncodedFieldForComponent(comp_cls)
        if not field_name:
          continue

        bit_length = max(bit_length, self._GetMinBitLength(field_name))
        self._database.AppendEncodedFieldBit(field_name, bit_length)

        handled_comp_classes |= set(
            self._database.GetComponentClasses(field_name))
        handled_encoded_fields.add(field_name)

    # Append other encoded fields.
    curr_bit_lengths = self._database.GetEncodedFieldsBitLength()
    for field_name in self._database.encoded_fields:
      if field_name in handled_encoded_fields:
        continue
      bit_length = self._GetMinBitLength(field_name)
      if (field_name in curr_bit_lengths and
          curr_bit_lengths[field_name] >= bit_length):
        continue
      self._database.AppendEncodedFieldBit(
          field_name, bit_length - curr_bit_lengths.get(field_name, 0))

  def GetComponents(
      self, comp_cls: str,
      include_default: bool = True) -> Mapping[str, database.ComponentInfo]:
    return self._database.GetComponents(comp_cls, include_default)

  def GetActiveComponentClasses(self,
                                image_id: Optional[int] = None) -> Set[str]:
    return self._database.GetActiveComponentClasses(image_id)

  def GetComponentClasses(self,
                          encoded_field_name: Optional[str] = None) -> Set[str]:
    """See database.WritableDatabase.GetComponentClasses."""
    return self._database.GetComponentClasses(encoded_field_name)

  def GetComponentNameByHash(self, comp_cls: str, comp_hash: str) -> str:
    return self._database.GetComponentNameByHash(comp_cls, comp_hash)

  @_EnsureInBuilderContext
  def SetLinkAVLProbeValue(self, comp_cls: str, comp_name: str,
                           converter_identifier: Optional[str],
                           probe_value_matched: bool):
    return self._database.SetLinkAVLProbeValue(
        comp_cls, comp_name, converter_identifier, probe_value_matched)

  @_EnsureInBuilderContext
  def UpdateComponent(self, comp_cls: str, old_name: str, new_name: str,
                      values: Optional[Mapping[str, Any]], support_status: str,
                      information: Optional[Mapping[str, Any]] = None,
                      bundle_uuids: Optional[Sequence[str]] = None):
    self._database.UpdateComponent(comp_cls, old_name, new_name, values,
                                   support_status, information, bundle_uuids)

  @_EnsureInBuilderContext
  def ReplaceRules(self, rule_expr_list: Mapping[str, Any]):
    """See database.WritableDatabase.ReplaceRules."""
    self._database.ReplaceRules(rule_expr_list)
