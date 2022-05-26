# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines available actions for HWIDv2 DBs."""

import re
from typing import List, Optional

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module


class HWIDV2Action(hwid_action.HWIDAction):
  HWID_VERSION = 2

  def __init__(self, hwid_v2_preproc_data: hwid_preproc_data.HWIDV2PreprocData):
    self._preproc_data = hwid_v2_preproc_data

  def GetBOMAndConfigless(
      self, hwid_string: str, verbose: Optional[bool] = False,
      vpg_config: Optional[
          vpg_config_module.VerificationPayloadGeneratorConfig] = None,
      require_vp_info: Optional[bool] = False):
    project, name, variant, volatile = self._SplitHWID(hwid_string)

    if project != self._preproc_data.project:
      raise hwid_action.InvalidHWIDError('project mismatch')

    bom = hwid_action.BOM()
    bom.project = self._preproc_data.project

    if name in self._preproc_data.bom_map:
      bom.AddAllComponents(
          self._preproc_data.bom_map[name]['primary']['components'],
          verbose=verbose)
    else:
      raise hwid_action.HWIDDecodeError('BOM %r not found for project %r.' %
                                        (bom, self._preproc_data.project))

    if variant:
      if variant in self._preproc_data.variant_map:
        bom.AddAllComponents(
            self._preproc_data.variant_map[variant]['components'],
            verbose=verbose)
      else:
        raise hwid_action.HWIDDecodeError(
            'variant %r not found for project %r.' %
            (variant, self._preproc_data.project))

    if volatile:
      if volatile in self._preproc_data.volatile_map:
        bom.AddAllComponents(self._preproc_data.volatile_map[volatile],
                             verbose=verbose)
      else:
        raise hwid_action.HWIDDecodeError(
            'volatile %r not found for project %r.' %
            (volatile, self._preproc_data.project))

    return bom, None

  def _EnumerateHWIDs(self, with_classes, without_classes, with_components,
                      without_components):
    hwids_set = set()
    for hw in self._preproc_data.bom_map:
      miss_list = self._preproc_data.bom_map[hw]['primary']['classes_missing']
      vol_ltrs = set()
      status_fields = ['deprecated', 'eol', 'qualified', 'supported']
      for field in status_fields:
        for hw_vol in self._preproc_data.hwid_status_map[field]:
          if hw in hw_vol:
            if hw_vol[-1] == '*':
              vol_ltrs.update(self._preproc_data.volatile_map)
            else:
              vol_ltrs.add(hw_vol.rpartition('-')[2])
      items = list(
          self._preproc_data.bom_map[hw]['primary']['components'].items())
      for var in self._preproc_data.bom_map[hw]['variants']:
        items += list(self._preproc_data.variant_map[var]['components'].items())
      for vol in vol_ltrs:
        for cls, comp in self._preproc_data.volatile_map[vol].items():
          items.append((cls, comp))
          items.append((comp, self._preproc_data.volatile_value_map[comp]))

      # Populate the class set and component set with data from items
      all_classes = set()
      all_components = set()
      for cls, comp in items:
        all_classes.add(cls)
        if isinstance(comp, list):
          all_components.update(comp)
        else:
          all_components.add(comp)

      valid = True
      if with_classes:
        for cls in with_classes:
          if cls in miss_list or cls not in all_classes:
            valid = False
      if without_classes:
        for cls in without_classes:
          if cls not in miss_list and cls in all_classes:
            valid = False
      if with_components:
        for comp in with_components:
          if comp not in all_components:
            valid = False
      if without_components:
        for comp in without_components:
          if comp in all_components:
            valid = False
      if valid:
        hwids_set.add(hw)
    return hwids_set

  def GetComponentClasses(self):
    classes_set = set()
    for hw in self._preproc_data.bom_map:
      classes_set.update(
          self._preproc_data.bom_map[hw]['primary']['components'].keys())
    for var in self._preproc_data.variant_map:
      classes_set.update(
          self._preproc_data.variant_map[var]['components'].keys())
    for vol in self._preproc_data.volatile_map:
      classes_set.update(self._preproc_data.volatile_map[vol].keys())
    classes_set.update(self._preproc_data.volatile_value_map.keys())
    return classes_set

  def GetComponents(self, with_classes: List[Optional[str]] = None):
    components = {}
    all_comps = []
    for bom in self._preproc_data.bom_map.values():
      if bom['primary']['components']:
        all_comps.extend(bom['primary']['components'].items())
    for var in self._preproc_data.variant_map.values():
      if var['components']:
        all_comps.extend(var['components'].items())
    for vol in self._preproc_data.volatile_map.values():
      if vol:
        for cls, comp in vol.items():
          all_comps.append((cls, comp))
          all_comps.append((comp, self._preproc_data.volatile_value_map[comp]))

    for cls, comp in all_comps:
      if with_classes and cls not in with_classes:
        continue
      if cls not in components:
        components[cls] = set()
      if isinstance(comp, list):
        components[cls].update(comp)
      else:
        components[cls].add(comp)

    return components

  def _SplitHWID(self, hwid_string):
    """Splits a HWIDv2 string into component parts.

    Examples matched (project, bom, variant, volatile):
      FOO BAR -> ('FOO', 'BAR', None, None)
      FOO BAR BAZ-QUX -> ('FOO', 'BAR', 'BAZ', 'QUX')
      FOO BAR BAZ-QUX 1234 -> ('FOO', 'BAR', 'BAZ', 'QUX')
      FOO BAR-BAZ -> ('FOO', 'BAR-BAZ', None, None)
      FOO BAR-BAZ QUX -> ('FOO', 'BAR-BAZ', 'QUX', None)
      FOO BAR-BAZ-QUX -> ('FOO', 'BAR-BAZ-QUX', None, None)

    Args:
      hwid_string: The HWIDv2 string in question

    Returns:
      A tuple of the BOM name, variant and volatile.

    Raises:
      hwid_action.InvalidHWIDError: if the string is in an invalid format.
    """

    match = re.match(
        r'\s*(?P<project>\w+)\s+(?P<name>\w+\S+)'
        r'(\s+(?P<variant>\w+)(-(?P<volatile>\w+))?)?.*', hwid_string)

    if match:
      groups = match.groupdict()
      project = _NormalizeString(groups['project'])
      name = _NormalizeString(groups['name'])
      variant = _NormalizeString(groups['variant'])
      volatile = _NormalizeString(groups['volatile'])

      return (project, name, variant, volatile)

    raise hwid_action.InvalidHWIDError(
        'Invalid HWIDv2 format: %r' % hwid_string)


def _NormalizeString(string):
  """Normalizes a string to account for things like case."""
  return string.strip().upper() if string else None
