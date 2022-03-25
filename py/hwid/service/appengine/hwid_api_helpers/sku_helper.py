# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import logging
from typing import List, NamedTuple, Optional, Tuple

from cros.factory.hwid.v3 import bom as v3_bom


class SKU(NamedTuple):
  """A holder of SKU related information."""
  sku_str: str
  project: str
  cpu: Optional[str]
  memory_str: str
  total_bytes: int
  warnings: List[str]


class SKUHelper:

  def __init__(self, decoder_data_manager):
    self._decoder_data_manager = decoder_data_manager

  def GetTotalRAMFromHWIDData(self, drams) -> Tuple[str, int, List[str]]:
    """Convert a list of DRAM string into a total number of bytes integer."""
    # v3_bom.RamSize is compatible with HWIDv2
    total_ram = v3_bom.RamSize(byte_count=0)
    warnings = []
    for dram in drams:
      if not dram.fields or 'size' not in dram.fields:
        warnings.append(f'{dram.name!r} does not contain size field')
        continue
      # The unit of the size field is MB.
      total_ram += v3_bom.RamSize(
          byte_count=int(dram.fields['size']) * 1024 * 1024)
    return str(total_ram), total_ram.byte_count, warnings

  def GetSKUFromBOM(self, bom, configless=None) -> SKU:
    """From a BOM construct a string that represents the hardware."""
    components = collections.defaultdict(list)
    for component in bom.GetComponents():
      components[component.cls].append(component)
      logging.debug(component)

    cpu = None
    cpus = self.GetComponentValueFromBOM(bom, 'cpu')
    if cpus:
      cpus.sort()
      cpu = '_'.join(
          self._decoder_data_manager.GetAVLName('cpu', comp_name)
          for comp_name in cpus)

    if configless and 'memory' in configless:
      memory_str = str(configless['memory']) + 'GB'
      total_bytes = configless['memory'] * 1024 * 1024 * 1024
      warnings: List[str] = []
    else:
      memory_str, total_bytes, warnings = self.GetTotalRAMFromHWIDData(
          components['dram'])

    project = bom.project.lower()
    sku_str = '%s_%s_%s' % (project, cpu, memory_str)

    return SKU(sku_str=sku_str, project=project, cpu=cpu, memory_str=memory_str,
               total_bytes=total_bytes, warnings=warnings)

  def GetComponentValueFromBOM(self, bom, component_cls):
    components = collections.defaultdict(list)
    for component in bom.GetComponents():
      components[component.cls].append(component.name)

    if components[component_cls]:
      return components[component_cls]

    return None
