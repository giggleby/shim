# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re

from cros.factory.utils import file_utils
from cros.factory.utils.type_utils import Error

from cros.factory.external.chromeos_cli import cros_config as cros_config_module


_RE_MAX98390_CHANNEL_NAME = re.compile(r'"(.+?) DSM Rdc"', re.MULTILINE)

_RE_MAX98373_CHANNEL_NAME = re.compile(r'"(.+?) ADC TEMP"', re.MULTILINE)

_RE_ALC1011_CHANNEL_NAME = re.compile(r'"(.+?) R0 Load Mode"', re.MULTILINE)

_RE_CS35L41_CHANNEL_NAME = re.compile(r'"(.+?) DSP1 Protection cd CAL_R"',
                                      re.MULTILINE)

_REGEX_MAPPING = {
    'MAX98373': _RE_MAX98373_CHANNEL_NAME,
    'MAX98390': _RE_MAX98390_CHANNEL_NAME,
    'ALC1011': _RE_ALC1011_CHANNEL_NAME,
    'CS35L41': _RE_CS35L41_CHANNEL_NAME,
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


def GetSmartAmpInfo(dut=None):
  """Returns the information about the amplifier on DUT.

  Amplifiers listed under `src/third_party/adhd/sound_card_init/amp/src` are
  smart amplifiers. Only smart amplifiers have sound-card-init file.

  Returns:
      A tuple of two strings and a list. They respectively represent the name
      of the amplifier on DUT, the path to sound-card-init-conf, and a list of
      the channel names of the smart amplifier.
      Return (amp_name, None, None) if no smart amplifiers are found.
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

  cros_config = cros_config_module.CrosConfig(dut=dut)
  amp_name = cros_config.GetAmplifier()
  sound_card_init_file = cros_config.GetSoundCardInit()
  if not sound_card_init_file:
    logging.info('No sound-card-init-conf found on DUT. '
                 'Assume using non-smart amplifier.')
    return amp_name, None, None

  sound_card_init_path = '/etc/sound_card_init/%s' % sound_card_init_file
  file_utils.CheckPath(sound_card_init_path)

  regex = _REGEX_MAPPING.get(amp_name)
  if not regex:
    raise Error('Currently we do support parsing the sound card init conf '
                'of %s. Please contact the factory bundle master to add the '
                'parsing script.' % amp_name)

  sound_card_init_output = file_utils.ReadFile(sound_card_init_path)
  channel_names = _ParseSoundCardInitConf(sound_card_init_path,
                                          sound_card_init_output, regex)

  return amp_name, sound_card_init_path, channel_names
