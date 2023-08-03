# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import enum
import re
from typing import Dict, Optional


class IntelFWParserError(Exception):
  pass


SoCInfo = collections.namedtuple('SoCInfo', ['component', 'info'])


class IntelFWParser:
  """Parses the log lines from /var/log/messages to get the FW info."""

  class Components(str, enum.Enum):
    Bluetooth = 'Bluetooth'
    GPU = 'GPU'
    Sof = 'Sof'
    Wifi = 'Wifi'

  def Parse(self, log_line: str) -> Optional[SoCInfo]:
    COMPONENTS_TO_PARSERS = {
        self.Components.Bluetooth: self.ParseBluetooth,
        self.Components.GPU: self.ParseGPU,
        self.Components.Sof: self.ParseSof,
        self.Components.Wifi: self.ParseWifi,
    }
    for component, parser in COMPONENTS_TO_PARSERS.items():
      parsed_info = parser(log_line)
      if parsed_info:
        return SoCInfo(component=component.value, info=parsed_info)
    return None

  def ParseBluetooth(self, log_line: str) -> Optional[Dict]:
    BLUETOOTH_REGEX = r'Bluetooth[^\n]+device firmware: (?P<bin>\S+)'
    match = re.search(BLUETOOTH_REGEX, log_line)
    if match:
      return {
          'binary': match.group('bin')
      }
    return None

  def ParseGPU(self, log_line: str) -> Optional[Dict]:

    def ParseSubComponents(log_line: str) -> Dict:
      GUC_HUC_REGEX = (
          r'(?P<name>\S+) firmware i915\/(?P<bin>\S+) version (?P<ver>\S+)')
      DMC_REGEX = (
          r'[^\n]+ (?P<name>\S+) firmware i915\/(?P<bin>\S+) \(v(?P<ver>\S+)\)')

      for patterns in (GUC_HUC_REGEX, DMC_REGEX):
        match = re.search(patterns, log_line)
        if match:
          return {
              'name': match.group('name'),
              'binary': match.group('bin'),
              'version': match.group('ver'),
          }
      raise IntelFWParserError(f'Failed to parse GPU components: {log_line}')

    GPU_REGEX = r'i915\s*\S+\s*\[drm\]\s*(?P<firmware_info>[^\n]+)'

    match = re.search(GPU_REGEX, log_line)
    if match:
      firmware_info = match.group('firmware_info')
      return ParseSubComponents(firmware_info)
    return None

  def ParseSof(self, log_line: str) -> Optional[Dict]:
    """This info is only available on MIPI cameras."""
    SOF_REGEX = r'sof-audio-pci-intel-tgl[^\n]+version (?P<ver>\S+)'
    match = re.search(SOF_REGEX, log_line)
    if match:
      return {
          'version': match.group('ver')
      }
    return None

  def ParseWifi(self, log_line: str) -> Optional[Dict]:
    WIFI_REGEX = r'iwlwifi[^\n]+firmware version (?P<bin>\S+)'
    match = re.search(WIFI_REGEX, log_line)
    if match:
      return {
          'binary': match.group('bin')
      }
    return None
