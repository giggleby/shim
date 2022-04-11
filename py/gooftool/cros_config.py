# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.gooftool import common as gooftool_common

# Path to the product name and sku id of the device.
# ARM devices: DEVICE_TREE_COMPATIBLE_PATH and DEVICE_TREE_SKU_ID_PATH
# x86 devices: PRODUCT_NAME_PATH and PRODUCT_SKU_ID_PATH
DEVICE_TREE_COMPATIBLE_PATH = '/proc/device-tree/compatible'
PRODUCT_NAME_PATH = '/sys/class/dmi/id/product_name'
DEVICE_TREE_SKU_ID_PATH = '/proc/device-tree/firmware/coreboot/sku-id'
PRODUCT_SKU_ID_PATH = '/sys/class/dmi/id/product_sku'


class CrosConfig:
  """Helper class to get data from cros_config."""

  def __init__(self, shell=None, dut=None):
    self._shell = shell or gooftool_common.Shell
    self._dut = dut

  def GetValue(self, path, key):
    return self._shell(['cros_config', path, key], sys_interface=self._dut)

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

  def GetPlatformName(self):
    result = self.GetValue('/identity', 'platform-name')
    return result.stdout.strip() if result.stdout else ''

  def GetModelName(self):
    result = self.GetValue('/', 'name')
    return result.stdout.strip() if result.stdout else ''

  def GetFingerPrintBoard(self):
    result = self.GetValue('/fingerprint', 'board')
    return result.stdout.strip() if result.stdout else ''

  def GetProductName(self):
    result_x86 = self.GetValue('/identity', 'smbios-name-match')
    result_arm = self.GetValue('/identity', 'device-tree-compatible-match')
    result = result_x86 or result_arm
    return result.stdout.strip() if result.stdout else ''

  def GetCustomizationId(self):
    result = self.GetValue('/identity', 'customization-id')
    return result.stdout.strip() if result.stdout else ''

  def GetSkuID(self):
    result = self.GetValue('/identity', 'sku-id')
    return result.stdout.strip() if result.stdout else ''

  def GetBrandCode(self):
    result = self.GetValue('/', 'brand-code')
    return result.stdout.strip() if result.stdout else ''

  def GetSmartAmp(self):
    """Returns the name of the smart-amp.

    If the DUT has no smart-amp, returns an empty string.
    """
    result = self.GetValue('/audio/main', 'speaker-amp')
    return result.stdout.strip() if result.stdout else ''

  def GetSoundCardInit(self):
    result = self.GetValue('/audio/main', 'sound-card-init-conf')
    return result.stdout.strip() if result.stdout else ''
