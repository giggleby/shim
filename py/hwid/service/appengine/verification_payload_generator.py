#!/usr/bin/env python3
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Methods to generate the verification payload from the HWID database."""

import collections
import hashlib
import re
from typing import DefaultDict, Dict, List, NamedTuple, Optional, Union

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
      GenericProbeStatementInfoRecord('cellular', 'cellular_network', [
          'bus_type', 'pci_vendor_id', 'pci_device_id', 'pci_revision',
          'pci_subsystem', 'usb_vendor_id', 'usb_product_id', 'usb_bcd_device'
      ]),
      GenericProbeStatementInfoRecord('ethernet', 'ethernet_network', [
          'bus_type', 'pci_vendor_id', 'pci_device_id', 'pci_revision',
          'pci_subsystem', 'usb_vendor_id', 'usb_product_id', 'usb_bcd_device'
      ]),
      GenericProbeStatementInfoRecord('wireless', 'wireless_network', [
          'bus_type', 'pci_vendor_id', 'pci_device_id', 'pci_revision',
          'pci_subsystem', 'usb_vendor_id', 'usb_product_id', 'usb_bcd_device',
          'sdio_vendor_id', 'sdio_device_id'
      ]),
      GenericProbeStatementInfoRecord('dram', 'memory',
                                      ['part', 'size', 'slot']),
      # TODO(yhong): Include other type of cameras if needed.
      GenericProbeStatementInfoRecord(
          'camera', 'usb_camera', {
              'bus_type': None,
              'usb_vendor_id': None,
              'usb_product_id': None,
              'usb_bcd_device': None,
              'usb_removable': re.compile('^(FIXED|UNKNOWN)$'),
          }),
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


class StrPrefixValueConverter(ValueConverter):

  def __call__(self, value):
    if isinstance(value, hwid_rule.Value):
      return re.compile(value.raw_value) if value.is_re else value.raw_value
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
    if not re.match('%s0*[0-9a-fA-F]{1,%d}$' %
                    (prefix, self._num_digits), value):
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
    value = '%04x' % int(value)
    return self._hex_to_hex_converter(value)


class FloatToHexValueConverter(ValueConverter):

  def __init__(self, num_digits):
    self._num_digits = num_digits
    self._hex_to_hex_converter = HexToHexValueConverter(self._num_digits,
                                                        has_prefix=False)

  def __call__(self, value):
    value = '%04x' % int(float(value))
    return self._hex_to_hex_converter(value)


class BatteryTechnologySysfsValueConverter(ValueConverter):
  VALUE_ALLOWLIST = ['Li-ion', 'Li-poly']

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
    if re.match(r'ELAN\d{4}:\d{2}$', value) or re.match(r'ekth\d{4}$', value):
      return self._hex_to_hex_converter(self.ELAN_VID)
    if value == 'Raydium Touchscreen' or re.match(r'RAYD\d{4}:\d{2}$', value):
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
  """

  def __init__(self, hwid_field_names: Union[str, List[str]],
               probe_statement_field_name: str,
               value_converters: Union[ValueConverter, List[ValueConverter]],
               is_optional: bool = False):
    self.hwid_field_names = type_utils.MakeList(hwid_field_names)
    self.probe_statement_field_name = probe_statement_field_name
    self.value_converters = type_utils.MakeList(value_converters)
    self.is_optional = is_optional

  def GenerateExpectedFields(self, comp_values: dict) -> Optional[str]:
    """Generates the expected field from a given component.

    This function generates the expected field from a given component using
    predefined fields and value converters.

    If there are not any HWID fields found in `comp_values`, this function will
    raise `MissingComponentValueError` if `is_optional` is `False`, otherwise
    return `None`.  If there are zero or multiple HWID fields covertible with
    the converters, this function will raise `ProbeStatementConversionError`,
    otherwise return the converted value.
    """
    expected_field = []
    valid_hwid_field_names = [
        name for name in self.hwid_field_names if name in comp_values
    ]
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
            'Missing component value field(s) for field %r : %r.' %
            (self.probe_statement_field_name, self.hwid_field_names))
      raise ProbeStatementConversionError(
          'Unable to convert the value of field %r : %r.' %
          (self.probe_statement_field_name, err))
    for value in expected_field:
      if value != expected_field[0]:
        raise ProbeStatementConversionError(
            'Found multiple valid component value fields for field %r.' %
            self.probe_statement_field_name)
    return expected_field[0]


class _SameNameFieldRecord(_FieldRecord):
  """FieldRecord with same HWID field name and probe statement field name."""

  def __init__(self, n, c, *args, **kwargs):
    super().__init__(n, n, c, *args, **kwargs)


class _ProbeStatementGenerator:

  def __init__(self, probe_category, probe_function_name, field_converters,
               probe_function_argument=None):
    self.probe_category = probe_category

    self._probe_statement_generator = (
        probe_config_definition.GetProbeStatementDefinition(probe_category))
    self._probe_function_name = probe_function_name
    if field_converters and isinstance(field_converters[0], _FieldRecord):
      self._field_converters = [field_converters]
    else:
      self._field_converters = field_converters
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
                  _SameNameFieldRecord('chemistry', str_converter),
                  _SameNameFieldRecord('manufacturer', str_converter),
                  _SameNameFieldRecord('model_name', str_converter),
              ],
              # Components from sysfs.
              [
                  _SameNameFieldRecord('manufacturer',
                                       StrPrefixValueConverter()),
                  _SameNameFieldRecord('model_name', StrPrefixValueConverter()),
                  _SameNameFieldRecord('technology',
                                       BatteryTechnologySysfsValueConverter()),
              ],
              # Components from EC.
              [
                  _SameNameFieldRecord('manufacturer', str_converter),
                  _SameNameFieldRecord('model_name', str_converter),
                  _FieldRecord('technology', 'chemistry', str_converter),
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
      _FieldRecord('idVendor', 'usb_vendor_id',
                   HexToHexValueConverter(4, has_prefix=False)),
      _FieldRecord('idProduct', 'usb_product_id',
                   HexToHexValueConverter(4, has_prefix=False)),
      _FieldRecord('bcdDevice', 'usb_bcd_device',
                   HexToHexValueConverter(4, has_prefix=False),
                   is_optional=True),
  ]
  all_probe_statement_generators['cellular'] = [
      _ProbeStatementGenerator('cellular', 'cellular_network',
                               network_pci_fields),
      _ProbeStatementGenerator('cellular', 'cellular_network', usb_fields),
  ]
  all_probe_statement_generators['ethernet'] = [
      _ProbeStatementGenerator('ethernet', 'ethernet_network',
                               network_pci_fields),
      _ProbeStatementGenerator('ethernet', 'ethernet_network', usb_fields),
  ]
  all_probe_statement_generators['wireless'] = [
      _ProbeStatementGenerator('wireless', 'wireless_network',
                               [network_pci_fields, network_sdio_fields]),
      _ProbeStatementGenerator('wireless', 'wireless_network', usb_fields),
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

  # This is the old name for video_codec + camera.
  all_probe_statement_generators['video'] = [
      _ProbeStatementGenerator('camera', 'usb_camera', usb_fields),
  ]
  all_probe_statement_generators['camera'] = [
      _ProbeStatementGenerator('camera', 'usb_camera', usb_fields),
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
    hwid_common.COMPONENT_STATUS.supported: hardware_verifier_pb2.QUALIFIED,
    hwid_common.COMPONENT_STATUS.unqualified: hardware_verifier_pb2.UNQUALIFIED,
    hwid_common.COMPONENT_STATUS.deprecated: hardware_verifier_pb2.REJECTED,
    hwid_common.COMPONENT_STATUS.unsupported: hardware_verifier_pb2.REJECTED,
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

  is_duplicate = comp_info.status == hwid_common.COMPONENT_STATUS.duplicate
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


def GetAllComponentVerificationPayloadPieces(db, vpg_config: Optional[
    vpg_config_module.VerificationPayloadGeneratorConfig] = None):
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
    qual_status_preference = {
        hardware_verifier_pb2.QUALIFIED: 0,
        hardware_verifier_pb2.UNQUALIFIED: 1,
        hardware_verifier_pb2.REJECTED: 2,
    }
    return (qual_status_preference.get(
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

  error_msgs = []
  generated_file_contents = {}

  grouped_comp_vp_piece_per_model = {}
  grouped_primary_comp_name_per_model = {}
  hw_verification_spec = hardware_verifier_pb2.HwVerificationSpec()
  for db, vpg_config in dbs:
    model_prefix = db.project.lower()
    probe_config = probe_config_types.ProbeConfigPayload()
    all_pieces = GetAllComponentVerificationPayloadPieces(db, vpg_config)
    grouped_comp_vp_piece = collections.defaultdict(list)
    grouped_primary_comp_name = {}
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
      probe_config.AddComponentProbeStatement(comp_vp_piece.probe_statement)
      hw_verification_spec.component_infos.append(comp_vp_piece.component_info)

    # Append the generic probe statements.
    for ps_gen in _GetAllGenericProbeStatementInfoRecords():
      if ps_gen.probe_category not in vpg_config.waived_comp_categories:
        probe_config.AddComponentProbeStatement(ps_gen.GenerateProbeStatement())

    probe_config_pathname = 'runtime_probe/%s/probe_config.json' % model_prefix
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
  import logging
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
  ap.add_argument('--no_verify_checksum', action='store_false',
                  help="Don't verify the checksum in the HWID databases.",
                  dest='verify_checksum')
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
    db = database.Database.LoadFile(hwid_db_path,
                                    verify_checksum=args.verify_checksum)
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
