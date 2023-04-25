# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is audio utility module to setup amixer related options."""

import re

from cros.factory.utils import process_utils

from cros.factory.external.py_lib import dbus


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

# Tools from platform/audiotest
AUDIOFUNTEST_PATH = 'audiofuntest'
AUDIOLOOP_PATH = 'looptest'
CONFORMANCETEST_PATH = 'alsa_conformance_test.py'
CONFORMANCETOOL_PATH = 'alsa_conformance_test'
SOX_PATH = 'sox'
DEFAULT_NUM_CHANNELS = 2

_DEFAULT_SOX_FORMAT = '-t raw -b 16 -e signed -L'

# SOX related utilities


def GetPlaySineArgs(channel, sample_rate, odev='default', freq=1000,
                    duration_secs=10, sample_size=16):
  """Gets the command args to generate a sine wav to play to odev.

  Args:
    channel: 0 for left, 1 for right; otherwise, mono.
    sample_rate: Sample rate of the audio file.
    odev: ALSA output device.
    freq: Frequency of the generated sine tone.
    duration_secs: Duration of the generated sine tone.
    sample_size: Output audio sample size. Default to 16.

  Returns:
    A command string to generate a sine wav
  """
  cmdargs = [
      SOX_PATH, '-r', f'{int(sample_rate)}', '-b', f'{int(sample_size)}', '-n',
      '-t', 'alsa', odev, 'synth', f'{int(duration_secs)}'
  ]
  if channel == 0:
    cmdargs += ['sine', f'{int(freq)}', 'sine', '0']
  elif channel == 1:
    cmdargs += ['sine', '0', 'sine', f'{int(freq)}']
  else:
    cmdargs += ['sine', f'{int(freq)}']
  return cmdargs


def GetGenerateSineWavArgs(path, channel, sample_rate, freq=1000,
                           duration_secs=10, sample_size=16):
  """Gets the command args to generate a sine .wav file.

  Args:
    path: The generated path of the sine .wav file.
    channel: 0 for left, 1 for right; otherwise, mono.
    sample_rate: Sample rate of the audio file.
    freq: Frequency of the generated sine tone.
    duration_secs: Duration of the generated sine tone.
    sample_size: Output audio sample size. Default to 16.
  """
  cmdargs = (
      f'{SOX_PATH} -r {int(sample_rate)} -b {int(sample_size)} -n {path} synth '
      f'{int(duration_secs)}')
  if channel == 0:
    cmdargs += f' sine {int(freq)} sine 0'
  elif channel == 1:
    cmdargs += f' sine 0 sine {int(freq)}'
  else:
    cmdargs += f' sine {int(freq)}'
  return cmdargs


def TrimAudioFile(in_path, out_path, start, end, num_channels, sample_rate,
                  sox_format=_DEFAULT_SOX_FORMAT):
  """Trims an audio file using sox command.

  Args:
    in_path: Path to the input audio file.
    out_path: Path to the output audio file.
    start: The starting time in seconds of specified range.
    end: The ending time in seconds of specified range.
         Sets to None for the end of audio file.
    num_channels: The number of channels in input file.
    sample_rate: Sample rate of the audio file.
    sox_format: Format to generate sox command.
  """
  cmd = (f'{SOX_PATH} -c {num_channels} -r {sample_rate} {sox_format} {in_path}'
         f' -c {num_channels} -r {sample_rate} {sox_format} {out_path} trim '
         f'{start}')
  if end is not None:
    cmd += str(end)

  process_utils.Spawn(cmd.split(' '), log=True, check_call=True)


def SoxStatOutput(in_file, num_channels, channel, sample_rate,
                  sox_format=_DEFAULT_SOX_FORMAT):
  """Get sox stat from one of the channels.

  Args:
    in_file: Input file name.
    num_channels: Number of channels of the in_file.
    channel: The index of the channel to get the stat. 0-based.
    sample_rate: Sample rate of the audio file.
    sox_format: Format to generate sox command.

  Returns:
    The output of sox stat command.
  """
  # Remix and output to stdout. Note that the channel index is 1-based.
  remix_cmd = (f'{SOX_PATH} -c{num_channels} -r {sample_rate} {sox_format} '
               f'{in_file} -c1 -r {sample_rate} {sox_format} - remix '
               f'{channel + 1}')
  stat_cmd = f'{SOX_PATH} -c1 -r {sample_rate} {sox_format} - -n stat'
  p = process_utils.CommandPipe()
  p.Pipe(remix_cmd.split(' ')).Pipe(stat_cmd.split(' ')).Communicate()
  return p.stderr_data


def GetAudioMinimumAmplitude(sox_output):
  """Gets the audio minimum amplitude from sox stat output

  Args:
    sox_output: Output of sox stat command.

  Returns:
    The minimum amplitude parsed from sox stat output.
  """
  m = re.search(r'^Minimum\s+amplitude:\s+(.+)$', sox_output, re.MULTILINE)
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
  m = re.search(r'^Maximum\s+amplitude:\s+(.+)$', sox_output, re.MULTILINE)
  if m is not None:
    return float(m.group(1))
  return None


def GetAudioMaximumDelta(sox_output):
  """Gets the audio maximum amplitude from sox stat output

  Args:
    sox_output: Output of sox stat command.

  Returns:
    The maximum amplitude parsed from sox stat output.
  """
  m = re.search(r'^Maximum\s+delta:\s+(.+)$', sox_output, re.MULTILINE)
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
  m = re.search(r'^RMS\s+amplitude:\s+(.+)$', sox_output, re.MULTILINE)
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
  _SOX_ROUGH_FREQ_RE = re.compile(r'Rough\s+frequency:\s+(.+)')
  for rms_line in sox_output.split('\n'):
    m = _SOX_ROUGH_FREQ_RE.match(rms_line)
    if m is not None:
      return int(m.group(1))
  return None


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
  output = process_utils.Spawn(['aplay', '-l'], read_stdout=True).stdout_data
  for line in output.split('\n'):
    m = _RE_CARD_INDEX.match(line)
    if m is not None and m.group(2) == card_name:
      return m.group(1)
  raise ValueError(f'device name {card_name} is incorrect')


def GetTotalNumberOfAudioDevices():
  """Get total number of audio devices.

  Returns:
    Total number of audio devices.
  """
  playback_num = int(
      process_utils.SpawnOutput('aplay -l | grep ^card | wc -l', shell=True))
  record_num = int(
      process_utils.SpawnOutput('arecord -l | grep ^card | wc -l', shell=True))
  return playback_num + record_num


class CRAS:
  """Class used to access CRAS information by
  executing commnad cras_test_clinet.
  """
  OUTPUT = 0
  INPUT = 1

  class Node:
    """Class to represent a input or output node in CRAS."""

    def __init__(self, node_id, name, is_active):
      self.node_id = node_id
      self.name = name
      self.is_active = is_active

    def __str__(self):
      return (f'Cras node {self.name}, id={self.node_id}, is_active='
              f'{self.is_active}')

  def __init__(self):
    self.input_nodes = []
    self.output_nodes = []

  def _GetControlInterface(self):
    """Returns an interface to control Cras using DBus API.

    Returns:
      A dbus.Interface object that can control Cras through DBus API.
    """
    bus = dbus.SystemBus()
    cras_object = bus.get_object('org.chromium.cras', '/org/chromium/cras')
    return dbus.Interface(cras_object, 'org.chromium.cras.Control')

  def EnableOutput(self):
    """Enables output by setting system mute and user mute states to False."""
    interface = self._GetControlInterface()
    interface.SetOutputMute(False)
    interface.SetOutputUserMute(False)

  def SetActiveOutputNodeVolume(self, volume):
    """Sets active output node volume.

    Args:
      volume: 0-100 for active output node volume.
    """
    interface = self._GetControlInterface()
    for node in interface.GetNodes():
      if not node['IsInput'] and node['Active']:
        interface.SetOutputNodeVolume(node['Id'], volume)

  def UpdateIONodes(self):
    """Updates the input and output nodes of CRAS"""
    nodes = self._GetControlInterface().GetNodes()
    self.input_nodes = [self.Node(n['Id'], n['Name'], n['Active'])
                        for n in nodes if n['IsInput']]
    self.output_nodes = [self.Node(n['Id'], n['Name'], n['Active'])
                         for n in nodes if not n['IsInput']]

  def SelectNodeById(self, node_id):
    """Selects node by given id.

    Args:
      node_id: The id of input/output node
    """
    interface = self._GetControlInterface()
    for node in self.input_nodes:
      if node_id == node.node_id:
        interface.SetActiveInputNode(node_id)
        return
    for node in self.output_nodes:
      if node_id == node.node_id:
        interface.SetActiveOutputNode(node_id)
        return
