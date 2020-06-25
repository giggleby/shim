# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(yhong): Integrate the module with go/cros-probe.

import re

from cros.factory.probe.runtime_probe import probe_config_types


_probe_statement_definitions = {}


def _ConstructAllProbeStatementDefinitions():
  def _GetASCIIStringErrorMsg(length):
    return 'format error, expect a %d-byte ASCII string' % length

  builder = probe_config_types.ProbeStatementDefinitionBuilder('battery')
  builder.AddProbeFunction('generic_battery',
                           'Read battery information from sysfs.')
  builder.AddStrOutputField('manufacturer',
                            ('Manufacturing name exposed from the ACPI '
                             'interface.'))
  builder.AddStrOutputField('model_name',
                            'Model name exposed from the ACPI interface.')
  builder.AddStrOutputField('technology',
                            'Technology exposed from the ACPI interface.')
  _probe_statement_definitions['battery'] = builder.Build()

  builder = probe_config_types.ProbeStatementDefinitionBuilder('storage')
  builder.AddProbeFunction('generic_storage',
                           ('A method that tries various of way to detect the '
                            'storage component.'))
  builder.AddStrOutputField('type', 'HW interface type of the storage.')
  builder.AddIntOutputField('sectors', 'Sector size.')

  builder.AddProbeFunction('mmc_storage', 'Probe function for eMMC storage.')
  probe_function_names = ['generic_storage', 'mmc_storage']
  builder.AddHexOutputField('manfid',
                            'Manufacturer ID (MID) in CID register.',
                            probe_function_names=probe_function_names,
                            num_value_digits=2)
  builder.AddHexOutputField('oemid',
                            'OEM/Application ID (OID) in CID register.',
                            probe_function_names=probe_function_names,
                            num_value_digits=4)
  builder.AddStrOutputField('name',
                            'Product name (PNM) in CID register.',
                            probe_function_names=probe_function_names,
                            value_pattern=re.compile('[ -~]{6}'),
                            value_format_error_msg=_GetASCIIStringErrorMsg(6))
  builder.AddHexOutputField('prv',
                            'Product revision (PRV) in CID register.',
                            probe_function_names=probe_function_names,
                            num_value_digits=2)

  builder.AddProbeFunction('nvme_storage', 'Probe function for NVMe storage.')
  probe_function_names = ['generic_storage', 'nvme_storage']
  builder.AddHexOutputField('pci_vendor', 'PCI Vendor ID.',
                            probe_function_names=probe_function_names,
                            num_value_digits=4)
  builder.AddHexOutputField('pci_device', 'PCI Device ID.',
                            probe_function_names=probe_function_names,
                            num_value_digits=4)
  builder.AddHexOutputField('pci_class', 'PCI Device Class Indicator.',
                            probe_function_names=probe_function_names,
                            num_value_digits=6)

  builder.AddProbeFunction('ata_storage', 'Probe function for ATA storage.')
  probe_function_names = ['generic_storage', 'ata_storage']
  builder.AddStrOutputField('ata_vendor', 'Vendor name.',
                            probe_function_names=probe_function_names,
                            value_pattern=re.compile('^ATA$'),
                            value_format_error_msg=_GetASCIIStringErrorMsg(8))
  builder.AddStrOutputField('ata_model', 'Model name.',
                            probe_function_names=probe_function_names,
                            value_format_error_msg=_GetASCIIStringErrorMsg(32))
  _probe_statement_definitions['storage'] = builder.Build()

  builder = probe_config_types.ProbeStatementDefinitionBuilder('network')
  builder.AddProbeFunction('generic_network',
                           ('A method that tries various of way to detect the '
                            'network-releated component.'))
  builder.AddProbeFunction('wireless_network',
                           ('A method that tries various of way to detect the '
                            'wireless component.'))
  builder.AddProbeFunction('cellular_network',
                           ('A method that tries various of way to detect the '
                            'cellular component.'))
  builder.AddProbeFunction('ethernet_network',
                           ('A method that tries various of way to detect the '
                            'ethernet component.'))
  builder.AddStrOutputField(
      'type',
      'Component type, one of "wireless", "ethernet" or "cellular".',
      value_pattern=re.compile('(wireless|ethernet|cellular)'),
      value_format_error_msg=('Must be either "wireless", "ethernet", or '
                              '"cellular".'))
  builder.AddStrOutputField('bus_type', 'HW interface type of the component.',
                            value_pattern=re.compile('(pci|usb|sdio)'),
                            value_format_error_msg=('Must be either "pci", '
                                                    '"usb", or "sdio"'))
  builder.AddHexOutputField('pci_vendor_id', 'PCI Vendor ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('pci_device_id', 'PCI Device ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('pci_revision', 'PCI Revision Info.',
                            num_value_digits=2)
  builder.AddHexOutputField('usb_vendor_id', 'USB Vendor ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('usb_product_id', 'USB Product ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('usb_bcd_device', 'USB BCD Device Info.',
                            num_value_digits=4)
  builder.AddHexOutputField('sdio_vendor_id', 'SDIO Vendor ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('sdio_product_id', 'SDIO Device ID.',
                            num_value_digits=4)
  _probe_statement_definitions['network'] = builder.Build()

  # Create dram builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('dram')
  builder.AddProbeFunction('memory',
                           'Probe memory from DMI.')
  builder.AddStrOutputField('part', 'Part number.')
  builder.AddIntOutputField('size', 'Memory size in MiB.')
  builder.AddIntOutputField('slot', 'Memory slot index.')
  _probe_statement_definitions['dram'] = builder.Build()

def GetProbeStatementDefinition(name):
  """Get the probe statement definition of the given name.

  Please refer to `_ConstructAllProbeStatementDefinitions()` for the available
  name list.`

  Args:
    name: Name of the probe statement definition.

  Returns:
    An instance of `probe_config_types.ProbeStatementDefinition`.
  """
  if not _probe_statement_definitions:
    _ConstructAllProbeStatementDefinitions()
  return _probe_statement_definitions[name]
