# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(yhong): Integrate the module with go/cros-probe.

import re

from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.utils import type_utils


@type_utils.CachedGetter
def _GetAllProbeStatementDefinitions():

  def _GetASCIIStringErrorMsg(length1, length2=None):
    if length2 is None:
      return f'format error, expect a {length1}-byte ASCII string'
    return (f'format error, expect a ASCII string of length {length1} to '
            f'{length2}')

  probe_statement_definitions = {}

  # Create battery builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('battery')
  builder.AddProbeFunction('generic_battery',
                           'Read battery information from sysfs.')
  builder.AddStrOutputField('chemistry', 'Chemistry exposed from the EC.')
  builder.AddStrOutputField('manufacturer',
                            ('Manufacturer name exposed from the ACPI '
                             'interface.'))
  builder.AddStrOutputField('model_name',
                            ('Model name exposed from the EC or the ACPI '
                             'interface.'))
  builder.AddStrOutputField('technology',
                            'Technology exposed from the ACPI interface.')
  probe_statement_definitions['battery'] = builder.Build()

  # Create storage builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('storage')
  builder.AddProbeFunction('generic_storage',
                           ('A method that tries various of way to detect the '
                            'storage component.'))
  builder.AddStrOutputField('type', 'HW interface type of the storage.')
  builder.AddIntOutputField('sectors', 'Sector size.')

  builder.AddProbeFunction('mmc_storage', 'Probe function for eMMC storage.')
  probe_function_names = ['generic_storage', 'mmc_storage']
  builder.AddHexOutputField('mmc_hwrev', 'Hardware revision in CID register.',
                            probe_function_names=probe_function_names,
                            num_value_digits=1)
  builder.AddHexOutputField(
      'mmc_manfid', 'Manufacturer ID (MID) in CID register.',
      probe_function_names=probe_function_names, num_value_digits=2)
  builder.AddHexOutputField(
      'mmc_oemid', 'OEM/Application ID (OID) in CID register.',
      probe_function_names=probe_function_names, num_value_digits=4)
  builder.AddStrOutputField(
      'mmc_name', 'Product name (PNM) in CID register.',
      probe_function_names=probe_function_names,
      value_pattern=re.compile(r'[\x01-\x7f]{4,6}'),
      value_format_error_msg=_GetASCIIStringErrorMsg(4, 6))
  builder.AddHexOutputField(
      'mmc_prv', 'Product revision (PRV) in CID register.',
      probe_function_names=probe_function_names, num_value_digits=2)
  builder.AddHexOutputField('mmc_serial', 'Product Serial Number (PSN)',
                            probe_function_names=probe_function_names,
                            num_value_digits=8)

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
  builder.AddStrOutputField('nvme_model', 'NVMe model name.',
                            probe_function_names=probe_function_names)

  builder.AddProbeFunction('ata_storage', 'Probe function for ATA storage.')
  probe_function_names = ['generic_storage', 'ata_storage']
  builder.AddStrOutputField('ata_vendor', 'Vendor name.',
                            probe_function_names=probe_function_names,
                            value_pattern=re.compile('ATA'),
                            value_format_error_msg=_GetASCIIStringErrorMsg(8))
  builder.AddStrOutputField('ata_model', 'Model name.',
                            probe_function_names=probe_function_names,
                            value_format_error_msg=_GetASCIIStringErrorMsg(32))

  builder.AddProbeFunction('ufs_storage', 'Probe function for UFS storage.')
  probe_function_names = ['generic_storage', 'ufs_storage']
  builder.AddStrOutputField('ufs_vendor', 'Vendor name.',
                            probe_function_names=probe_function_names)
  builder.AddStrOutputField('ufs_model', 'Model name.',
                            probe_function_names=probe_function_names)
  probe_statement_definitions['storage'] = builder.Build()

  # Create mmc_host builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('mmc_host')
  builder.AddProbeFunction('mmc_host',
                           'The probe function for MMC host components.')
  builder.AddHexOutputField('pci_vendor_id', 'PCIe vendor ID',
                            num_value_digits=4)
  builder.AddHexOutputField('pci_device_id', 'PCIe device ID',
                            num_value_digits=4)
  builder.AddHexOutputField('pci_class', 'PCIe class code', num_value_digits=6)
  probe_statement_definitions['mmc_host'] = builder.Build()

  # Create network builder
  for network_type in ['cellular', 'ethernet', 'wireless']:
    builder = probe_config_types.ProbeStatementDefinitionBuilder(network_type)
    builder.AddProbeFunction(
        f'{network_type}_network',
        (f'A method that tries various of way to detect the {network_type} '
         'component.'))
    builder.AddStrOutputField(
        'bus_type', 'HW interface type of the component.',
        value_pattern=re.compile('(pci|usb|sdio)'),
        value_format_error_msg='Must be either "pci", "usb", or "sdio"')
    builder.AddHexOutputField('pci_vendor_id', 'PCI Vendor ID.',
                              num_value_digits=4)
    builder.AddHexOutputField('pci_device_id', 'PCI Device ID.',
                              num_value_digits=4)
    builder.AddHexOutputField('pci_revision', 'PCI Revision Info.',
                              num_value_digits=2)
    builder.AddHexOutputField('pci_subsystem', 'PCI subsystem ID.',
                              num_value_digits=4)
    builder.AddHexOutputField('usb_vendor_id', 'USB Vendor ID.',
                              num_value_digits=4)
    builder.AddHexOutputField('usb_product_id', 'USB Product ID.',
                              num_value_digits=4)
    builder.AddHexOutputField('usb_bcd_device', 'USB BCD Device Info.',
                              num_value_digits=4)
    builder.AddHexOutputField('sdio_vendor_id', 'SDIO Vendor ID.',
                              num_value_digits=4)
    builder.AddHexOutputField('sdio_device_id', 'SDIO Device ID.',
                              num_value_digits=4)
    probe_statement_definitions[network_type] = builder.Build()

  # Create dram builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('dram')
  builder.AddProbeFunction('memory', 'Probe memory from DMI.')
  builder.AddStrOutputField('part', 'Part number.')
  builder.AddIntOutputField('size', 'Memory size in MiB.')
  builder.AddIntOutputField('slot', 'Memory slot index.')
  probe_statement_definitions['dram'] = builder.Build()

  # Create input_device builder
  for category in ['stylus', 'touchpad', 'touchscreen']:
    builder = probe_config_types.ProbeStatementDefinitionBuilder(category)
    builder.AddProbeFunction('input_device', 'Probe input devices from procfs.')
    builder.AddStrOutputField('name', 'Model name.')
    builder.AddHexOutputField('product', 'Product ID.')
    builder.AddHexOutputField('vendor', 'Vendor ID.', num_value_digits=4)
    builder.AddStrOutputField('fw_version', 'Firmware version.')
    builder.AddStrOutputField('device_type', 'Device type.')
    probe_statement_definitions[category] = builder.Build()

  builder = probe_config_types.ProbeStatementDefinitionBuilder('camera')
  builder.AddProbeFunction('usb_camera',
                           ('A method that probes camera devices on USB bus.'))
  builder.AddStrOutputField(
      'bus_type', 'HW interface type of the component.',
      value_pattern=re.compile('(usb|mipi)'),
      value_format_error_msg=('Must be either "usb" or "mipi".'))
  builder.AddHexOutputField('usb_vendor_id', 'USB Vendor ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('usb_product_id', 'USB Product ID.',
                            num_value_digits=4)
  builder.AddHexOutputField('usb_bcd_device', 'USB BCD Device Info.',
                            num_value_digits=4)
  builder.AddStrOutputField('usb_removable', 'Whether the device is removable.')

  builder.AddProbeFunction('mipi_camera',
                           ('A method that probes camera devices on MIPI bus.'))
  builder.AddStrOutputField('mipi_name', 'Entity name from V4L2.')
  builder.AddStrOutputField(
      'mipi_module_id',
      'Camera module vendor ID and product ID read from camera EEPROM.')
  builder.AddStrOutputField(
      'mipi_sensor_id',
      'Image sensor vendor ID and product ID read from camera EEPROM.')
  builder.AddHexOutputField('mipi_vendor',
                            'Image sensor vendor ID queried via V4L2.',
                            num_value_digits=4)
  probe_statement_definitions['camera'] = builder.Build()

  builder = probe_config_types.ProbeStatementDefinitionBuilder('display_panel')
  builder.AddProbeFunction('edid', 'A method that probes devices via edid.')
  builder.AddIntOutputField('height', 'The height of the device.')
  builder.AddHexOutputField('product_id', 'The product ID, 16 bits',
                            num_value_digits=4)
  builder.AddStrOutputField(
      'vendor', 'The vendor code, 3 letters',
      value_pattern=re.compile('[A-Z]{3}'),
      value_format_error_msg='Must be a 3-letter all caps string.')
  builder.AddIntOutputField('width', 'The width of the device.')
  probe_statement_definitions['display_panel'] = builder.Build()

  # Create tcpc builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('tcpc')
  builder.AddProbeFunction('tcpc', 'Probe tcpc info from ec.')
  builder.AddHexOutputField('device_id', 'The device id of tcpc.')
  builder.AddHexOutputField('product_id', 'The product id of tcpc.')
  builder.AddHexOutputField('vendor_id', 'The vendor id of tcpc.')
  probe_statement_definitions['tcpc'] = builder.Build()

  # Create GPU builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('gpu')
  builder.AddProbeFunction('gpu', 'Probe GPU info.')
  builder.AddHexOutputField('vendor', 'The device id.')
  builder.AddHexOutputField('device', 'The device id.')
  builder.AddHexOutputField('subsystem_vendor', 'The subsystem vendor id.')
  builder.AddHexOutputField('subsystem_device', 'The subsystem device id.')
  probe_statement_definitions['gpu'] = builder.Build()

  # Create audio codec builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder('audio_codec')
  builder.AddProbeFunction('audio_codec', 'Probe audio codec info.')
  builder.AddStrOutputField('name',
                            'The probed kernel name of audio codec comp.')
  probe_statement_definitions['audio_codec'] = builder.Build()

  # Create PCIe-eMMC storage bridge builder
  builder = probe_config_types.ProbeStatementDefinitionBuilder(
      'emmc_pcie_storage_bridge')
  builder.AddProbeFunction('mmc_host',
                           'The probe function for MMC host components.')
  builder.AddHexOutputField('pci_vendor_id', 'PCIe vendor ID',
                            num_value_digits=4)
  builder.AddHexOutputField('pci_device_id', 'PCIe device ID',
                            num_value_digits=4)
  builder.AddHexOutputField('pci_class', 'PCIe class code', num_value_digits=6)
  probe_statement_definitions['emmc_pcie_storage_bridge'] = builder.Build()

  return probe_statement_definitions


def GetProbeStatementDefinition(name):
  """Get the probe statement definition of the given name.

  Please refer to `_ConstructAllProbeStatementDefinitions()` for the available
  name list.`

  Args:
    name: Name of the probe statement definition.

  Returns:
    An instance of `probe_config_types.ProbeStatementDefinition`.
  """
  return _GetAllProbeStatementDefinitions()[name]
