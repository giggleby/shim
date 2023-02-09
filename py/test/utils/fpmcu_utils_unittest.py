#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.utils import fpmcu_utils


class FpmcuDeviceTest(unittest.TestCase):

  def setUp(self):
    dut = mock.MagicMock()
    self.device = fpmcu_utils.FpmcuDevice(dut)

  def testGetName(self):
    output = ('Chip info:\n'
              '  vendor:    stm\n'
              '  name:      stm32f412\n'
              '  revision:  \n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetName(), 'stm32f412')

  def testGetNameOnEmptyName(self):
    output = ('Chip info:\n'
              '  vendor:    stm\n'
              '  name:      \n'
              '  revision:  \n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetName)

  def testGetFirmwareVersion(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: RW\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(
        self.device.GetFirmwareVersion(),
        ('bloonchipper_v2.0.5938-197506c1', 'bloonchipper_v2.0.14348-e5fb0b9'))

  def testGetFirmwareVersionOnEmptyFirmwareVersion(self):
    output = (
        'RO version:    \n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    \n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: RW\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetFirmwareVersion)

  def testRequireFpinfoNoErrorFlagsOnNoErrorFlagsSet(self):
    output = (
        'Fingerprint sensor: vendor 20435046 product 9 model 0 version 1\n'
        'Image: size 160x160 8 bpp\n'
        'Error flags: \n'
        'Dead pixels: UNKNOWN\n'
        'Templates: version 4 size 5156 count 0/5 dirty bitmap 0\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertIsNone(self.device.ValidateFpinfoNoErrorFlags())

  def testRequireFpinfoNoErrorFlagsOnErrorFlagsSet(self):
    output = (
        'Fingerprint sensor: vendor 20435046 product 9 model 0 version 1\n'
        'Image: size 160x160 8 bpp\n'
        'Error flags: BAD_HWID INIT_FAIL \n'
        'Dead pixels: UNKNOWN\n'
        'Templates: version 4 size 5156 count 0/5 dirty bitmap 0\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    with self.assertRaises(fpmcu_utils.FpmcuError) as ctx:
      self.device.ValidateFpinfoNoErrorFlags()
    e = ctx.exception
    self.assertEqual(str(e), 'Sensor failure: BAD_HWID INIT_FAIL')

  def testGetFpSensorInfoOnNoErrorFlagsSet(self):
    output = (
        'Fingerprint sensor: vendor 20435046 product 9 model 0 version 1\n'
        'Image: size 160x160 8 bpp\n'
        'Error flags: \n'
        'Dead pixels: UNKNOWN\n'
        'Templates: version 4 size 5156 count 0/5 dirty bitmap 0\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    expected_vendor, expected_sensor = '20435046', '0'
    self.assertEqual(self.device.GetFpSensorInfo(),
                     (expected_vendor, expected_sensor))

  def testGetFpSensorInfoOnErrorFlagsSet(self):
    output = (
        'Fingerprint sensor: vendor 20435046 product 9 model 0 version 1\n'
        'Image: size 160x160 8 bpp\n'
        'Error flags: BAD_HWID INIT_FAIL \n'
        'Dead pixels: UNKNOWN\n'
        'Templates: version 4 size 5156 count 0/5 dirty bitmap 0\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    with self.assertRaises(fpmcu_utils.FpmcuError) as ctx:
      self.device.GetFpSensorInfo()
    e = ctx.exception
    self.assertEqual(str(e), 'Sensor failure: BAD_HWID INIT_FAIL')

  def testGetFpSensorInfoOnInvalidOutput(self):
    output = ('Fingerprint sensor: \n'
              'Image: size 160x160 8 bpp\n'
              'Error flags: BAD_HWID INIT_FAIL \n'
              'Dead pixels: UNKNOWN\n'
              'Templates: version 4 size 5156 count 0/5 dirty bitmap 0\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetFpSensorInfo)

  def testGetFlashProtectFlagsOnLowercasedHexOutput(self):
    output = (
        'Flash protect flags: 0x0000000f wp_gpio_asserted\n'
        'Valid flags:         0x0000083f wp_gpio_asserted ro_at_boot ro_now all_now STUCK INCONSISTENT UNKNOWN_ERROR\n'
        'Writable flags:      0x00000005 ro_at_boot all_now\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetFlashProtectFlags(), 0x0f)

  def testGetFlashProtectFlagsOnUppercasedHexOutput(self):
    output = (
        'Flash protect flags: 0x0000000F wp_gpio_asserted\n'
        'Valid flags:         0x0000083f wp_gpio_asserted ro_at_boot ro_now all_now STUCK INCONSISTENT UNKNOWN_ERROR\n'
        'Writable flags:      0x00000005 ro_at_boot all_now\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetFlashProtectFlags(), 0x0f)

  def testGetFlashProtectFlagsOnEmptyFlags(self):
    output = (
        'Flash protect flags: \n'
        'Valid flags:         0x0000083f wp_gpio_asserted ro_at_boot ro_now all_now STUCK INCONSISTENT UNKNOWN_ERROR\n'
        'Writable flags:      0x00000005 ro_at_boot all_now\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetFlashProtectFlags)

  def testGetFlashProtectFlagsOnInvalidHexFlags(self):
    output = (
        'Flash protect flags: 0x0000000z wp_gpio_asserted\n'
        'Valid flags:         0x0000083f wp_gpio_asserted ro_at_boot ro_now all_now STUCK INCONSISTENT UNKNOWN_ERROR\n'
        'Writable flags:      0x00000005 ro_at_boot all_now\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetFlashProtectFlags)

  def testIsSystemLockedOnLocked(self):
    output = ('Reset flags: 0x0000040a\n'
              'Flags: 0x00000001\n'
              'Firmware copy: 2\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertTrue(self.device.IsSystemLocked())

  def testIsSystemLockedOnNonLocked(self):
    output = ('Reset flags: 0x0000040a\n'
              'Flags: 0x00000000\n'
              'Firmware copy: 2\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertFalse(self.device.IsSystemLocked())

  def testIsSystemLockedOnLowercasedHexOutput(self):
    output = ('Reset flags: 0x0000040a\n'
              'Flags: 0x0000000a\n'
              'Firmware copy: 2\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertFalse(self.device.IsSystemLocked())

  def testIsSystemLockedOnUppercasedHexOutput(self):
    output = ('Reset flags: 0x0000040a\n'
              'Flags: 0x0000000A\n'
              'Firmware copy: 2\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertFalse(self.device.IsSystemLocked())

  def testIsSystemLockedOnEmptyFlags(self):
    output = ('Reset flags: 0x0000040a\n'
              'Flags: \n'
              'Firmware copy: 2\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.IsSystemLocked)

  def testIsSystemLockedOnInvalidHexFlags(self):
    output = ('Reset flags: 0x0000040a\n'
              'Flags: 0x0000000z\n'
              'Firmware copy: 2\n')
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.IsSystemLocked)

  def testGetImageSlotForRW(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: RW\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetImageSlot(), fpmcu_utils.ImageSlot.RW)

  def testGetImageSlotForRO(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: RO\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetImageSlot(), fpmcu_utils.ImageSlot.RO)

  def testGetImageSlotForUnknownImage1(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: unknown\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetImageSlot(), fpmcu_utils.ImageSlot.UNKNOWN)

  def testGetImageSlotForUnknownImage2(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: ?\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertEqual(self.device.GetImageSlot(), fpmcu_utils.ImageSlot.UNKNOWN)

  def testGetImageSlotOnInvalidImageOutput(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: INVALID\n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )

    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetImageSlot)

  def testGetImageSlotOnEmptyImageOutput(self):
    output = (
        'RO version:    bloonchipper_v2.0.5938-197506c1\n'
        'RO cros fwid:  CROS_FWID_MISSING\n'
        'RW version:    bloonchipper_v2.0.14348-e5fb0b9\n'
        'RW cros fwid:  bloonchipper_14931.0.0\n'
        'Firmware copy: \n'
        'Build info:    bloonchipper_v2.0.14348-e5fb0b9 cryptoc:v1.9308_26_0.11-11a97df private:1.1.9999-e5fb0b9 fpc:1.1.9999-e5fb0b9 bloonchipper_14931.0.0 2022-06-17 16:40:54 @chromeos-ci-legacy-us-central2-d-x32-21-ivd3\n'
        'Tool version:  v2.0.20247-b863c6d01b 2023-01-31 01:10:33 @chromeos-release-builder-us-east1-d-x32-8-nunm\n'
    )
    self.device.FpmcuCommand = mock.MagicMock(return_value=output)
    self.assertRaises(fpmcu_utils.FpmcuError, self.device.GetImageSlot)


if __name__ == '__main__':
  unittest.main()
