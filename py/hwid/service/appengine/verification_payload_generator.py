#!/usr/bin/env python3
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Methods to generate the verification payload from the HWID database."""

import collections
import hashlib
import itertools
import logging
import re
from typing import DefaultDict, Dict, List, Mapping, NamedTuple, Optional, Set, Union

from google.protobuf import text_format
import hardware_verifier_pb2  # pylint: disable=import-error
import runtime_probe_pb2  # pylint: disable=import-error

from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module
from cros.factory.hwid.v3 import common as hwid_common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import rule as hwid_rule
from cros.factory.probe.runtime_probe import probe_config_definition
from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.utils import json_utils
from cros.factory.utils import type_utils


BATTERY_SYSFS_MANUFACTURER_MAX_LENGTH = 7
BATTERY_SYSFS_MODEL_NAME_MAX_LENGTH = 7
COMMON_SYSFS_TECHNOLOGY = frozenset(['Li-ion', 'Li-poly'])
COMMON_ECTOOL_CHEMISTRY = frozenset(['LION', 'LiP', 'LIP'])
COMMON_HWID_TECHNOLOGY = COMMON_SYSFS_TECHNOLOGY | COMMON_ECTOOL_CHEMISTRY


class GenericProbeStatementInfoRecord:
  """Placeholder for info. related to the generic probe statement.

  Attributes:
    probe_category: The name of the probe category.
    probe_func_name: The name of the probe function.
    allowlist_fields: A dictionary which keys are the allowed fields in the
        output while the corresponding value can be `None` or some value for
        filtering unwanted generic probed result.  Type of the values must
        match the definition declared in
        `cros.factory.probe.runtime_probe.probe_config_definitions` because
        they will be fed to the probe statement generator.
  """

  def __init__(self, probe_category, probe_func_name, allowlist_fields,
               probe_function_argument=None):
    """Constructor.

    Args:
      probe_category: The name of the probe category.
      probe_func_name: The name of the probe function.
      allowlist_fields: Either a list of allowed fields in the output or
          a dictionary of allowed fields with values for filtering.
      probe_function_argument: A dictionary which will be passed to the probe
          function.
    """
    self.probe_category = probe_category
    self.probe_func_name = probe_func_name
    self.allowlist_fields = (
        allowlist_fields if isinstance(allowlist_fields, dict) else
        {fn: None
         for fn in allowlist_fields})
    self.probe_function_argument = probe_function_argument

  def GenerateProbeStatement(self):
    return probe_config_definition.GetProbeStatementDefinition(
        self.probe_category).GenerateProbeStatement(
            'generic', self.probe_func_name, self.allowlist_fields,
            probe_function_argument=self.probe_function_argument)


# TODO(yhong): Remove the expect field when runtime_probe converts the output
#              format automatically (b/133641904).
@type_utils.CachedGetter
def _GetAllGenericProbeStatementInfoRecords():
  return [
      GenericProbeStatementInfoRecord(
          'battery', 'generic_battery',
          ['chemistry', 'manufacturer', 'model_name', 'technology']),
      GenericProbeStatementInfoRecord('storage', 'generic_storage', [
          'type', 'sectors', 'mmc_hwrev', 'mmc_manfid', 'mmc_name', 'mmc_oemid',
          'mmc_prv', 'mmc_serial', 'pci_vendor', 'pci_device', 'pci_class',
          'nvme_model', 'ata_vendor', 'ata_model', 'ufs_vendor', 'ufs_model'
      ]),
      GenericProbeStatementInfoRecord(
          'cellular', 'network', [
              'bus_type', 'pci_vendor_id', 'pci_device_id', 'pci_revision',
              'pci_subsystem', 'usb_vendor_id', 'usb_product_id',
              'usb_bcd_device'
          ], probe_function_argument={'device_type': 'cellular'}),
      GenericProbeStatementInfoRecord(
          'ethernet', 'network', [
              'bus_type', 'pci_vendor_id', 'pci_device_id', 'pci_revision',
              'pci_subsystem', 'usb_vendor_id', 'usb_product_id',
              'usb_bcd_device'
          ], probe_function_argument={'device_type': 'ethernet'}),
      GenericProbeStatementInfoRecord(
          'wireless', 'network', [
              'bus_type', 'pci_vendor_id', 'pci_device_id', 'pci_revision',
              'pci_subsystem', 'usb_vendor_id', 'usb_product_id',
              'usb_bcd_device', 'sdio_vendor_id', 'sdio_device_id'
          ], probe_function_argument={'device_type': 'wifi'}),
      GenericProbeStatementInfoRecord('dram', 'memory',
                                      ['part', 'size', 'slot']),
      GenericProbeStatementInfoRecord('camera', 'generic_camera', [
          'bus_type', 'usb_vendor_id', 'usb_product_id', 'usb_bcd_device',
          'usb_removable', 'mipi_module_id', 'mipi_name', 'mipi_sensor_id',
          'mipi_vendor'
      ]),
      GenericProbeStatementInfoRecord(
          'display_panel', 'edid', ['height', 'product_id', 'vendor', 'width']),
      GenericProbeStatementInfoRecord(
          'touchpad', 'input_device', [
              'name',
              'product',
              'vendor',
              'fw_version',
              'device_type',
          ], probe_function_argument={'device_type': 'touchpad'}),
      GenericProbeStatementInfoRecord(
          'touchscreen', 'input_device', [
              'name',
              'product',
              'vendor',
              'fw_version',
              'device_type',
          ], probe_function_argument={'device_type': 'touchscreen'}),
      GenericProbeStatementInfoRecord(
          'stylus', 'input_device', [
              'name',
              'product',
              'vendor',
              'fw_version',
              'device_type',
          ], probe_function_argument={'device_type': 'stylus'}),
  ]


class ValueConverter:

  def __call__(self, value):
    raise NotImplementedError


class StrValueConverter(ValueConverter):

  def __call__(self, value):
    if isinstance(value, hwid_rule.Value):
      return re.compile(value.raw_value) if value.is_re else value.raw_value
    return str(value)


class TruncatedStrValueConverter(ValueConverter):

  def __init__(self, truncated_length: int = 0):
    self._truncated_length = truncated_length

  def __call__(self, value):
    if isinstance(value, hwid_rule.Value):
      return re.compile(value.raw_value) if value.is_re else value.raw_value
    space_count = self._truncated_length - len(value)
    if space_count > 0:
      # TODO: Use raw f-string once yapf supports it.
      return re.compile(f'{re.escape(value)}(\\s{{{space_count}}}.*)?')
    return re.compile(f'{re.escape(value)}.*')


class IntValueConverter(ValueConverter):

  def __call__(self, value):
    return int(value)


class HexToHexValueConverter(ValueConverter):

  def __init__(self, num_digits, has_prefix=True):
    self._num_digits = num_digits
    self._has_prefix = has_prefix

  def __call__(self, value):
    prefix = '0x' if self._has_prefix else ''
    if not re.fullmatch(f'{prefix}0*[0-9a-fA-F]{{1,{self._num_digits}}}',
                        value):
      raise ValueError(
          f'Not a regular string of {self._num_digits} digits hex number.')
    # Regulate the output to the fixed-digit hex string with upper cases.
    return value.upper()[len(prefix):][-self._num_digits:].zfill(
        self._num_digits)


class IntToHexValueConverter(ValueConverter):

  def __init__(self, num_digits):
    self._num_digits = num_digits
    self._hex_to_hex_converter = HexToHexValueConverter(self._num_digits,
                                                        has_prefix=False)

  def __call__(self, value):
    value = f'{int(value):04x}'
    return self._hex_to_hex_converter(value)


class FloatToHexValueConverter(ValueConverter):

  def __init__(self, num_digits):
    self._num_digits = num_digits
    self._hex_to_hex_converter = HexToHexValueConverter(self._num_digits,
                                                        has_prefix=False)

  def __call__(self, value):
    value = f'{int(float(value)):04x}'
    return self._hex_to_hex_converter(value)


class BatteryTechnologySysfsValueConverter(ValueConverter):
  VALUE_ALLOWLIST = COMMON_SYSFS_TECHNOLOGY

  def __init__(self):
    self._str_converter = StrValueConverter()

  def __call__(self, value):
    if value in self.VALUE_ALLOWLIST:
      return self._str_converter(value)
    raise ValueError(f'Unknown battery technology {value}.')


class InputDeviceVendorValueConverter(ValueConverter):
  ELAN_VID = '04F3'
  RAYD_VID = '27A3'

  def __init__(self):
    self._str_converter = StrValueConverter()
    self._hex_to_hex_converter = HexToHexValueConverter(4, has_prefix=False)

  def __call__(self, value):
    value = self._str_converter(value)
    if re.fullmatch(r'ELAN\d{4}:\d{2}', value) or re.fullmatch(
        r'ekth\d{4}', value):
      return self._hex_to_hex_converter(self.ELAN_VID)
    if value == 'Raydium Touchscreen' or re.fullmatch(r'RAYD\d{4}:\d{2}',
                                                      value):
      return self._hex_to_hex_converter(self.RAYD_VID)
    raise ValueError(f'Unknown input device id {value}.')


class MissingComponentValueError(Exception):
  """Some required component values are missing so that they should not be
  converted by this generator."""


class ProbeStatementConversionError(Exception):
  """The given component values are considered invalid so that it cannot be
  converted by this generator."""


class _FieldRecord:
  """Record to describe the expected field and corresponding conversion method.

  Attributes:
    hwid_field_names: The name or a list of names of HWID field(s) to be
        converted from.
    probe_statement_field_name: The probe statement field name.
    value_converters: The converter or a list of converters converting HWID
        values.
    is_optional: Whether this record is optional.
    skip_values: Set of values to skip generating the expected value for this
        field.
  """

  def __init__(
      self, hwid_field_names: Union[str,
                                    List[str]], probe_statement_field_name: str,
      value_converters: Union[ValueConverter, List[ValueConverter]],
      is_optional: bool = False, skip_values: Optional[Set[str]] = None):
    self.hwid_field_names = type_utils.MakeList(hwid_field_names)
    self.probe_statement_field_name = probe_statement_field_name
    self.value_converters = type_utils.MakeList(value_converters)
    self.is_optional = is_optional
    self.skip_values = skip_values or set()

  def GenerateExpectedFields(self, comp_values: dict) -> Optional[str]:
    """Generates the expected field from a given component.

    This function generates the expected field from a given component using
    predefined fields and value converters.

    If any of the HWID fields found in `comp_values` is in `self.skip_values`,
    this function will return `None`. If there are not any HWID fields found in
    `comp_values`, this function will raise `MissingComponentValueError` if
    `is_optional` is `False`, otherwise return `None`.  If there are zero or
    multiple HWID fields covertible with the converters, this function will
    raise `ProbeStatementConversionError`, otherwise return the converted value.
    """
    expected_field = []
    valid_hwid_field_names = [
        name for name in self.hwid_field_names if name in comp_values
    ]

    for hwid_field_name in valid_hwid_field_names:
      comp_value = comp_values[hwid_field_name]
      if isinstance(comp_value, str) and comp_value in self.skip_values:
        # The value in HWID can be ignored. Don't generate expected value
        # for this field.
        return None

    err = None
    for hwid_field_name in valid_hwid_field_names:
      for value_converter in self.value_converters:
        try:
          expected_field.append(value_converter(comp_values[hwid_field_name]))
          break
        except Exception as e:
          if err is None:
            err = e

    if not expected_field:
      if self.is_optional:
        return None
      if not valid_hwid_field_names:
        raise MissingComponentValueError(
            'Missing component value field(s) for field '
            f'{self.probe_statement_field_name!r} : {self.hwid_field_names!r}.')
      raise ProbeStatementConversionError(
          'Unable to convert the value of field '
          f'{self.probe_statement_field_name!r} : {err!r}.')
    for value in expected_field:
      if value != expected_field[0]:
        raise ProbeStatementConversionError(
            'Found multiple valid component value fields for field '
            f'{self.probe_statement_field_name!r}.')
    return expected_field[0]


class _SameNameFieldRecord(_FieldRecord):
  """FieldRecord with same HWID field name and probe statement field name."""

  def __init__(self, n, c, *args, **kwargs):
    super().__init__(n, n, c, *args, **kwargs)


class _ProbeStatementGenerator:

  def __init__(self, probe_category, probe_function_name, field_converters,
               probe_function_argument=None):
    self.probe_category = probe_category
    self.has_multiple_converters = False

    self._probe_statement_generator = (
        probe_config_definition.GetProbeStatementDefinition(probe_category))
    self._probe_function_name = probe_function_name
    if field_converters and isinstance(field_converters[0], _FieldRecord):
      self._field_converters = [field_converters]
    else:
      self._field_converters = field_converters
      self.has_multiple_converters = True
    self._probe_function_argument = probe_function_argument

  def TryGenerate(self, comp_name, comp_values, information=None):

    expected_fields_list = []
    err = None
    for fcs in self._field_converters:
      counter = collections.Counter(fc.probe_statement_field_name for fc in fcs)
      repeated_keys = [k for k in counter if counter[k] > 1]
      if repeated_keys:
        raise ValueError('Repeated probe_statement_field_name in '
                         f'field_converters: {repeated_keys}.')
      try:
        expected_fields = {}
        for fc in fcs:
          expected_fields[fc.probe_statement_field_name] = (
              fc.GenerateExpectedFields(comp_values))
        expected_fields_list.append(expected_fields)
      except Exception as e:
        if err is None:
          err = e
    if not expected_fields_list:
      raise err

    try:
      return self._probe_statement_generator.GenerateProbeStatement(
          comp_name, self._probe_function_name, expected_fields_list,
          probe_function_argument=self._probe_function_argument,
          information=information)
    except Exception as e:
      raise ProbeStatementConversionError(
          f'Unable to convert to the probe statement : {e!r}.') from None


@type_utils.CachedGetter
def GetAllProbeStatementGenerators():

  str_converter = StrValueConverter()
  int_converter = IntValueConverter()

  all_probe_statement_generators = {}

  all_probe_statement_generators['battery'] = [
      _ProbeStatementGenerator(
          'battery',
          'generic_battery',
          [
              [
                  _SameNameFieldRecord('chemistry', str_converter,
                                       skip_values=COMMON_ECTOOL_CHEMISTRY),
                  _SameNameFieldRecord('manufacturer', str_converter),
                  _SameNameFieldRecord('model_name', str_converter),
              ],
              # Components from sysfs. Since the maximum length of the
              # manufacturer field and the model_name field are both 7 and the
              # trailing spaces will be truncated, we should fill the space if
              # it is too short and do a prefix matching.
              [
                  _SameNameFieldRecord(
                      'manufacturer',
                      TruncatedStrValueConverter(
                          BATTERY_SYSFS_MANUFACTURER_MAX_LENGTH)),
                  _SameNameFieldRecord(
                      'model_name',
                      TruncatedStrValueConverter(
                          BATTERY_SYSFS_MODEL_NAME_MAX_LENGTH)),
                  _SameNameFieldRecord('technology',
                                       BatteryTechnologySysfsValueConverter()),
              ],
              # Components from EC.
              # For the chemistry field, keep only vendor-specific value.
              [
                  _SameNameFieldRecord('manufacturer', str_converter),
                  _SameNameFieldRecord('model_name', str_converter),
                  _FieldRecord('technology', 'chemistry', str_converter,
                               skip_values=COMMON_HWID_TECHNOLOGY),
              ]
          ])
  ]

  storage_shared_fields = [_SameNameFieldRecord('sectors', int_converter)]
  all_probe_statement_generators['storage'] = [
      # eMMC
      _ProbeStatementGenerator(
          'storage', 'generic_storage', storage_shared_fields + [
              _FieldRecord(['hwrev', 'mmc_hwrev'], 'mmc_hwrev',
                           HexToHexValueConverter(1), is_optional=True),
              _FieldRecord(['name', 'mmc_name'], 'mmc_name', str_converter),
              _FieldRecord(['manfid', 'mmc_manfid'], 'mmc_manfid',
                           HexToHexValueConverter(2)),
              _FieldRecord(['oemid', 'mmc_oemid'], 'mmc_oemid',
                           HexToHexValueConverter(4)),
              _FieldRecord(['prv', 'mmc_prv'], 'mmc_prv',
                           HexToHexValueConverter(2), is_optional=True),
              _FieldRecord(['serial', 'mmc_serial'], 'mmc_serial',
                           HexToHexValueConverter(8), is_optional=True),
          ]),
      # NVMe
      _ProbeStatementGenerator(
          'storage', 'generic_storage', storage_shared_fields + [
              _FieldRecord(['vendor', 'pci_vendor'], 'pci_vendor',
                           HexToHexValueConverter(4)),
              _FieldRecord(['device', 'pci_device'], 'pci_device',
                           HexToHexValueConverter(4)),
              _FieldRecord(['class', 'pci_class'], 'pci_class',
                           HexToHexValueConverter(6)),
              _SameNameFieldRecord('nvme_model', str_converter,
                                   is_optional=True),
          ]),
      # ATA
      _ProbeStatementGenerator(
          'storage', 'generic_storage', storage_shared_fields + [
              _FieldRecord(['vendor', 'ata_vendor'], 'ata_vendor',
                           str_converter),
              _FieldRecord(['model', 'ata_model'], 'ata_model', str_converter),
          ]),
      # UFS
      _ProbeStatementGenerator(
          'storage', 'generic_storage', storage_shared_fields + [
              _FieldRecord(['vendor', 'ufs_vendor'], 'ufs_vendor',
                           str_converter),
              _FieldRecord(['model', 'ufs_model'], 'ufs_model', str_converter),
          ]),
  ]

  # TODO(yhong): Also convert SDIO network component probe statements.
  network_pci_fields = [
      _FieldRecord('vendor', 'pci_vendor_id', HexToHexValueConverter(4)),
      # TODO(yhong): Set `pci_device_id` to non optional field when b/150914933
      #     is resolved.
      _FieldRecord('device', 'pci_device_id', HexToHexValueConverter(4),
                   is_optional=True),
      _FieldRecord('revision_id', 'pci_revision', HexToHexValueConverter(2),
                   is_optional=True),
      _FieldRecord('subsystem_device', 'pci_subsystem',
                   HexToHexValueConverter(4), is_optional=True),
  ]
  network_sdio_fields = [
      _FieldRecord('vendor', 'sdio_vendor_id', HexToHexValueConverter(4)),
      _FieldRecord('device', 'sdio_device_id', HexToHexValueConverter(4)),
  ]
  usb_fields = [
      _FieldRecord(['idVendor', 'usb_vendor_id'], 'usb_vendor_id',
                   HexToHexValueConverter(4, has_prefix=False)),
      _FieldRecord(['idProduct', 'usb_product_id'], 'usb_product_id',
                   HexToHexValueConverter(4, has_prefix=False)),
      _FieldRecord(['bcdDevice', 'usb_bcd_device'], 'usb_bcd_device',
                   HexToHexValueConverter(4, has_prefix=False),
                   is_optional=True),
  ]
  all_probe_statement_generators['cellular'] = [
      _ProbeStatementGenerator(
          'cellular', 'network', network_pci_fields,
          probe_function_argument={'device_type': 'cellular'}),
      _ProbeStatementGenerator(
          'cellular', 'network', usb_fields,
          probe_function_argument={'device_type': 'cellular'}),
  ]
  all_probe_statement_generators['ethernet'] = [
      _ProbeStatementGenerator(
          'ethernet', 'network', network_pci_fields,
          probe_function_argument={'device_type': 'ethernet'}),
      _ProbeStatementGenerator(
          'ethernet', 'network', usb_fields,
          probe_function_argument={'device_type': 'ethernet'}),
  ]
  all_probe_statement_generators['wireless'] = [
      _ProbeStatementGenerator('wireless', 'network',
                               [network_pci_fields, network_sdio_fields],
                               probe_function_argument={'device_type': 'wifi'}),
      _ProbeStatementGenerator('wireless', 'network', usb_fields,
                               probe_function_argument={'device_type': 'wifi'}),
  ]

  dram_fields = [
      _SameNameFieldRecord('part', str_converter),
      _SameNameFieldRecord('size', int_converter),
      _SameNameFieldRecord('slot', int_converter, is_optional=True),
  ]
  all_probe_statement_generators['dram'] = [
      _ProbeStatementGenerator('dram', 'memory', dram_fields),
  ]

  input_device_fields = [
      _SameNameFieldRecord('name', str_converter),
      _SameNameFieldRecord(
          'product',
          [
              HexToHexValueConverter(4, has_prefix=False),
              # raydium_ts
              HexToHexValueConverter(8, has_prefix=True),
          ]),
      _SameNameFieldRecord('vendor', HexToHexValueConverter(
          4, has_prefix=False)),
  ]
  input_device_fields_old = [
      _FieldRecord(
          ['product_id', 'hw_version'],
          'product',
          [
              HexToHexValueConverter(4, has_prefix=False),
              # raydium_ts
              HexToHexValueConverter(8, has_prefix=True),
              FloatToHexValueConverter(4),
          ]),
      _FieldRecord(['vendor_id', 'id', 'name'], 'vendor', [
          HexToHexValueConverter(4, has_prefix=False),
          InputDeviceVendorValueConverter(),
      ]),
  ]
  all_probe_statement_generators['stylus'] = [
      _ProbeStatementGenerator(
          'stylus', 'input_device', input_device_fields,
          probe_function_argument={'device_type': 'stylus'}),
      _ProbeStatementGenerator(
          'stylus', 'input_device', input_device_fields_old,
          probe_function_argument={'device_type': 'stylus'}),
  ]
  all_probe_statement_generators['touchpad'] = [
      _ProbeStatementGenerator(
          'touchpad', 'input_device', input_device_fields,
          probe_function_argument={'device_type': 'touchpad'}),
      _ProbeStatementGenerator(
          'touchpad', 'input_device', input_device_fields_old,
          probe_function_argument={'device_type': 'touchpad'}),
  ]
  all_probe_statement_generators['touchscreen'] = [
      _ProbeStatementGenerator(
          'touchscreen', 'input_device', input_device_fields,
          probe_function_argument={'device_type': 'touchscreen'}),
      _ProbeStatementGenerator(
          'touchscreen', 'input_device', input_device_fields_old,
          probe_function_argument={'device_type': 'touchscreen'}),
  ]

  mipi_fields_eeprom = [
      _FieldRecord(['module_id', 'mipi_module_id'], 'mipi_module_id',
                   str_converter),
      _FieldRecord(['sensor_id', 'mipi_sensor_id'], 'mipi_sensor_id',
                   str_converter),
  ]
  mipi_fields_v4l2 = [
      _FieldRecord(['name', 'mipi_name'], 'mipi_name', str_converter),
      _FieldRecord(['vendor', 'mipi_vendor'], 'mipi_vendor',
                   HexToHexValueConverter(4, has_prefix=True),
                   is_optional=True),
  ]

  # This is the old name for video_codec + camera.
  all_probe_statement_generators['video'] = [
      _ProbeStatementGenerator('camera', 'usb_camera', usb_fields),
      _ProbeStatementGenerator('camera', 'mipi_camera', mipi_fields_eeprom),
      _ProbeStatementGenerator('camera', 'mipi_camera', mipi_fields_v4l2),
  ]
  all_probe_statement_generators['camera'] = [
      _ProbeStatementGenerator('camera', 'usb_camera', usb_fields),
      _ProbeStatementGenerator('camera', 'mipi_camera', mipi_fields_eeprom),
      _ProbeStatementGenerator('camera', 'mipi_camera', mipi_fields_v4l2),
  ]

  display_panel_fields = [
      _SameNameFieldRecord('height', int_converter),
      _SameNameFieldRecord('product_id',
                           HexToHexValueConverter(4, has_prefix=False)),
      _SameNameFieldRecord('vendor', str_converter),
      _SameNameFieldRecord('width', int_converter),
  ]
  all_probe_statement_generators['display_panel'] = [
      _ProbeStatementGenerator('display_panel', 'edid', display_panel_fields),
  ]

  return all_probe_statement_generators


@type_utils.CachedGetter
def GetMultiExpectedFieldsCategories():
  """Get component categories that may generate multiple expected fields lists

  This function checks all probe statement generators, and collects the probe
  categories of the generators that have multiple converters and thus may
  generate multiple expected fields lists.

  Returns:
    A frozenset contains all the probe categories that may generate multiple
    expected fields lists.
  """
  return frozenset(ps_gen.probe_category
                   for ps_gens in GetAllProbeStatementGenerators().values()
                   for ps_gen in ps_gens
                   if ps_gen.has_multiple_converters)


class VerificationPayloadGenerationResult(NamedTuple):
  """
  Attributes:
    generated_file_contents: A string-to-string dictionary which represents the
        files that should be committed into the bsp package.
    error_msgs: A list of errors encountered during the generation.
    payload_hash: Hash of the payload.
    primary_identifiers: An instance of collections.defaultdict(dict) mapping
        `model` to {(category, component name): target component name} which
        groups components with same probe statement.
  """
  generated_file_contents: dict
  error_msgs: list
  payload_hash: str
  primary_identifiers: DefaultDict[str, Dict]


ComponentVerificationPayloadPiece = collections.namedtuple(
    'ComponentVerificationPayloadPiece',
    ['is_duplicate', 'error_msg', 'probe_statement', 'component_info'])

_STATUS_MAP = {
    hwid_common.ComponentStatus.supported: hardware_verifier_pb2.QUALIFIED,
    hwid_common.ComponentStatus.unqualified: hardware_verifier_pb2.UNQUALIFIED,
    hwid_common.ComponentStatus.deprecated: hardware_verifier_pb2.QUALIFIED,
    hwid_common.ComponentStatus.unsupported: hardware_verifier_pb2.REJECTED,
}

_QUAL_STATUS_PREFERENCE = {
    hardware_verifier_pb2.QUALIFIED: 0,
    hardware_verifier_pb2.UNQUALIFIED: 1,
    hardware_verifier_pb2.REJECTED: 2,
}

_ProbeRequestSupportCategory = runtime_probe_pb2.ProbeRequest.SupportCategory


def GenerateProbeStatement(ps_gens, comp_name, comp_info):
  err = None
  error_msg = None
  all_suitable_generator_and_ps = []

  for ps_gen in ps_gens:
    try:
      ps = ps_gen.TryGenerate(comp_name, comp_info.values,
                              comp_info.information)
    except MissingComponentValueError:
      continue
    except Exception as e:
      if err is None:
        err = e
    else:
      all_suitable_generator_and_ps.append((ps_gen, ps))

  if not all_suitable_generator_and_ps:
    if isinstance(err, ProbeStatementConversionError):
      error_msg = ('Failed to generate the probe statement for component '
                   f'{comp_name!r}: {err!r}.')
    else:
      # Ignore this component if no any generator are suitable for it.
      return None

  is_duplicate = comp_info.status == hwid_common.ComponentStatus.duplicate
  if is_duplicate or error_msg:
    probe_statement = None
    component_info = None
  else:
    ps_gen, probe_statement = all_suitable_generator_and_ps[0]
    component_info = hardware_verifier_pb2.ComponentInfo(
        component_category=_ProbeRequestSupportCategory.Value(
            ps_gen.probe_category), component_uuid=comp_name,
        qualification_status=_STATUS_MAP[comp_info.status])

  return ComponentVerificationPayloadPiece(is_duplicate, error_msg,
                                           probe_statement, component_info)


def GetAllComponentVerificationPayloadPieces(
    db, vpg_config: Optional[
        vpg_config_module.VerificationPayloadGeneratorConfig] = None,
    skip_comp_names: Optional[Set[str]] = None):
  """Generates materials for verification payload from each components in HWID.

  This function goes over each component in HWID one-by-one, and attempts to
  derive the corresponding material for building up the final verification
  payload.

  Args:
    db: An instance of HWID database.
    vpg_config: Config for the generator.

  Returns:
    A dictionary that maps the HWID component to the corresponding material.
    The key is a pair of the component category and the component name.  The
    value is an instance of `ComponentVerificationPayloadPiece`.  Callers can
    also look up whether a specific component is in the returned dictionary
    to know whether that component is covered by this verification payload
    generator.
  """
  ret = {}

  model_prefix = db.project.lower()
  if vpg_config is None:
    vpg_config = vpg_config_module.VerificationPayloadGeneratorConfig.Create()
  for hwid_comp_category, ps_gens in GetAllProbeStatementGenerators().items():
    if hwid_comp_category in vpg_config.waived_comp_categories:
      continue
    comps = db.GetComponents(hwid_comp_category, include_default=False)
    for comp_name, comp_info in comps.items():
      if skip_comp_names and comp_name in skip_comp_names:
        continue
      unique_comp_name = model_prefix + '_' + comp_name
      vp_piece = GenerateProbeStatement(ps_gens, unique_comp_name, comp_info)
      if vp_piece is None:
        continue
      if hwid_comp_category in vpg_config.ignore_error:
        vp_piece = vp_piece._replace(error_msg=None)
      ret[hwid_comp_category, comp_name] = vp_piece
  return ret


def GenerateVerificationPayload(dbs):
  """Generates the corresponding verification payload from the given HWID DBs.

  This function ignores the component categories that no corresponding generator
  can handle.  For example, if no generator can handle the `cpu` category,
  this function will ignore all CPU components.  If at least one generator
  class can handle `cpu` category but all related generators fail to handle
  any of the `cpu` component in the given HWID databases, this function raises
  exception to indicate a failure.

  Args:
    dbs: A list of tuple of the HWID database object and the config for the
        generator.

  Returns:
    Instance of `VerificationPayloadGenerationResult`.
  """

  def _ComponentSortKey(comp_vp_piece):
    return (_QUAL_STATUS_PREFERENCE.get(
        comp_vp_piece.component_info.qualification_status,
        3), comp_vp_piece.probe_statement.component_name)

  def _StripModelPrefix(comp_name, model):
    """Strip the known model prefix in comp name."""

    model = model.lower()
    if not comp_name.startswith(model + '_'):
      raise ValueError(r'Component name {comp_name!r} does not start with'
                       r'"{model}_".')
    return comp_name.partition('_')[2]

  def _CollectPrimaryIdentifiers(grouped_comp_vp_piece_per_model,
                                 grouped_primary_comp_name_per_model):
    """Collect the mappings from grouped comp_vp_pieces.

    This function extracts the required fields (model, category, component name,
    and targeted component name) for deduplicating probe
    statements from ComponentVerificationPayloadPiece which contains unnecessary
    information.
    """

    primary_identifiers = collections.defaultdict(dict)
    for model, grouped_comp_vp_piece in grouped_comp_vp_piece_per_model.items():
      grouped_primary_comp_name = grouped_primary_comp_name_per_model[model]
      for hash_value, comp_vp_piece_list in grouped_comp_vp_piece.items():
        if len(comp_vp_piece_list) <= 1:
          continue
        primary_component_name = grouped_primary_comp_name[hash_value]
        for comp_vp_piece in comp_vp_piece_list:
          probe_statement = comp_vp_piece.probe_statement
          if probe_statement.component_name == primary_component_name:
            continue
          primary_identifiers[model][
              probe_statement.category_name,
              _StripModelPrefix(probe_statement
                                .component_name, model)] = _StripModelPrefix(
                                    primary_component_name, model)
    return primary_identifiers

  def _MergeExpectedFields(probe_config, vp_pieces):
    """Merge the same expected fields in different components.

    This function traverses components in vp_pieces in qualification status
    order. For every component, if the expected fields were also in the previous
    components, skip generating probe statement for these fields. Or else, add
    them to probe_config.
    """
    vp_pieces.sort(key=_ComponentSortKey)
    # Map expect fields string to the component.
    comp_expects = {}

    for vp_piece in vp_pieces:
      expect_fields = vp_piece.probe_statement.statement.get('expect')
      if isinstance(expect_fields, dict):
        expect_fields = [expect_fields]

      new_expect_fields = []
      for expect_field in expect_fields:
        expect_field_str = json_utils.DumpStr(expect_field, sort_keys=True)
        if expect_field_str in comp_expects:
          main_category, main_component = comp_expects[expect_field_str]
          merged_category = vp_piece.probe_statement.category_name
          merged_component = vp_piece.probe_statement.component_name
          logging.info('Some expected fields of %s/%s are merged into %s/%s',
                       merged_category, merged_component, main_category,
                       main_component)
        else:
          category = vp_piece.probe_statement.category_name
          component = vp_piece.probe_statement.component_name
          comp_expects[expect_field_str] = (category, component)
          new_expect_fields.append(expect_field)

      if not new_expect_fields:
        # All expected fields of this component were merged into previous
        # components. Skip generating probe statements for it.
        vp_piece.probe_statement.UpdateExpect({})
        continue

      if len(new_expect_fields) == 1:
        vp_piece.probe_statement.UpdateExpect(new_expect_fields[0])
      else:
        vp_piece.probe_statement.UpdateExpect(new_expect_fields)

      probe_config.AddComponentProbeStatement(vp_piece.probe_statement)

  def _CheckShouldSkipBattery(battery_lhs: Mapping[str, str],
                              battery_rhs: Mapping[str, str]):
    """Check if we should skip generating probe statements for either
    `battery_lhs` or `battery_rhs`.

    Return True if the following are satisfied:
    1. `model_name` and `manufacturer` of one battery are prefixes of the
       corresponding field values of the other.
    2. At least one of `model_name`, `manufacturer` and `technology` are
       different between the two batteries.
    3. At least one of the batteries' `technology` is Li-ion, Li-poly, LION,
       LiP, or LIP.
    """

    for field in ['model_name', 'manufacturer', 'technology']:
      field_lhs = battery_lhs.get(field)
      field_rhs = battery_rhs.get(field)
      if field_lhs != field_rhs:
        break
    else:
      # Return False on the special case that all fields are the same between
      # two batteries.
      return False

    lhs_technology = battery_lhs.get('technology')
    rhs_technology = battery_rhs.get('technology')
    if not (lhs_technology in COMMON_HWID_TECHNOLOGY or
            rhs_technology in COMMON_HWID_TECHNOLOGY):
      return False

    lhs_match = True
    rhs_match = True

    for field, min_length in [
        ('model_name', BATTERY_SYSFS_MODEL_NAME_MAX_LENGTH),
        ('manufacturer', BATTERY_SYSFS_MANUFACTURER_MAX_LENGTH)
    ]:
      field_lhs = battery_lhs.get(field)
      field_rhs = battery_rhs.get(field)
      if not (isinstance(field_lhs, str) and isinstance(field_rhs, str)):
        return False

      field_lhs = field_lhs.ljust(min_length)
      field_rhs = field_rhs.ljust(min_length)

      if not field_rhs.startswith(field_lhs):
        lhs_match = False
      if not field_lhs.startswith(field_rhs):
        rhs_match = False

    return lhs_match or rhs_match

  def _CollectSkipCompNames(db: database.Database) -> Set[str]:
    """Collect a set of component names for which we should skip generating
    probe statements.

    This function checks all components in `db` and collect those for which we
    should skip generating probe statements. Currently it only checks battery
    components.
    """
    skip_comp_names = set()

    batteries = db.GetComponents('battery', include_default=False)

    def BatteryKeyFunc(comp_name: str):
      """Key function for deciding which battery to skip.

      The battery with larger key returned by this function is going to be
      skipped, in the order:
      1. Qualification status.
      2. Length of model_name (skip the longer one).
      3. Length of manufacturer (skip the longer one).
      4. Component name (skip the lexicographically larger one).
      """
      component = batteries[comp_name]
      model_name = component.values['model_name']
      manufacturer = component.values['manufacturer']
      status = _STATUS_MAP.get(component.status)
      qual = _QUAL_STATUS_PREFERENCE.get(status, 3)

      return (qual, len(model_name), len(manufacturer), comp_name)

    for comp_name_1, comp_name_2 in itertools.combinations(batteries, 2):
      if comp_name_1 in skip_comp_names or comp_name_2 in skip_comp_names:
        continue

      comp_1 = batteries[comp_name_1].values
      comp_2 = batteries[comp_name_2].values

      if _CheckShouldSkipBattery(comp_1, comp_2):
        skip_comp_names.add(max(comp_name_1, comp_name_2, key=BatteryKeyFunc))

    return skip_comp_names

  error_msgs = []
  generated_file_contents = {}

  grouped_comp_vp_piece_per_model = {}
  grouped_primary_comp_name_per_model = {}
  hw_verification_spec = hardware_verifier_pb2.HwVerificationSpec()
  multi_exp_categories = GetMultiExpectedFieldsCategories()

  for db, vpg_config in dbs:
    model_prefix = db.project.lower()
    probe_config = probe_config_types.ProbeConfigPayload()

    skip_comp_names = _CollectSkipCompNames(db)
    if skip_comp_names:
      logging.info('Skip generating payload for components: %s',
                   skip_comp_names)

    all_pieces = GetAllComponentVerificationPayloadPieces(
        db, vpg_config, skip_comp_names)
    grouped_comp_vp_piece = collections.defaultdict(list)
    grouped_primary_comp_name = {}
    grouped_merge_vp_piece = collections.defaultdict(list)
    for comp_vp_piece in all_pieces.values():
      if comp_vp_piece.is_duplicate:
        continue
      if comp_vp_piece.error_msg:
        error_msgs.append(comp_vp_piece.error_msg)
      if comp_vp_piece.probe_statement:
        grouped_comp_vp_piece[
            comp_vp_piece.probe_statement.statement_hash].append(comp_vp_piece)

    for hash_val, comp_vp_piece_list in grouped_comp_vp_piece.items():
      comp_vp_piece = min(comp_vp_piece_list, key=_ComponentSortKey)
      grouped_primary_comp_name[
          hash_val] = comp_vp_piece.probe_statement.component_name
      comp_category = comp_vp_piece.probe_statement.category_name
      hw_verification_spec.component_infos.append(comp_vp_piece.component_info)
      if comp_category in multi_exp_categories:
        grouped_merge_vp_piece[comp_category].append(comp_vp_piece)
      else:
        probe_config.AddComponentProbeStatement(comp_vp_piece.probe_statement)

    for vp_pieces in grouped_merge_vp_piece.values():
      _MergeExpectedFields(probe_config, vp_pieces)

    # Append the generic probe statements.
    for ps_gen in _GetAllGenericProbeStatementInfoRecords():
      if ps_gen.probe_category not in vpg_config.waived_comp_categories:
        probe_config.AddComponentProbeStatement(ps_gen.GenerateProbeStatement())

    probe_config_pathname = f'runtime_probe/{model_prefix}/probe_config.json'
    generated_file_contents[probe_config_pathname] = probe_config.DumpToString()
    grouped_comp_vp_piece_per_model[db.project] = grouped_comp_vp_piece
    grouped_primary_comp_name_per_model[db.project] = grouped_primary_comp_name

  primary_identifiers = _CollectPrimaryIdentifiers(
      grouped_comp_vp_piece_per_model, grouped_primary_comp_name_per_model)

  hw_verification_spec.component_infos.sort(
      key=lambda ci: (ci.component_category, ci.component_uuid))

  # Append the allowlists in the verification spec.
  for ps_info in _GetAllGenericProbeStatementInfoRecords():
    hw_verification_spec.generic_component_value_allowlists.add(
        component_category=_ProbeRequestSupportCategory.Value(
            ps_info.probe_category), field_names=list(ps_info.allowlist_fields))

  generated_file_contents[
      'hw_verification_spec.prototxt'] = text_format.MessageToString(
          hw_verification_spec)
  payload_json = json_utils.DumpStr(generated_file_contents, sort_keys=True)
  payload_hash = hashlib.sha1(payload_json.encode('utf-8')).hexdigest()

  return VerificationPayloadGenerationResult(
      generated_file_contents, error_msgs, payload_hash, primary_identifiers)


def main():
  # only import the required modules while running this module as a program
  import argparse
  import os
  import sys

  from cros.factory.utils import file_utils

  ap = argparse.ArgumentParser(
      description=('Generate the verification payload source files from the '
                   'given HWID databases.'))
  ap.add_argument(
      '-o', '--output_dir', metavar='PATH',
      help=('Base path to the output files. In most of the cases, '
            'it should be '
            'chromeos-base/racc-config-<BOARD>/files '
            'in a private overlay repository.'))
  ap.add_argument(
      'hwid_db_paths', metavar='HWID_DATABASE_PATH', nargs='+',
      help=('Paths to the input HWID databases. If the board '
            'has multiple models, users should specify all models '
            'at once.'))
  ap.add_argument(
      '--ignore_error', nargs='*', default=[], dest='ignore_error',
      help=('Ignore error messages for component category, must specify in '
            'format of `<model_name>.<category_name>`.'))
  ap.add_argument(
      '--waived_comp_category', nargs='*', default=[], dest='waived_categories',
      help=('Waived component category, must specify in format of '
            '`<model_name>.<category_name>`.'))
  args = ap.parse_args()

  logging.basicConfig(level=logging.INFO)

  waived_categories = collections.defaultdict(list)
  for waived_category in args.waived_categories:
    model_name, unused_sep, category_name = waived_category.partition('.')
    waived_categories[model_name.lower()].append(category_name)

  ignore_error = collections.defaultdict(list)
  for category in args.ignore_error:
    model_name, unused_sep, category_name = category.partition('.')
    ignore_error[model_name.lower()].append(category_name)

  dbs = []
  for hwid_db_path in args.hwid_db_paths:
    logging.info('Load the HWID database file (%s).', hwid_db_path)
    db = database.Database.LoadFile(hwid_db_path, verify_checksum=False)
    vpg_config = vpg_config_module.VerificationPayloadGeneratorConfig.Create(
        ignore_error=ignore_error[db.project.lower()],
        waived_comp_categories=waived_categories[db.project.lower()])
    logging.info('Waived component category: %r',
                 vpg_config.waived_comp_categories)
    logging.info('Ignore exception component category: %r',
                 vpg_config.ignore_error)
    dbs.append((db, vpg_config))

  logging.info('Generate the verification payload data.')
  result = GenerateVerificationPayload(dbs)
  for model, mapping in result.primary_identifiers.items():
    logs = [f'Found duplicate probe statements for model {model}:']
    for (category, comp_name), primary_comp_name in mapping.items():
      logs.append(f'  {category}/{comp_name} will be mapped to '
                  f'{category}/{primary_comp_name}.')
    logging.info('\n'.join(logs))

  if result.error_msgs:
    for error_msg in result.error_msgs:
      logging.error(error_msg)
    sys.exit(1)

  for pathname, content in result.generated_file_contents.items():
    logging.info('Output the verification payload file (%s).', pathname)
    fullpath = os.path.join(args.output_dir, pathname)
    file_utils.TryMakeDirs(os.path.dirname(fullpath))
    file_utils.WriteFile(fullpath, content)
  logging.info('Payload hash: %s', result.payload_hash)


if __name__ == '__main__':
  main()
