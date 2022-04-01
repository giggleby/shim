# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re

from cros.factory.gooftool import cros_config as cros_config_module
from cros.factory.utils import file_utils
from cros.factory.utils.type_utils import Error

_RE_MAX98390_CHANNEL_NAME = re.compile(r'"(.+?) DSM Rdc"', re.MULTILINE)

_RE_MAX98373_CHANNEL_NAME = re.compile(r'"(.+?) ADC TEMP"', re.MULTILINE)

_RE_ALC1011_CHANNEL_NAME = re.compile(r'"(.+?) R0 Load Mode"', re.MULTILINE)

_REGEX_MAPPING = {
    'MAX98373': _RE_MAX98373_CHANNEL_NAME,
    'MAX98390': _RE_MAX98390_CHANNEL_NAME,
    'ALC1011': _RE_ALC1011_CHANNEL_NAME
}


class SoundCardInitConfParseError(Error):
  message_template = 'Fail to parse sound card init conf: %s. ' \
                     'The file might not be well formatted!\n %s'

  def __init__(self, sound_card_init_conf_path, content):
    Error.__init__(self)
    self.path = sound_card_init_conf_path
    self.content = content

  def __str__(self):
    return SoundCardInitConfParseError.message_template % \
           (self.path, self.content)


def GetSmartAmpInfo(shell=None, dut=None):
  """Returns the information about the smart amp on DUT.

  Amplifiers listed under `src/third_party/adhd/sound_card_init/amp/src` are
  smart amplifiers.

  Returns:
      A tuple of two strings and a list. They respectively represent the name
      of the amplifier on DUT, the path to sound-card-init-conf, and a list of
      the channel names of the smart amplifier.
      Return (None, None, None) if no smart amplifier is found.
  """

  def _ParseSoundCardInitConf(sound_card_init_path, sound_card_init_output,
                              regex):
    channel_names = []

    for channel in re.finditer(regex, sound_card_init_output):
      channel_names.append(channel.group(1))

    if len(channel_names) == 0:
      raise SoundCardInitConfParseError(sound_card_init_path,
                                        sound_card_init_output)

    return channel_names

  cros_config = cros_config_module.CrosConfig(shell=shell, dut=dut)
  smart_amp = cros_config.GetSmartAmp()
  if not smart_amp:
    logging.info('No smart amplifier found on DUT.')
    return None, None, None

  sound_card_init_file = cros_config.GetSoundCardInit()
  if not sound_card_init_file:
    raise Error('Cannot get the name of sound-card-init-conf via '
                '`cros_config /audio/main sound-card-init-conf`.')

  sound_card_init_path = '/etc/sound_card_init/%s' % sound_card_init_file
  file_utils.CheckPath(sound_card_init_path)

  regex = _REGEX_MAPPING.get(smart_amp)
  if not regex:
    raise Error('Currently we do support parsing the sound card init conf '
                'of %s. Please contact the factory bundle master to add the '
                'parsing script.' % smart_amp)

  sound_card_init_output = file_utils.ReadFile(sound_card_init_path)
  channel_names = _ParseSoundCardInitConf(sound_card_init_path,
                                          sound_card_init_output, regex)

  return smart_amp, sound_card_init_path, channel_names
