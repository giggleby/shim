# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import enum
from typing import Optional


CategoryProperties = collections.namedtuple('CategoryProperties',
                                            ('avl_name', 'hwid_name'))


@enum.unique
class TestCategory(enum.Enum):
  """Tags for test categories.

  The reference for the name of a component in AVL is defined in
  go/cros-avl-component-types.

  The reference for the name of a component in HWID DB is defined in
  go/cros-runtime-probe-and-hardware-verifier?\
cl=head#name-policy-enforcements-and-runtime-probe-in-factories and
  go/AVL-HWID-component-mapping.
  """

  ACCELEROMETER = enum.auto()
  AMBIENTLIGHTSENSOR = enum.auto()
  AUDIOCODEC = enum.auto()
  BATTERY = enum.auto()
  BRIDGE_PCIE_EMMC = enum.auto()
  CAMERA = enum.auto()
  CPU = enum.auto()
  DRAM = enum.auto()
  EC = enum.auto()
  EMR_IC = enum.auto()
  ETHERNET = enum.auto()
  FINGERPRINT_SENSOR = enum.auto()
  GPU = enum.auto()
  HPS = enum.auto()
  LCD = enum.auto()
  MIPI_CAMERA = enum.auto()
  SAR_SENSOR = enum.auto()
  SMART_SPEAKER_AMPLIFIER = enum.auto()
  SPEAKERAMPLIFIER = enum.auto()
  SPIFLASH = enum.auto()
  STORAGE = enum.auto()
  TOUCHCONTROLLER = enum.auto()
  TPM = enum.auto()
  TRACKPAD = enum.auto()
  USI_CONTROLLER = enum.auto()
  WIFI = enum.auto()
  WWAN = enum.auto()

  @property
  def _properties(self):
    return {
        TestCategory.ACCELEROMETER:
            CategoryProperties('Accelerometer/IMU', None),
        TestCategory.AMBIENTLIGHTSENSOR:
            CategoryProperties('Ambient Light Sensor', None),
        TestCategory.AUDIOCODEC:
            CategoryProperties('Audio Jack Codec', 'audio_codec'),
        TestCategory.BATTERY:
            CategoryProperties('Battery', 'battery'),
        TestCategory.BRIDGE_PCIE_EMMC:
            CategoryProperties('Storage bridge (PCIE-eMMC)', 'storage_bridge'),
        TestCategory.CAMERA:
            CategoryProperties('Camera - USB', 'camera'),
        TestCategory.CPU:
            CategoryProperties('CPU', 'cpu'),
        TestCategory.DRAM:
            CategoryProperties('Memory', 'dram'),
        TestCategory.EC:
            CategoryProperties('EC', 'ec_flash_chip'),
        TestCategory.EMR_IC:
            CategoryProperties('Touch screen controller (EMR Stylus)',
                               'touchscreen'),
        TestCategory.ETHERNET:
            CategoryProperties('Ethernet controller', 'ethernet'),
        TestCategory.FINGERPRINT_SENSOR:
            CategoryProperties('Fingerprint Sensor', 'fingerprint'),
        TestCategory.HPS:
            CategoryProperties('HPS (Human Presence Sensor)', 'hps'),
        TestCategory.LCD:
            CategoryProperties('Display Panel', 'display_panel'),
        TestCategory.MIPI_CAMERA:
            CategoryProperties('Camera - MIPI', 'camera'),
        TestCategory.SAR_SENSOR:
            CategoryProperties('Proximity(SAR) Sensor', None),
        TestCategory.SMART_SPEAKER_AMPLIFIER:
            CategoryProperties('Smart Speaker Amplifier', 'audio_codec'),
        TestCategory.SPEAKERAMPLIFIER:
            CategoryProperties('Speaker Amplifier', 'audio_codec'),
        TestCategory.SPIFLASH:
            CategoryProperties('SPI Flash', 'flash_chip'),
        TestCategory.STORAGE:
            CategoryProperties('Storage', 'storage'),
        TestCategory.TOUCHCONTROLLER:
            CategoryProperties('Touch screen Controller (non stylus)',
                               'touchscreen'),
        TestCategory.TPM:
            CategoryProperties('TPM', 'tpm'),
        TestCategory.TRACKPAD:
            CategoryProperties('Touchpad Controller', 'touchpad'),
        TestCategory.USI_CONTROLLER:
            CategoryProperties('Touch screen controller (USI Stylus)',
                               'touchscreen'),
        TestCategory.WIFI:
            CategoryProperties('Wifi / Bluetooth', 'wireless'),
        TestCategory.WWAN:
            CategoryProperties('WWAN', 'cellular'),
    }.get(self, CategoryProperties(None, None))

  @property
  def avl_name(self) -> Optional[str]:
    return self._properties.avl_name

  @property
  def hwid_name(self) -> Optional[str]:
    return self._properties.hwid_name
