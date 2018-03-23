# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""YAML tags used in the HWID database."""

import factory_common  # pylint: disable=W0611
from cros.factory.l10n import regions
from cros.factory.utils import yaml_utils


class RegionFieldMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """Metaclass for registering the !region_field YAML tag."""
  YAML_TAG = '!region_field'

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    return RegionField(node.value)

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_scalar(mcs.YAML_TAG)


class RegionField(dict):
  """A class for holding the region field data in a HWID database."""
  __metaclass__ = RegionFieldMetaclass

  def __init__(self, list_node=None):
    if not isinstance(list_node, list):
      self._is_legacy_style = True
      list_codes = [code for code in regions.LEGACY_REGIONS_LIST
                    if code in regions.REGIONS]

    else:
      self._is_legacy_style = False
      list_codes = [regions.REGIONS[node.value].region_code
                    for node in list_node]

    # The numeric ids of valid regions start from 1.
    # crbug.com/624257: If no explicit regions defined, populate with only the
    # legacy list.
    fields_dict = dict(
        (i + 1, {'region': code}) for i, code in enumerate(list_codes))

    # 0 is a reserved field and is set to {region: []}, so that previous HWIDs
    # which do not have region encoded will not return a bogus region component
    # when being decoded.
    fields_dict[0] = {'region': []}

    super(RegionField, self).__init__(fields_dict)


class RegionComponentMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """Metaclass for registering the !region_component YAML tag."""
  YAML_TAG = '!region_component'

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    return RegionComponent()

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_scalar(mcs.YAML_TAG)


class RegionComponent(dict):
  """A class for holding the region component data in a HWID database."""
  __metaclass__ = RegionComponentMetaclass

  def __init__(self):
    components_dict = {
        'probeable': True,
        'items': {}
    }
    for code, region in regions.REGIONS.iteritems():
      components_dict['items'][code] = {
          'values': {
              'region_code': region.region_code
          }}
    super(RegionComponent, self).__init__(components_dict)
