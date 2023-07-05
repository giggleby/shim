# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.external.chromeos_cli import shell


# Path to the product name and sku id of the device.
# ARM devices: DEVICE_TREE_COMPATIBLE_PATH and DEVICE_TREE_SKU_ID_PATH
# x86 devices: PRODUCT_NAME_PATH and PRODUCT_SKU_ID_PATH
DEVICE_TREE_COMPATIBLE_PATH = '/proc/device-tree/compatible'
PRODUCT_NAME_PATH = '/sys/class/dmi/id/product_name'
DEVICE_TREE_SKU_ID_PATH = '/proc/device-tree/firmware/coreboot/sku-id'
PRODUCT_SKU_ID_PATH = '/sys/class/dmi/id/product_sku'
SYSFS_CHROMEOS_ACPI_FRID_PATH = '/sys/devices/platform/chromeos_acpi/FRID'
PROC_FDT_CHROMEOS_FRID_PATH = \
    '/proc/device-tree/firmware/chromeos/readonly-firmware-version'


class CrosConfig:
  """Helper class to get data from cros_config."""

  def __init__(self, dut=None):
    self._shell = shell.Shell(dut)

  def GetValue(self, path, key):
    return self._shell(['cros_config', path, key])

  def GetCustomLabelTag(self):
    """Get custom-label-tag value of this device.

    Returns:
      A tuple of (|is_custom_label|, |custom_label_tag|).
      |is_custom_label| indicates if this device is custom label or not.
      |custom_label_tag| is the value of custom-label-tag if |is_custom_label|
      is True.
    """
    result = self.GetValue('/identity', 'custom-label-tag')
    if not result.success:
      whitelabel_result = self.GetValue('/identity', 'whitelabel-tag')
      if whitelabel_result.success:
        # It means that an old test image that only supports whitelabel-tag is
        # used.  The partner needs to either upgrade the test image
        # (>= 14675.0.0), or downgrade the factory toolkit (< 14680.0.0).
        raise RuntimeError(
            'custom-label-tag is not supported by this image, please upgrade '
            'the test image to version higher than "14675.0.0".')
    return result.success, (result.stdout.strip() if result.stdout else '')

  # Introducing frid as ToT cros_config only supports this field
  # while removing smbios-name-match / device-tree-compatible-match.
  # The change was landed in 15227.0.0, refer to b/245588383 for details.
  def GetFrid(self):
    result = self.GetValue('/identity', 'frid')
    return result.stdout.strip() if result.stdout else ''

  def GetModelName(self):
    result = self.GetValue('/', 'name')
    return result.stdout.strip() if result.stdout else ''

  def GetFingerPrintBoard(self):
    result = self.GetValue('/fingerprint', 'board')
    return result.stdout.strip() if result.stdout else ''

  def GetProductName(self):
    result_x86 = self.GetValue('/identity', 'smbios-name-match')
    if result_x86:
      return result_x86.stdout.strip(), 'smbios-name-match'

    result_arm = self.GetValue('/identity', 'device-tree-compatible-match')
    if result_arm:
      return result_arm.stdout.strip(), 'device-tree-compatible-match'

    return '', ''

  def GetCustomizationId(self):
    result = self.GetValue('/identity', 'customization-id')
    return result.stdout.strip() if result.stdout else ''

  def GetSkuID(self):
    result = self.GetValue('/identity', 'sku-id')
    return result.stdout.strip() if result.stdout else ''

  def GetBrandCode(self):
    result = self.GetValue('/', 'brand-code')
    return result.stdout.strip() if result.stdout else ''

  def GetFormFactor(self):
    result = self.GetValue('/hardware-properties', 'form-factor')
    return result.stdout.strip() if result.stdout else ''

  def GetAmplifier(self):
    """Returns the name of the amplifier on DUT."""
    result = self.GetValue('/audio/main', 'speaker-amp')
    return result.stdout.strip() if result.stdout else ''

  def GetSoundCardInit(self):
    """Returns the name of the sound-card-init-conf file.

    Only smart amplifiers have sound-card-init-conf file.
    """
    result = self.GetValue('/audio/main', 'sound-card-init-conf')
    return result.stdout.strip() if result.stdout else ''

  def GetShimlessEnabledStatus(self):
    """Checks if Shimless RMA has been enabled on this device."""
    result = self.GetValue('/rmad', 'enabled')

    return result.stdout and result.stdout.strip() == 'true'
