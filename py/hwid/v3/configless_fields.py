# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for configless fields.

Configless fields are some numeric fields in HWID that can be decoded without
board / project specific database (e.g. HWID database).
"""

import factory_common  # pylint: disable=unused-import
from cros.factory.hwid.v3 import common
from cros.factory.test import device_data_constants


class ConfiglessFields(object):
  """ConfiglessFields class

  The format of configless fields is decided by FIELDS:

  `hex(<FIELDS[0]>)-hex(<FIELDS[1]>)-...-hex(<FIELDS[-1]>)`

  And the content of feature list field is decided by FEATURE_LIST[version]
  where version is FIELDS[0]. To make it easier to extend (that is, add
  'has_new_feature' to the end of existing FEATURE_LIST[version]), always add
  a leading 1, so we can determine the length of feature list when it was
  encoded.

  For example,

  FIELDS = [
      'version',
      'memory',
      'storage',
      'feature_list'
  ]

  FEATURE_LIST = {
      0: [
          'has_touchscreen',
          'has_touchpad',
          'has_stylus',
          'has_front_camera',
          'has_rear_camera',
          'has_fingerprint',
          'is_convertible',
          'is_rma_device'
      ]
  }

  encoded string "0-8-74-180" represents version 0, 8G memory, 116G storage and
  has touchscreen('180' is 0b110000000).

  If we extend version 0,

  FEATURE_LIST = {
      0: [
          'has_touchscreen',
          'has_touchpad',
          'has_stylus',
          'has_front_camera',
          'has_rear_camera',
          'has_fingerprint',
          'is_convertible',
          'is_rma_device',
          'has_new_feature',
      ]
  }

  then, feature list field '180' means has touchscreen and don't have value for
  'has_new_feature'.
  """

  FIELDS = [
      'version', # version of feature list
      'memory',
      'storage',
      'feature_list'
  ]

  FEATURE_LIST = {
      0: [
          'has_touchscreen',
          'has_touchpad',
          'has_stylus',
          'has_front_camera',
          'has_rear_camera',
          'has_fingerprint',
          'is_convertible',
          'is_rma_device'
      ]
  }


  @classmethod
  def Encode(cls, db, bom, device_info, version, is_rma_device):
    """Return a encoded string according to version.

    Args:
      db: a Database object that is used to provide device-specific
          information.
      :type database: cros.factory.hwid.v3.database.Database

      bom: a BOM object that lists components on current device.
      :type bom: cros.factory.hwid.v3.bom.BOM

      device_info: a dictionary follows definition in `device_data`.
      :type device_info: dict

      version: use _FeatureList_{version} to encode/decode feature list field.
      :type version: int

    Returns:
      A string of encoded configless fields.
    """
    getter = _ConfiglessFieldGetter(
        db, bom, device_info, version, is_rma_device)
    return '-'.join(
        hex(getter(field)).upper().replace('0X', '') for field in cls.FIELDS)

  @classmethod
  def Decode(cls, encoded_string):
    """Return a dict of decoded info.

    Args:
      encoded_string: a string generated by ConfiglessFields.Encode
      :type encoded_string: string

    Returns:
      A decoded dict.
      For example, a return dict
      {
          'version': 0,
          'memory': 8,
          'storage' 116,
          'feature_list': {
              'has_touchscreen': 1,
              'has_touchpad': 0,
              'has_stylus': 0,
              'has_front_camera': 0,
              'has_rear_camera': 0,
              'has_fingerprint': 0,
              'is_convertible': 0,
              'is_rma_device': 0,
          }
      }
      means configless fileds version 0, 8G memory, 116G storage and has
      touchscreen.
    """
    decoder = _ConfiglessFieldDecoder(encoded_string)
    fields = {
        field: decoder(field)
        for field in cls.FIELDS
    }
    return fields


class FeatureList(object):
  """Encode/Decode feature list according to ConfiglessFields.FeatureList"""
  def __init__(self, version):
    self.features = ConfiglessFields.FEATURE_LIST[version]

  def Encode(self, components):
    encoded_value = 1
    for feature in self.features:
      encoded_value <<= 1
      encoded_value |= components.get(feature, 0)
    return encoded_value

  def Decode(self, encoded_value):
    feature_count = len(self.features)
    if encoded_value >= 2 ** (feature_count + 1):
      raise common.HWIDException(
          'The given configless fields is invalid. The last field should be a '
          'hex value in [0, %s].' %
          hex(2 ** (feature_count + 1) - 1).upper().replace('0X', ''))

    bin_string = bin(encoded_value).replace('0b', '')[1:]
    result = {
        self.features[i]: int(bin_string[i])
        for i in xrange(len(bin_string))
    }
    return result


class _ConfiglessFieldGetter(object):
  """Extract value of from BOM / device_info for configless fields."""
  def __init__(self, db, bom, device_info, version, is_rma_device):
    self._db = db
    self._bom = bom
    self._device_info = device_info or {}
    self._version = version
    self._is_rma_device = is_rma_device
    self._feature_list = FeatureList(version)

  def __call__(self, field_name):
    """Get value of a field."""
    return getattr(self, field_name)

  @property
  def memory(self):
    if self.is_rma_device and 'dram' not in self._bom.components:
      # We might be generating HWID for RMA spare boards, real DRAM info might
      # not be available until the spare board is mounted on device.  So it's
      # okay to omit this field.
      return 0
    size_mb = sum(int(self._db.GetComponents('dram')[comp].values['size'])
                  for comp in self._bom.components['dram'])
    return size_mb // 1024

  @property
  def storage(self):
    if self.is_rma_device and 'storage' not in self._bom.components:
      # We might be generating HWID for RMA spare boards, real storage info
      # might not be available until the spare board is mounted on device.  So
      # it's okay to omit this field.
      return 0
    sectors = sum(int(self._db.GetComponents('storage')[comp].values['sectors'])
                  for comp in self._bom.components['storage'])
    # Assume sector size is 512 bytes
    return sectors // 2 // 1024 // 1024

  @property
  def version(self):
    return self._version

  @property
  def is_rma_device(self):
    return self._is_rma_device

  @property
  def feature_list(self):
    """Get feature list encoded string."""
    components = self._device_info.get(device_data_constants.KEY_COMPONENT, {})
    # Set is_rma_device.
    components['is_rma_device'] = self._is_rma_device
    return self._feature_list.Encode(components)


class _ConfiglessFieldDecoder(object):
  """Extract value of encoded string for configless fields."""
  def __init__(self, encoded_string):
    encoded_fields = [int(field, 16) for field in encoded_string.split('-')]
    if len(encoded_fields) != len(ConfiglessFields.FIELDS):
      raise common.HWIDException(
          'The given configless fields %r is invalid. It must have %r fields.' %
          (encoded_string, len(ConfiglessFields.FIELDS)))

    self._encoded_fields = dict(zip(ConfiglessFields.FIELDS, encoded_fields))
    self._feature_list = FeatureList(self._encoded_fields['version'])

  def __call__(self, field_name):
    """Get decoded value of a field.

    By default, convert encoded hex string to integer.
    To override the behavior, create a property of field name
    (e.g. `feature_list`).
    """
    try:
      return getattr(self, field_name)
    except Exception:
      return self._encoded_fields[field_name]

  @property
  def feature_list(self):
    """Construct the dict of feature list"""
    return self._feature_list.Decode(self._encoded_fields['feature_list'])
