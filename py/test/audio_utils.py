#!/usr/bin/python

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is audio utility module to setup amixer related options."""

from __future__ import print_function

import logging
import os
import re
import tempfile
import yaml

import factory_common  # pylint: disable=W0611
from glob import glob
from cros.factory.utils.process_utils import PIPE, Spawn

# Configuration file is put under overlay directory and it can be customized
# for each board.
# Configuration file is using YAML nested collections format.
#
# Structure of this configuration file:
# card_index:
#   action:
#     "amixer configuration name": "value"
#
# =============== Configuration Example ===================
# 0:
#   enable_dmic:
#     "DIGMICL Switch": "on"
#     "DIGMICR Switch": "on"
#   disable_dmic:
#     "DIGMICL Switch": "off"
#     "DIGMICR Switch": "off"
# =========================================================
_DEFAULT_CONFIG_PATH = '/usr/local/factory/py/test/audio.conf'

# Tools from platform/audiotest
AUDIOFUNTEST_PATH = 'audiofuntest'
AUDIOLOOP_PATH = 'looptest'
SOX_PATH = 'sox'
DEFAULT_NUM_CHANNELS = 2

_DEFAULT_SOX_FORMAT = '-t raw -b 16 -e signed -r 48000 -L'

# Strings for key in audio.conf
HP_JACK_NAME = 'headphone_jack'
MIC_JACK_NAME = 'mic_jack'
HP_JACK_DETECT = 'headphone_jack_detect'
MIC_JACK_DETECT = 'mic_jack_detect'

DEFAULT_HEADPHONE_JACK_NAMES = ['Headphone Jack', 'Headset Jack']
# The input device event may be on Headphone Jack
DEFAULT_MIC_JACK_NAMES = ['Mic Jack'] + DEFAULT_HEADPHONE_JACK_NAMES

# SOX related utilities
def GetPlaySineArgs(channel, odev='default', freq=1000, duration_secs=10,
                    sample_size=16):
  """Gets the command args to generate a sine wav to play to odev.

  Args:
    channel: 0 for left, 1 for right; otherwize, mono.
    odev: ALSA output device.
    freq: Frequency of the generated sine tone.
    duration_secs: Duration of the generated sine tone.
    sample_size: Output audio sample size. Default to 16.

  Returns:
    A command string to generate a sine wav
  """
  cmdargs = "%s -b %d -n -t alsa %s synth %d" % (
      SOX_PATH, sample_size, odev, duration_secs)
  if channel == 0:
    cmdargs += " sine %d sine 0" % freq
  elif channel == 1:
    cmdargs += " sine 0 sine %d" % freq
  else:
    cmdargs += " sine %d" % freq
  return cmdargs


def TrimAudioFile(in_path, out_path, start, end,
                  num_channel, sox_format=_DEFAULT_SOX_FORMAT):
  """Trims an audio file using sox command.

  Args:
    in_path: Path to the input audio file.
    out_path: Path to the output audio file.
    start: The starting time in seconds of specified range.
    end: The ending time in seconds of specified range.
         Sets to None for the end of audio file.
    num_channel: The number of channels in input file.
    sox_format: Format to generate sox command.
  """
  cmd = "%s -c %s %s %s -c %s %s %s trim %s" % (
      SOX_PATH, str(num_channel), sox_format, in_path,
      str(num_channel), sox_format, out_path, str(start))
  if end is not None:
    cmd += str(end)

  Spawn(cmd.split(' '), log=True, check_call=True)


# Functions to compose customized sox command, execute it and process the
# output of sox command.
def SoxMixerOutput(in_file, channel, sox_format=_DEFAULT_SOX_FORMAT):
  """Gets sox mixer command to reduce channel.

  Args:
    in_file: Input file name.
    channel: The selected channel to take effect.
    sox_format: A dict format to generate sox command.

  Returns:
    The output of sox mixer command
  """
  # The selected channel from input.(1 for the first channel).
  remix_channel = channel + 1

  command = '%s -c 2 %s %s -c 1 %s - remix %s' % (SOX_PATH,
      sox_format, in_file, sox_format, str(remix_channel))
  return Spawn(command.split(' '), log=True, read_stdout=True).stdout_data


def SoxStatOutput(in_file, channel, sox_format=_DEFAULT_SOX_FORMAT):
  """Executes sox stat command.

  Args:
    in_file: Input file name.
    channel: The selected channel.
    sox_format: Format to generate sox command.

  Returns:
    The output of sox stat command
  """
  sox_output = SoxMixerOutput(in_file, channel, sox_format)
  with tempfile.NamedTemporaryFile(delete=False) as temp_file:
    temp_file.write(sox_output)
  stat_cmd = '%s -c 1 %s %s -n stat' % (SOX_PATH, sox_format, temp_file.name)
  output = Spawn(stat_cmd.split(' '), read_stderr=True).stderr_data
  os.unlink(temp_file.name)
  return output


def GetAudioMinimumAmplitude(sox_output):
  """Gets the audio minimum amplitude from sox stat output

  Args:
    sox_output: Output of sox stat command.

  Returns:
    The minimum amplitude parsed from sox stat output.
  """
  m = re.search('^Minimum\s+amplitude:\s+(.+)$', sox_output, re.MULTILINE)
  if m is not None:
    return float(m.group(1))
  return None


def GetAudioMaximumAmplitude(sox_output):
  """Gets the audio maximum amplitude from sox stat output

  Args:
    sox_output: Output of sox stat command.

  Returns:
    The maximum amplitude parsed from sox stat output.
  """
  m = re.search('^Maximum\s+amplitude:\s+(.+)$', sox_output, re.MULTILINE)
  if m is not None:
    return float(m.group(1))
  return None


def GetAudioRms(sox_output):
  """Gets the audio RMS value from sox stat output

  Args:
    sox_output: Output of sox stat command.

  Returns:
    The RMS value parsed from sox stat output.
  """
  m = re.search('^RMS\s+amplitude:\s+(.+)$', sox_output, re.MULTILINE)
  if m is not None:
    return float(m.group(1))
  return None


def GetRoughFreq(sox_output):
  """Gets the rough audio frequency from sox stat output

  Args:
    sox_output: Output of sox stat command.

  Returns:
    The rough frequency value parsed from sox stat output.
  """
  _SOX_ROUGH_FREQ_RE = re.compile('Rough\s+frequency:\s+(.+)')
  for rms_line in sox_output.split('\n'):
    m = _SOX_ROUGH_FREQ_RE.match(rms_line)
    if m is not None:
      return int(m.group(1))
  return None


def NoiseReduceFile(in_file, noise_file, out_file,
                    sox_format=_DEFAULT_SOX_FORMAT):
  """Runs the sox command to noise-reduce in_file using
     the noise profile from noise_file.

  Args:
    in_file: The file to noise reduce.
    noise_file: The file containing the noise profile.
        This can be created by recording silence.
    out_file: The file contains the noise reduced sound.
    sox_format: The  sox format to generate sox command.
  """
  f = tempfile.NamedTemporaryFile(delete=False)
  f.close()
  prof_cmd = '%s -c 2 %s %s -n noiseprof %s' % (SOX_PATH,
      sox_format, noise_file, f.name)
  Spawn(prof_cmd.split(' '), check_call=True)

  reduce_cmd = ('%s -c 2 %s %s -c 2 %s %s noisered %s' %
      (SOX_PATH, sox_format, in_file, sox_format, out_file, f.name))
  Spawn(reduce_cmd.split(' '), check_call=True)
  os.unlink(f.name)


def GetCardIndexByName(card_name):
  """Get audio card index by card name.

  Args:
    card_name: Audio card name.

  Returns:
    Card index of the card name.

  Raises:
    ValueError when card name does not exist.
  """
  _RE_CARD_INDEX = re.compile(r'^card (\d+):.*?\[(.+?)\]')
  output = Spawn(['aplay', '-l'], read_stdout=True).stdout_data
  for line in output.split('\n'):
    m = _RE_CARD_INDEX.match(line)
    if m is not None and m.group(2) == card_name:
      return m.group(1)
  raise ValueError('device name %s is incorrect' % card_name)

class AudioUtil(object):
  """This class is used for setting audio related configuration.
  It reads audio.conf initially to decide how to enable/disable each
  component by amixer.
  """
  def __init__(self, config_path=_DEFAULT_CONFIG_PATH):
    self._restore_mixer_control_stack = []
    if os.path.exists(config_path):
      with open(config_path, 'r') as config_file:
        self.audio_config = yaml.load(config_file)
      for index in self.audio_config.keys():
        if index.isdigit() is False:
          new_index = GetCardIndexByName(index)
          self.audio_config[new_index] = self.audio_config[index]
    else:
      self.audio_config = {}
      logging.info('Cannot find configuration file.')

  def GetMixerControls(self, name, card='0'):
    """Gets the value for mixer control.

    Args:
      name: The name of mixer control
      card: The index of audio card
    """
    list_controls = Spawn(['amixer', '-c%d' % int(card), 'controls'],
                          stdout=PIPE)
    _CONTROL_RE = re.compile('numid=(\d+).*?name=\'%s\'' % name)
    numid = 0
    for ctl in list_controls.stdout:
      m = _CONTROL_RE.match(ctl)
      if m:
        numid = int(m.group(1))
        break
    if numid == 0:
      logging.info('Unable to find mixer control %s', name)
      return None

    output = Spawn(['amixer', '-c%d' % int(card), 'cget', 'numid=%d' % numid],
                   stdout=PIPE)
    lines = output.stdout.read()
    logging.info('lines: %r', lines)
    m = re.search(r'^.*: values=(.*)$', lines, re.MULTILINE)
    if m:
      return m.group(1)
    else:
      logging.info('Unable to get value for mixer control %s, numid=%d',
                   name, numid)
      return None

  def SetMixerControls(self, mixer_settings, card='0', store=True):
    """Sets all mixer controls listed in the mixer settings on card.

    Args:
      mixer_settings: A dict of mixer settings to set.
      card: The index of audio card
      store: Store the current value so it can be restored later using
        RestoreMixerControls.
    """
    logging.info('Setting mixer control values on %s', card)
    restore_mixer_settings = dict()
    for name, value in mixer_settings.items():
      if store:
        old_value = self.GetMixerControls(name, card)
        restore_mixer_settings[name] = old_value
        logging.info('Saving %s with value %s on card %s',
                     name, old_value, card)
      logging.info('Setting %s to %s on card %s', name, value, card)
      command = ['amixer', '-c', card, 'cset', 'name=%r' % name, value]
      Spawn(command, check_call=True)
    if store:
      self._restore_mixer_control_stack.append((restore_mixer_settings, card))

  def RestoreMixerControls(self):
    """Restores the mixer controls stored in _restore_mixer_control_stack.

    Also, clear _restore_mixer_control_stack.
    """
    while self._restore_mixer_control_stack:
      mixer_settings, card = self._restore_mixer_control_stack.pop()
      self.SetMixerControls(mixer_settings, card, False)
    self._restore_mixer_control_stack = []

  def FindEventDeviceByName(self, name):
    """Finds the event device by matching name.

    Args:
      name: The name to look up event device by substring matching.

    Returns:
      The full name of the found event device of form /dev/input/event*
    """
    for evdev in glob('/dev/input/event*'):
      f = open(os.path.join('/sys/class/input/',
                            os.path.basename(evdev),
                           'device/name'),
               'r')
      evdev_name = f.read()
      if evdev_name.find(name) != -1:
        logging.info('Find %s Event Device %s', name, evdev)
        return evdev
    return None

  def GetHeadphoneJackStatus(self, card='0'):
    """Gets the plug/unplug status of headphone jack.

    Args:
      card: The index of audio card.

    Returns:
      True if headphone jack is plugged, False otherwise.
    """
    status = None

    if card in self.audio_config and HP_JACK_DETECT in self.audio_config[card]:
      command = self.audio_config[card][HP_JACK_DETECT]
      logging.info('Getting headphone jack status by %s', command)
      jack_status = Spawn(command, read_stdout=True).stdout_data.strip()
      status = True if jack_status == '1' else False
      logging.info('headphone jack status %s', status)
      return status

    possible_names = []
    if card in self.audio_config and HP_JACK_NAME in self.audio_config[card]:
      possible_names = [self.audio_config[card][HP_JACK_NAME]]
    else:
      possible_names = DEFAULT_HEADPHONE_JACK_NAMES

    # Loops through possible names. Uses mixer control or evtest
    # to query jack status.
    for hp_jack_name in possible_names:
      values = self.GetMixerControls(hp_jack_name, card)
      if values:
        status = True if values == 'on' else False
        break

      # Check input device for headphone
      evdev = self.FindEventDeviceByName(hp_jack_name)
      if evdev:
        query = Spawn(['evtest', '--query', evdev, 'EV_SW',
                       'SW_HEADPHONE_INSERT'],
                      call=True)
        status = (query.returncode != 0)
        break

    logging.info('Getting headphone jack status %s', status)
    if status is None:
      raise ValueError('No methods to get headphone jack status')

    return status

  def GetMicJackStatus(self, card='0'):
    """Gets the plug/unplug status of mic jack.

    Args:
      card: The index of audio card.

    Returns:
      True if mic jack is plugged, False otherwise.
    """
    status = None

    if card in self.audio_config and MIC_JACK_DETECT in self.audio_config[card]:
      command = self.audio_config[card][MIC_JACK_DETECT]
      logging.info('Getting microphone jack status by %s', command)
      jack_status = Spawn(command, read_stdout=True).stdout_data.strip()
      status = True if jack_status == '1' else False
      logging.info('microphone jack status %s', status)
      return status

    possible_names = []
    if card in self.audio_config and MIC_JACK_NAME in self.audio_config[card]:
      possible_names = [self.audio_config[card][MIC_JACK_NAME]]
    else:
      possible_names = DEFAULT_MIC_JACK_NAMES

    # Loops through possible names. Uses mixer control or evtest
    # to query jack status.
    for jack_name in possible_names:
      values = self.GetMixerControls(jack_name, card)
      if values:
        status = True if values == 'on' else False
        break

      evdev = self.FindEventDeviceByName(jack_name)
      if evdev:
        query = Spawn(['evtest', '--query', evdev, 'EV_SW',
                       'SW_MICROPHONE_INSERT'],
                      call=True)
        status = (query.returncode != 0)
        break

    logging.info('Getting microphone jack status %s', status)
    if status is None:
      raise ValueError('No methods to get microphone jack status')

    return status

  def ApplyAudioConfig(self, action, card='0'):
    if card in self.audio_config:
      if action in self.audio_config[card]:
        self.SetMixerControls(self.audio_config[card][action], card)
      else:
        logging.info('Action %s cannot be found in card %s', action, card)
    else:
      logging.info('Card %s does not exist', card)

  def InitialSetting(self, card='0'):
    self.ApplyAudioConfig('initial', card)

  def EnableSpeaker(self, card='0'):
    self.ApplyAudioConfig('enable_speaker', card)

  def MuteLeftSpeaker(self, card='0'):
    self.ApplyAudioConfig('mute_left_speaker', card)

  def MuteRightSpeaker(self, card='0'):
    self.ApplyAudioConfig('mute_right_speaker', card)

  def DisableSpeaker(self, card='0'):
    self.ApplyAudioConfig('disable_speaker', card)

  def EnableHeadphone(self, card='0'):
    self.ApplyAudioConfig('enable_headphone', card)

  def MuteLeftHeadphone(self, card='0'):
    self.ApplyAudioConfig('mute_left_headphone', card)

  def MuteRightHeadphone(self, card='0'):
    self.ApplyAudioConfig('mute_right_headphone', card)

  def DisableHeadphone(self, card='0'):
    self.ApplyAudioConfig('disable_headphone', card)

  def EnableDmic(self, card='0'):
    self.ApplyAudioConfig('enable_dmic', card)

  def MuteLeftDmic(self, card='0'):
    self.ApplyAudioConfig('mute_left_dmic', card)

  def MuteRightDmic(self, card='0'):
    self.ApplyAudioConfig('mute_right_dmic', card)

  def DisableDmic(self, card='0'):
    self.ApplyAudioConfig('disable_dmic', card)

  def EnableMLBDmic(self, card='0'):
    self.ApplyAudioConfig('enable_mlb_dmic', card)

  def MuteLeftMLBDmic(self, card='0'):
    self.ApplyAudioConfig('mute_left_mlb_dmic', card)

  def MuteRightMLBDmic(self, card='0'):
    self.ApplyAudioConfig('mute_right_mlb_dmic', card)

  def DisableMLBDmic(self, card='0'):
    self.ApplyAudioConfig('disable_mlb_dmic', card)

  def EnableExtmic(self, card='0'):
    self.ApplyAudioConfig('enable_extmic', card)

  def MuteLeftExtmic(self, card='0'):
    self.ApplyAudioConfig('mute_left_extmic', card)

  def MuteRightExtmic(self, card='0'):
    self.ApplyAudioConfig('mute_right_extmic', card)

  def DisableExtmic(self, card='0'):
    self.ApplyAudioConfig('disable_extmic', card)

  def SetSpeakerVolume(self, volume=0, card='0'):
    if not isinstance(volume, int) or volume < 0:
      raise ValueError('Volume should be positive integer.')
    if card in self.audio_config:
      if 'set_speaker_volume' in self.audio_config[card]:
        for name in self.audio_config[card]['set_speaker_volume'].keys():
          if 'Volume' in name:
            self.audio_config[card]['set_speaker_volume'][name] = str(volume)
            self.SetMixerControls(
                self.audio_config[card]['set_speaker_volume'], card)
            break

  def SetHeadphoneVolume(self, volume=0, card='0'):
    if not isinstance(volume, int) or volume < 0:
      raise ValueError('Volume should be positive integer.')
    if card in self.audio_config:
      if 'set_headphone_volume' in self.audio_config[card]:
        for name in self.audio_config[card]['set_headphone_volume'].keys():
          if 'Volume' in name:
            self.audio_config[card]['set_headphone_volume'][name] = str(volume)
            self.SetMixerControls(
                self.audio_config[card]['set_headphone_volume'], card)
            break

class CRAS(object):
  """Class used to access CRAS information by
  executing commnad cras_test_clinet.
  """
  OUTPUT = 0
  INPUT = 1

  class Node(object):
    """Class to represent a input or output node in CRAS."""
    def __init__(self, node_id, plugged, name):
      self.node_id = node_id
      self.plugged = plugged
      self.name = name

    def __str__(self):
      return 'Cras node %s, id=%s, plugged=%s' % (self.name, self.node_id,
                                                  self.plugged)

  def __init__(self):
    self.CRAS_TEST_CLIENT = 'cras_test_client'
    self._RE_INPUT_NODES_SECTION = re.compile('Input Nodes:.*')
    self._RE_OUTPUT_NOTES_SECTION = re.compile('Output Nodes:.*')
    self._RE_END_SECTION = re.compile('^[A-Z].*')
    self._RE_IO_NODE_LINE = re.compile('\t(\d+:\d+).*')

    self.input_nodes = []
    self.output_nodes = []

  def DumpServerInfo(self):
    """Gets the server info of CRAS"""
    command = [self.CRAS_TEST_CLIENT, '--dump_server_info']
    return Spawn(command, read_stdout=True).stdout_data

  def UpdateIONodes(self):
    """Updates the input and output nodes of CRAS"""
    server_info = self.DumpServerInfo()
    node_section = 0
    self.input_nodes = []
    self.output_nodes = []

    for line in server_info.split('\n'):
      if self._RE_END_SECTION.match(line):
        node_section = 0
      if self._RE_INPUT_NODES_SECTION.match(line):
        node_section = 1
      if self._RE_OUTPUT_NOTES_SECTION.match(line):
        node_section = 2

      if self._RE_IO_NODE_LINE.match(line):
        # ID Prio Vol Plugged Time Type Name
        args = line.split()
        if node_section == 1:
          self.input_nodes.append(self.Node(args[0], args[3],
                                            ' '.join(args[5:])))
        elif node_section == 2:
          self.output_nodes.append(self.Node(args[0], args[3],
                                             ' '.join(args[5:])))

  def _SelectNode(self, node, direction):
    """Selects node.

    Args:
      node: The node to select to
      direction: Input or output of the node
    """
    command = [self.CRAS_TEST_CLIENT,
               '--select_input' if direction == CRAS.INPUT
                                else '--select_output',
               node.node_id]
    Spawn(command, call=True)

  def SelectNodeById(self, node_id):
    """Selects node by given id.

    Args:
      node_id: The id of input/output node
    """
    for node in self.input_nodes:
      if node_id == node.node_id:
        self._SelectNode(node, CRAS.INPUT)
        return
    for node in self.output_nodes:
      if node_id == node.node_id:
        self._SelectNode(node, CRAS.OUTPUT)
        return
