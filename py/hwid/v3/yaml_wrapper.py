# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A yaml module wrapper for HWID v3.

This module overwrites the functions we are interested in to make a separation
from the origin yaml module.
"""

import collections
import functools
import itertools

from yaml import *  # pylint: disable=wildcard-import,unused-wildcard-import
from yaml import __with_libyaml__
from yaml import constructor
from yaml import nodes
from yaml import resolver

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import rule
from cros.factory.test.l10n import regions
from cros.factory.utils import schema
from cros.factory.utils import yaml_utils


# Prefer CSafe* to improve performance.
_SafeLoader, _SafeDumper = ((CSafeLoader, CSafeDumper) if __with_libyaml__ else
                            (SafeLoader, SafeDumper))


class V3Loader(_SafeLoader):
  """A HWID v3 yaml Loader for patch separation."""


class V3Dumper(_SafeDumper):
  """A HWID v3 yaml Dumper for patch separation."""


class V3DumperInternal(_SafeDumper):
  """A HWID v3 yaml Dumper for dumping unexposed tags for internal use."""


# Because PyYaml can only represent scalar, sequence, mapping object, the
# customized output format must be one of this:
#   !custom_scalar_tag STRING
#   !custom_sequence_tag [object1, object2]
#   !custom_mapping_tag {key1: value1, key2: value2}
# We cannot only output the tag without any data, such as !region_component.
# Therefore we add a dummy string afterward, and remove it in post-processing.
_YAML_DUMMY_STRING = 'YAML_DUMMY_STRING'
_DUMMY_STRING_DUMP_STYLE = (f' {_YAML_DUMMY_STRING}'
                            if __with_libyaml__ else f" '{_YAML_DUMMY_STRING}'")


def _RemoveDummyStringWrapper(func):

  def wrapper(*args, **kwargs):
    """Remove the dummy string in the yaml result."""
    return func(*args, **kwargs).replace(_DUMMY_STRING_DUMP_STYLE, '')

  return wrapper


def _OptionalInternalDumpers(func):

  @functools.wraps(func)
  def wrapper(*args, internal=False, **kwargs):
    return func(*args, Dumper=V3DumperInternal if internal else V3Dumper,
                **kwargs)

  return wrapper


# Patch functions to use V3Loader and V3Dumper.  safe_load does not accept the
# argument Loader, so we have to achieve this by customizing yaml.load.
safe_load = functools.partial(load, Loader=V3Loader)
safe_load_all = functools.partial(load_all, Loader=V3Loader)
add_constructor = functools.partial(add_constructor, Loader=V3Loader)
safe_dump = _RemoveDummyStringWrapper(_OptionalInternalDumpers(dump))
safe_dump_all = _RemoveDummyStringWrapper(_OptionalInternalDumpers(dump_all))
add_representer = _OptionalInternalDumpers(add_representer)


# Override existing YAML tags to disable some auto type conversion.
def RestrictedBoolConstructor(self, node):
  """Override PyYaml default behavior for bool values

  Only 'true' and 'false' will be parsed as boolean.  Other values
  (on|off|yes|no) will be return as string.

  It does more harm than good to allow this conversion.  HWID database seldom
  contains boolean values, writing 'true|false' instead of 'on|off|yes|no' for
  boolean values should be ok.  Further more, 'no' (string) is the country code
  for Norway.  We need to always remember to quote 'no' in region component if
  we don't override the default behavior.
  """
  if not isinstance(node, nodes.ScalarNode):
    return self.construct_scalar(node)  # this should raise an exception
  value = node.value
  if value.lower() == 'true':
    return True
  if value.lower() == 'false':
    return False
  return self.construct_yaml_str(node)


add_constructor('tag:yaml.org,2002:bool', RestrictedBoolConstructor)


# Override existing YAML representer for strings to switch the representing
# style automatically.
def _HWIDStrPresenter(yaml_dumper, data):
  return yaml_dumper.represent_scalar('tag:yaml.org,2002:str', data,
                                      style='|' if '\n' in data else None)


add_representer(str, _HWIDStrPresenter)
add_representer(str, _HWIDStrPresenter, internal=True)


# The following register customized YAML tags.
# pylint: disable=abstract-method
class _HWIDV3YAMLTagHandler(yaml_utils.BaseYAMLTagHandler):
  LOADERS = (V3Loader, )
  DUMPERS = (V3Dumper, V3DumperInternal)

  @classmethod
  def IsDumperInternal(cls, dumper):
    return isinstance(dumper, V3DumperInternal)


# The dictionary class for the HWID database object.
Dict = collections.OrderedDict


class _DefaultMappingHandler(_HWIDV3YAMLTagHandler):
  YAML_TAG = resolver.BaseResolver.DEFAULT_MAPPING_TAG
  TARGET_CLASS = Dict

  @classmethod
  def YAMLConstructor(cls, loader, node, deep=False):
    if not isinstance(node, nodes.MappingNode):
      raise constructor.ConstructorError(
          None, None, f'Expected a mapping node, but found {node.id}.',
          node.start_mark)
    mapping = cls.TARGET_CLASS()
    for key_node, value_node in node.value:
      key = loader.construct_object(key_node, deep=deep)
      try:
        hash(key)
      except TypeError:
        raise constructor.ConstructorError(
            'While constructing a mapping', node.start_mark,
            f'found unacceptable key ({key}).', key_node.start_mark) from None
      value = loader.construct_object(value_node, deep=deep)
      if key in mapping:
        raise constructor.ConstructorError(
            'While constructing a mapping', node.start_mark,
            f'found duplicated key ({key}).', key_node.start_mark)
      mapping[key] = value
    return mapping

  @classmethod
  def YAMLRepresenter(cls, dumper, data):
    return dumper.represent_dict(data.items())


_UNKNOWN_REGION_INDEX = 255
_UNKNOWN_REGION_CODE = 'unknown'


class RegionField(dict):
  """A class for holding the region field data in a HWID database."""

  def __init__(self, region_names=None):
    if region_names is None:
      self._is_legacy_style = True
      fields_dict = dict(
          (i, {
              common.REGION_CLS: code
          })
          for (i, code) in enumerate(regions.LEGACY_REGIONS_LIST, 1)
          if code in regions.REGIONS)
      fields_dict.setdefault(_UNKNOWN_REGION_INDEX,
                             {common.REGION_CLS: _UNKNOWN_REGION_CODE})
    else:
      self._is_legacy_style = False
      # The numeric ids of valid regions start from 1.
      # crbug.com/624257: If no explicit regions defined, populate with only the
      # legacy list.
      fields_dict = dict((i, {
          common.REGION_CLS: n
      }) for i, n in enumerate(region_names, 1))

    # 0 is a reserved field and is set to {region: []}, so that previous HWIDs
    # which do not have region encoded will not return a bogus region component
    # when being decoded.
    fields_dict[0] = {
        common.REGION_CLS: []
    }

    super().__init__(fields_dict)

  @property
  def is_legacy_style(self):
    return self._is_legacy_style

  def GetRegionNames(self):
    """Returns the material that is used to initialize this instance."""
    if self.is_legacy_style:
      return None
    return [self[idx][common.REGION_CLS] for idx in range(1, len(self))]


class _RegionFieldYAMLTagHandler(_HWIDV3YAMLTagHandler):
  """Metaclass for registering the !region_field YAML tag.

  The yaml format of RegionField should be:
    !region_field [<region_code_1>, <region_code_2>,...]
  """
  YAML_TAG = '!region_field'
  TARGET_CLASS = RegionField

  @classmethod
  def YAMLConstructor(cls, loader, node, deep=False):
    if isinstance(node, nodes.SequenceNode):
      return cls.TARGET_CLASS(loader.construct_sequence(node, deep=deep))
    return cls.TARGET_CLASS()

  @classmethod
  def YAMLRepresenter(cls, dumper, data):
    """Represent the list style of RegionField.

    When the RegionField is legacy style, we output:
        !region_field 'YAML_DUMMY_STRING'
    Otherwise when we dump the RegionField to yaml, it should output like:
        !region_field [us, gb]
    """
    region_names = data.GetRegionNames()
    if region_names is not None:
      return dumper.represent_sequence(cls.YAML_TAG, region_names)
    return dumper.represent_scalar(cls.YAML_TAG, _YAML_DUMMY_STRING)


class _RegionComponent(dict):
  """A class for holding the region component data in a HWID database.

  The instance of this class is expected to be frozen after constructing.
  """

  def __init__(self, status_lists=None):
    # Load system regions.
    components_dict = {
        'items': {}
    }
    for code, region in regions.BuildRegionsDict(include_all=True).items():
      region_comp = {
          'values': {
              'region_code': region.region_code
          }
      }
      if code not in regions.REGIONS:
        region_comp['status'] = common.ComponentStatus.unsupported
      components_dict['items'][code] = region_comp

    components_dict['items'][_UNKNOWN_REGION_CODE] = {
        'status': common.ComponentStatus.unsupported,
        'values': {
            'region_code': _UNKNOWN_REGION_CODE
        }
    }

    # Apply customized status lists.
    if status_lists is not None:
      for status in common.ComponentStatus:
        for region in status_lists.get(status, []):
          components_dict['items'][region]['status'] = status

    super().__init__(components_dict)
    self.status_lists = status_lists

  def __eq__(self, rhs):
    return (isinstance(rhs, _RegionComponent) and super().__eq__(rhs) and
            self.status_lists == rhs.status_lists)

  def __ne__(self, rhs):
    return not self.__eq__(rhs)


class _RegionComponentYAMLTagHandler(_HWIDV3YAMLTagHandler):
  """Metaclass for registering the !region_component YAML tag."""
  YAML_TAG = '!region_component'
  TARGET_CLASS = _RegionComponent

  _STATUS_LISTS_SCHEMA = schema.FixedDict(
      'status lists', optional_items={
          s: schema.List('regions', element_type=schema.Scalar('region', str),
                         min_length=1)
          for s in common.ComponentStatus
      })

  @classmethod
  def YAMLConstructor(cls, loader, node, deep=False):
    if isinstance(node, nodes.ScalarNode):
      if node.value:
        raise constructor.ConstructorError(
            f'Expected empty scalar node, but got {node.value!r}.')
      return cls.TARGET_CLASS()

    status_lists = _DefaultMappingHandler.YAMLConstructor(
        loader, node, deep=True)
    cls._VerifyStatusLists(status_lists)
    return cls.TARGET_CLASS(status_lists)

  @classmethod
  def YAMLRepresenter(cls, dumper, data):
    if data.status_lists is None:
      return dumper.represent_scalar(cls.YAML_TAG, _YAML_DUMMY_STRING)
    return dumper.represent_mapping(cls.YAML_TAG, data.status_lists)

  @classmethod
  def _VerifyStatusLists(cls, status_lists):
    try:
      cls._STATUS_LISTS_SCHEMA.Validate(status_lists)
    except schema.SchemaException as e:
      raise constructor.ConstructorError(f'{e}{status_lists!r}')

    for regions1, regions2 in itertools.combinations(status_lists.values(), 2):
      duplicated_regions = set(regions1) & set(regions2)
      if duplicated_regions:
        raise constructor.ConstructorError(
            f'found ambiguous status for regions {duplicated_regions!r}.')


class _RegexpYAMLTagHandler(_HWIDV3YAMLTagHandler):
  """Class for creating regular expression-enabled Value object.

  This class registers YAML constructor and representer to decode from YAML
  tag '!re' and data to a Value object, and to encode a Value object to its
  corresponding YAML representation.
  """
  YAML_TAG = '!re'
  TARGET_CLASS = rule.Value

  @classmethod
  def YAMLConstructor(cls, loader, node, deep=False):
    value = loader.construct_scalar(node)
    return cls.TARGET_CLASS(value, is_re=True)

  @classmethod
  def YAMLRepresenter(cls, dumper, data):
    if data.is_re:
      return dumper.represent_scalar(cls.YAML_TAG, data.raw_value)
    return dumper.represent_data(data.raw_value)


class _LinkAVLYAMLTagHandler(_HWIDV3YAMLTagHandler):
  YAML_TAG = '!link_avl'
  TARGET_CLASS = rule.AVLProbeValue

  @classmethod
  def YAMLConstructor(cls, loader, node, deep=False):
    # TODO(clarkchung): Consider creating another customized loader
    # (e.g. V3LoaderInternal) here and keep V3Loader unaware of this syntax.
    if not isinstance(node, nodes.MappingNode):
      raise constructor.ConstructorError(
          f'Expected an mapping node, but got {node.value!r}.')

    existing_values = _DefaultMappingHandler.YAMLConstructor(
        loader, node, deep=True)
    converter_identifier = existing_values['converter']
    probe_value_matched = existing_values['probe_value_matched']
    values = existing_values['original_values']
    return cls.TARGET_CLASS(converter_identifier, probe_value_matched, values)

  @classmethod
  def YAMLRepresenter(cls, dumper, data):
    if cls.IsDumperInternal(dumper):
      return dumper.represent_mapping(
          cls.YAML_TAG, {
              'converter': data.converter_identifier,
              'probe_value_matched': data.probe_value_matched,
              'original_values': None if data.value_is_none else Dict(data)
          })
    return (dumper.represent_none(data)
            if data.value_is_none else dumper.represent_dict(data.items()))


class _FromFactoryBundleTagHandler(_HWIDV3YAMLTagHandler):
  YAML_TAG = '!from_factory_bundle'
  TARGET_CLASS = rule.FromFactoryBundle

  @classmethod
  def YAMLConstructor(cls, loader, node, deep=False):
    if not isinstance(node, nodes.MappingNode):
      raise constructor.ConstructorError(
          f'Expected an mapping node, but got {node.value!r}.')
    comp = _DefaultMappingHandler.YAMLConstructor(loader, node, deep=True)
    bundle_uuids = comp.pop('bundle_uuids', None)
    return cls.TARGET_CLASS(bundle_uuids, **comp)

  @classmethod
  def YAMLRepresenter(cls, dumper, data):
    if cls.IsDumperInternal(dumper):
      data['bundle_uuids'] = data.bundle_uuids
      return dumper.represent_mapping(cls.YAML_TAG, Dict(data))
    return dumper.represent_dict(data.items())
