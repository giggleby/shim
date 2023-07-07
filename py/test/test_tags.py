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
cl=head#name-policy-enforcements-and-runtime-probe-in-factories.
  """

  AUDIOCODEC = enum.auto()
  BATTERY = enum.auto()
  BRIDGE_PCIE_EMMC = enum.auto()
  CAMERA = enum.auto()
  CPU = enum.auto()
  DRAM = enum.auto()
  EC = enum.auto()
  EMR_IC = enum.auto()
  ETHERNET = enum.auto()
  GPU = enum.auto()
  LCD = enum.auto()
  MIPI_CAMERA = enum.auto()
  SMART_SPEAKER_AMPLIFIER = enum.auto()
  SPEAKERAMPLIFIER = enum.auto()
  SPIFLASH = enum.auto()
  STORAGE = enum.auto()
  TOUCHCONTROLLER = enum.auto()
  TRACKPAD = enum.auto()
  USI_CONTROLLER = enum.auto()
  WIFI = enum.auto()

  @property
  def _properties(self):
    return {
        TestCategory.AUDIOCODEC:
            CategoryProperties('Audio Jack Codec', 'audio_codec'),
        TestCategory.BATTERY:
            CategoryProperties('Battery', 'battery'),
        TestCategory.CAMERA:
            CategoryProperties('Camera - USB', 'camera'),
        TestCategory.CPU:
            CategoryProperties('CPU', 'cpu'),
        TestCategory.DRAM:
            CategoryProperties('Memory', 'dram'),
        TestCategory.ETHERNET:
            CategoryProperties('Ethernet controller', 'ethernet'),
        TestCategory.LCD:
            CategoryProperties('Display Panel', 'display_panel'),
        TestCategory.MIPI_CAMERA:
            CategoryProperties('Camera - MIPI', 'camera'),
        TestCategory.WIFI:
            CategoryProperties('Wifi / Bluetooth', 'wireless'),
    }.get(self, CategoryProperties(None, None))

  @property
  def avl_name(self) -> Optional[str]:
    return self._properties.avl_name

  @property
  def hwid_name(self) -> Optional[str]:
    return self._properties.hwid_name
