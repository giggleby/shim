# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a factory test for the audio function. An external loopback dongle
is required to automatically capture and detect the playback tones.

This test supports two test scenarios:
1. Loop from headphone out to headphone in
2. Loop from speaker to digital microphone

Here are two test list examples for two test cases:
OperatorTest(
    id='AudioJack',
    label_zh=u'音源孔',
    pytest_name='audio_loop',
    disable_services=['cras'],
    dargs={'enable_audiofun': False,
           'output_volume': 20,
           'require_dongle': True})

OperatorTest(
    id='SpeakerDMic',
    label_zh=u'喇叭/麦克风',
    pytest_name='audio_loop',
    disable_services=['cras'],
    dargs={'enable_audiofun': True,
           'audiofun_duration_secs': 4,
           'output_volume': 10})
"""
import os
import re
import tempfile
import time
import threading
import unittest

from cros.factory.test.args import Arg
from cros.factory.test import audio_utils
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.utils.process_utils import Spawn, PIPE

# Default setting
_DEFAULT_FREQ_HZ = 1000
_DEFAULT_FREQ_THRESHOLD_HZ = 50
_DEFAULT_SINE_DURATION_SEC = 1

# Pass threshold for audiofuntest
_AUDIOFUNTEST_THRESHOLD = 50.0

# Regular expressions to match audiofuntest message.
_AUDIOFUNTEST_STOP_RE = re.compile('^Stop')
_AUDIOFUNTEST_SUCCESS_RATE_RE = re.compile('.*rate\s*=\s*(.*)$')


class PlaySineThread(threading.Thread):
  """Wraps the execution of arecord in a thread."""
  def __init__(self, channel, odev, freq, seconds):
    threading.Thread.__init__(self)
    self.cmdargs = audio_utils.GetPlaySineArgs(channel, odev, freq,
        seconds)

  def run(self):
    Spawn(self.cmdargs.split(' '), check_call=True)


class AudioLoopTest(unittest.TestCase):
  ARGS = [
    # Common arguments
    Arg('initial_actions', list, 'List of tuple (card, actions)', []),
    Arg('input_dev', str, 'Input ALSA device', 'hw:0,0'),
    Arg('output_dev', str, 'Output ALSA device', 'hw:0,0'),
    Arg('output_volume', int, 'Output Volume', 10),
    Arg('autostart', bool, 'Auto start option', False),
    Arg('require_dongle', bool, 'Require dongle option', False),
    Arg('enable_audiofun', bool, 'Enable audio function test'),
    # Only used for speaker and dmic
    Arg('audiofun_duration_secs', int, 'Duration of audio function test',
        10),
    # Only used for audiojack
    Arg('sine_duration_secs', int, 'Play sine tone duration',
        _DEFAULT_SINE_DURATION_SEC),
  ]

  def setUp(self):
    # We've encountered false positive running audiofuntest tool against
    # audio fun-plug on a few platforms; so it is suggested not to enable
    # both at the same time.
    if (self.args.require_dongle is True and
        self.args.enable_audiofun is True):
      raise ValueError('Audiofuntest does not require dongle.')
    # Initialize frontend parameters
    self._input_device = self.args.input_dev
    self._output_device = self.args.output_dev
    self._output_volume = self.args.output_volume
    self._sine_duration_secs = self.args.sine_duration_secs
    self._audiofun = self.args.enable_audiofun
    self._audiofun_duration_secs = self.args.audiofun_duration_secs

    self._freq = _DEFAULT_FREQ_HZ
    # Used in RunAudioFunTest() or AudioLoopBack() for test result.
    self._test_result = True
    self._test_message = None

    # Get the card index from given I/O device names.
    self._in_card = self.GetCardIndex(self._input_device)
    self._out_card = self.GetCardIndex(self._output_device)

    self._audio_util = audio_utils.AudioUtil()
    for card, action in self.args.initial_actions:
      self._audio_util.ApplyAudioConfig(action, card)

    # Setup HTML UI, and event handler
    self._ui = test_ui.UI()
    self._ui.AddEventHandler('start_run_test', self.StartRunTest)

  def runTest(self):
    # If autostart, JS triggers start_run_test event.
    # Otherwise, it binds start_run_test with 's' key pressed.
    self._ui.CallJSFunction('init', self.args.autostart,
        self.args.require_dongle)
    self._ui.Run()

  def GetCardIndex(self, device):
    """Gets the card index from given device names.

    Args:
      device: ALSA device name
    """
    dev_name_pattern = re.compile(".*?hw:([0-9]+),([0-9]+)")
    match = dev_name_pattern.match(device)
    if match:
      return match.group(1)
    else:
      raise ValueError('device name %s is incorrect' % device)

  def AudioFunTest(self):
    """Runs audiofuntest program to get the frequency from microphone
    immediately.

    Sample audiofuntest message:
    O: carrier = 41, delay = 6, success = 60, fail = 0, rate = 100.0
    Stop play tone
    Stop capturing data
    """
    settings = {'left': self._audio_util.MuteLeftSpeaker,
                'right': self._audio_util.MuteRightSpeaker}
    for channel, func_ptr in settings.items():
      test_result = None
      func_ptr(self._out_card)

      factory.console.info('Run audiofuntest from %r to %r' % (
          self._output_device, self._input_device))
      process = Spawn([audio_utils.AUDIOFUNTEST_PATH,
          '-r', '48000', '-i', self._input_device, '-o', self._output_device,
          '-l', '%d' % self._audiofun_duration_secs], stderr=PIPE)
      last_success_rate = None

      while True:
        proc_output = process.stderr.readline()
        if not proc_output:
          break
        m = _AUDIOFUNTEST_SUCCESS_RATE_RE.match(proc_output)
        if m is not None:
          last_success_rate = float(m.group(1))
          self._ui.CallJSFunction('testInProgress', last_success_rate)

        m = _AUDIOFUNTEST_STOP_RE.match(proc_output)
        if m is not None:
          test_result = (last_success_rate > _AUDIOFUNTEST_THRESHOLD)
          break

      # Unmute channels
      self._audio_util.EnableSpeaker(self._out_card)

      # Show instant message and wait for a while
      if not test_result:
        self._test_result = False
        if last_success_rate is not None:
          self._ui.CallJSFunction('testFailResult', last_success_rate)
          time.sleep(1)
          self._test_message = (
              'For channel %s, The success rate is %.1f, too low!' %
              (channel, last_success_rate))
          factory.console.log(self._test_message)
        else:
          self._test_message = 'audiofuntest terminated unexpectedly'
          factory.console.log(self._test_message)
    self.EndTest()

  def TestLoopbackChannel(self, output_device, noise_file_name, record_command,
      num_channels):
    """Tests loopback on all channels.

    Args:
      output_device: Output devices
      noise_file_name: Name of the file contains pre-recorded noise.
      record_command: A record command used in thread
      num_channels: Number of channels to test
    """
    for channel in xrange(num_channels):
      reduced_file_name = "reduced-%d-%s.wav" % (channel, time.time())
      record_file_name = "record-%d-%s.wav" % (channel, time.time())

      # Play thread has one more second to ensure record process can record
      # entire sine tone
      playsine_thread = PlaySineThread(channel, output_device, self._freq,
          self._sine_duration_secs + 1)
      playsine_thread.start()
      time.sleep(0.5)

      Spawn(record_command + [record_file_name], check_call=True)

      playsine_thread.join()
      sox_output_record = audio_utils.SoxStatOutput(record_file_name, channel)
      rms_val_record = audio_utils.GetAudioRms(sox_output_record)
      factory.console.info('Got recorded audio RMS value of %f.',
          rms_val_record)

      audio_utils.NoiseReduceFile(record_file_name, noise_file_name,
          reduced_file_name)

      sox_output_reduced = audio_utils.SoxStatOutput(reduced_file_name,
          channel)

      os.unlink(reduced_file_name)
      os.unlink(record_file_name)

      self.CheckRecordedAudio(sox_output_reduced)

  def AudioLoopback(self):
    rec_cmd = ['arecord', '-D', self._input_device, '-f', 'dat', '-d',
        str(self._sine_duration_secs)]

    self._ui.CallJSFunction('testInProgress', None)
    # Record a sample of "silence" to use as a noise profile.
    with tempfile.NamedTemporaryFile(delete=False) as noise_file:
      factory.console.info('Noise file: %s' % noise_file.name)
      Spawn(rec_cmd + [noise_file.name], check_call=True)

    # Playback sine tone and check the recorded audio frequency.
    self.TestLoopbackChannel(self._output_device, noise_file.name,
        rec_cmd, audio_utils.DEFAULT_NUM_CHANNELS)
    os.unlink(noise_file.name)

    self.EndTest()

  def CheckRecordedAudio(self, sox_output):
    freq = audio_utils.GetRoughFreq(sox_output)
    if freq is None or (
        abs(freq - self._freq) > _DEFAULT_FREQ_THRESHOLD_HZ):
      self._test_result = False
      self._test_message = 'Test Fail at frequency %r' % freq
      factory.console.info(self._test_message)
    else:
      factory.console.info('Got frequency %d' % freq)

  def EndTest(self):
    if self._test_result:
      self._ui.CallJSFunction('testPassResult')
      time.sleep(0.5)
      self._ui.Pass()
    else:
      self._ui.Fail(self._test_message)

  def StartRunTest(self, event): # pylint: disable=W0613
    if self._audiofun:
      self._audio_util.EnableSpeaker(self._out_card)
      self._audio_util.EnableDmic(self._in_card)
      self._audio_util.SetSpeakerVolume(self._output_volume, self._out_card)
      self._audio_util.DisableHeadphone(self._out_card)
      self._audio_util.DisableExtmic(self._in_card)
      self.AudioFunTest()
    else:
      self._audio_util.DisableSpeaker(self._out_card)
      self._audio_util.DisableDmic(self._in_card)
      self._audio_util.EnableHeadphone(self._out_card)
      self._audio_util.EnableExtmic(self._in_card)
      self._audio_util.SetHeadphoneVolume(self._output_volume, self._out_card)
      self.AudioLoopback()
