# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""YAML tags used in the HWID database."""

import factory_common # pylint: disable=W0611
from cros.factory.l10n import regions
from cros.factory.utils import yaml_utils


class RegionFieldMetaclass(yaml_utils.BaseYAMLTagMetaclass):
  """Metaclass for registering the !region_field YAML tag."""
  YAML_TAG = '!region_field'

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    return RegionField()

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    return dumper.represent_scalar(mcs.YAML_TAG)


class RegionField(dict):
  """A class for holding the region field data in a HWID database."""
  __metaclass__ = RegionFieldMetaclass

  def __init__(self):
    # The numeric ids of valid regions start from 1.
    fields_dict = dict(
        (r.numeric_id, {'region': r.region_code})
        for r in regions.REGIONS.itervalues())
    # 0 is a reserved field and is set to {region: None}, so that previous HWIDs
    # which do not have region encoded will not return a bogus region component
    # when being decoded.
    fields_dict[0] = {'region': None}
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
              'region_code': region.region_code,
              'keyboards': ','.join(region.keyboards),
              'time_zone': region.time_zone,
              'language_codes': ','.join(region.language_codes),
              'keyboard_mechanical_layout': region.keyboard_mechanical_layout,
          }}
    super(RegionComponent, self).__init__(components_dict)
