# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines generic probe statement generators for all categories"""

from cros.factory.probe.runtime_probe import probe_config_definition
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
def GetAllGenericProbeStatementInfoRecords():
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
