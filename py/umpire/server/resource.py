# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import enum
from typing import Union

from cros.factory.utils import file_utils


ConfigType = collections.namedtuple('ConfigType',
                                    ['type_name', 'fn_prefix', 'fn_suffix'])


class ConfigTypes(enum.Enum):
  umpire_config = ConfigType('umpire_config', 'umpire', 'json')
  payload_config = ConfigType('payload_config', 'payload', 'json')
  multicast_config = ConfigType('multicast_config', 'multicast', 'json')

  def __str__(self):
    return self.name


PayloadType = collections.namedtuple('PayloadType',
                                     ['type_name', 'import_pattern'])


class PayloadTypes(enum.Enum):
  complete = PayloadType('complete', 'complete/*')
  firmware = PayloadType('firmware', 'firmware/*')
  hwid = PayloadType('hwid', 'hwid/*')
  netboot_cmdline = PayloadType('netboot_cmdline',
                                'netboot/tftp/chrome-bot/*/cmdline*')
  netboot_firmware = PayloadType('netboot_firmware', 'netboot/image*.net.bin')
  netboot_kernel = PayloadType('netboot_kernel',
                               'netboot/tftp/chrome-bot/*/vmlinu*')
  project_config = PayloadType('project_config', 'project_config/*')
  release_image = PayloadType('release_image', 'release_image/*')
  test_image = PayloadType('test_image', 'test_image/*')
  toolkit = PayloadType('toolkit', 'toolkit/*')

  def __str__(self):
    return self.name


def GetResourceHashFromFile(file_path):
  """Calculates hash of a resource file.

  Args:
    file_path: path to the file.

  Returns:
    Hash of the file in hexadecimal.
  """
  return file_utils.MD5InHex(file_path)


def BuildConfigFileName(config_type: Union[str, ConfigTypes], file_path):
  """Builds resource name for a config file.

  Args:
    config_type: An element of ConfigTypes.
    file_path: path to the config file.

  Returns:
    Resource name.
  """
  if not isinstance(config_type, ConfigTypes):
    config_type = ConfigTypes[config_type]
  cfg_type = config_type.value
  return '.'.join([cfg_type.fn_prefix,
                   GetResourceHashFromFile(file_path),
                   cfg_type.fn_suffix])


def IsConfigFileName(basename):
  """Check if basename is a config file."""
  s = basename.split('.')
  if len(s) == 3:
    for config_type in ConfigTypes:
      type_info = config_type.value
      if s[0] == type_info.fn_prefix and s[2] == type_info.fn_suffix:
        return True
  return False
