# Copyright 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


# DESCRIPTION :
#
# This is a factory test to test the audio.  Operator will test both record and
# playback for headset and built-in audio.  Recordings are played back for
# confirmation.  An additional pre-recorded sample is played to confirm speakers
# operate independently.
# We will test each channel of input and output.


import logging
import os
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test.i18n import arg_utils as i18n_arg_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils

_RECORD_SEC = 3
_RECORD_RATE = 48000
_SOUND_DIRECTORY = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', 'goofy',
    'static', 'sounds')


_MSG_AUDIO_INFO = i18n_test_ui.MakeI18nLabelWithClass(
    "Press 'P' to first play a sample for each channel to ensure audio "
    'output works.<br>'
    "Press 'R' to record {record_sec} seconds, Playback will follow<br>"
    'Press space to mark pass',
    'audio-test-info',
    record_sec=_RECORD_SEC)
_MSG_RECORD_INFO = i18n_test_ui.MakeI18nLabelWithClass('Start recording',
                                                       'audio-test-info')
_HTML_AUDIO = """
<table style="width: 70%%; margin: auto;">
  <tr>
    <td align="center"><div id="audio_title"></div></td>
  </tr>
  <tr>
    <td><hr></td>
  </tr>
  <tr>
    <td><div id="audio_info"></div></td>
  </tr>
  <tr>
    <td><hr></td>
  </tr>
</table>
"""

_CSS_AUDIO = """
  .audio-test-title { font-size: 2em; }
  .audio-test-info { font-size: 2em; }
"""

PLAY_SAMPLE_VALUE = (1 << 0)
RECORD_VALUE = (1 << 1)
PASS_VALUE = (PLAY_SAMPLE_VALUE | RECORD_VALUE)


def GetPlaybackRecordLabel(channel):
  return i18n_test_ui.MakeI18nLabelWithClass(
      'Playback sound (Mic channel {channel})',
      'audio-test-info',
      channel=channel)


def GetPlaybackLabel(channel):
  return i18n_test_ui.MakeI18nLabelWithClass(
      'Playback sound to channel {channel}', 'audio-test-info', channel=channel)


class AudioBasicTest(unittest.TestCase):
  ARGS = [
      i18n_arg_utils.I18nArg(
          'audio_title', 'Label Title of audio test', default=_('Headset')),
      Arg('audio_conf', str, 'Audio config file path', optional=True),
      Arg('initial_actions', list, 'List of tuple (card, actions)', []),
      Arg('input_dev', tuple,
          'Input ALSA device. (card_name, sub_device).'
          'For example: ("audio_card", "0").', ('0', '0')),
      Arg('output_dev', tuple,
          'Output ALSA device. (card_name, sub_device).'
          'For example: ("audio_card", "0").', ('0', '0')),
      Arg('output_channels', int, 'number of output channels.', 2),
      Arg('input_channels', int, 'number of input channels.', 2),
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    if self.args.audio_conf:
      self._dut.audio.LoadConfig(self.args.audio_conf)

    # Tansfer input and output device format
    self._in_card = self._dut.audio.GetCardIndexByName(self.args.input_dev[0])
    self._in_device = self.args.input_dev[1]
    self._out_card = self._dut.audio.GetCardIndexByName(self.args.output_dev[0])
    self._out_device = self.args.output_dev[1]

    # Init audio card before show html
    for card, action in self.args.initial_actions:
      card = self._dut.audio.GetCardIndexByName(card)
      self._dut.audio.ApplyAudioConfig(action, card)

    # Initialize frontend presentation
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS(_CSS_AUDIO)
    self.template.SetState(_HTML_AUDIO)
    self.ui.BindKey('R', self.HandleRecordEvent)
    self.ui.BindKey('P', self.HandleSampleEvent)
    self.ui.BindKey(test_ui.SPACE_KEY, self.MarkPass)

    msg_audio_title = i18n_test_ui.MakeI18nLabelWithClass(
        self.args.audio_title, 'audio-test-info')
    self.ui.SetHTML(msg_audio_title, id='audio_title')
    self.ui.SetHTML(_MSG_AUDIO_INFO, id='audio_info')
    self.current_process = None
    self.key_press = None
    # prevent operator from pressing space directly,
    # make sure they press P and R.
    self.event_value = 0

  def HandleRecordEvent(self, event):
    del event  # Unused.
    if not self.key_press:
      self.key_press = 'R'
      logging.info('start record')
      self.ui.SetHTML(_MSG_RECORD_INFO, id='audio_info')
      dut_record_file_path = self._dut.temp.mktemp(False)
      self._dut.audio.RecordWavFile(dut_record_file_path, self._in_card,
                                    self._in_device, _RECORD_SEC,
                                    self.args.input_channels, _RECORD_RATE)
      logging.info('stop record and start playback')
      # playback the record file by each channel.
      with file_utils.UnopenedTemporaryFile(suffix='.wav') as full_wav_path:
        self._dut.link.Pull(dut_record_file_path, full_wav_path)
        for i in xrange(self.args.input_channels):
          with file_utils.UnopenedTemporaryFile(suffix='.wav') as wav_path:
            # Get channel i from full_wav_path to a stereo wav_path
            # Since most devices support 2 channels.
            process_utils.Spawn(
                ['sox', full_wav_path, wav_path, 'remix', str(i + 1),
                 str(i + 1)], log=True, check_call=True)
            with self._dut.temp.TempFile() as dut_path:
              self._dut.link.Push(wav_path, dut_path)
              self.ui.SetHTML(GetPlaybackRecordLabel(i + 1), id='audio_info')
              self._dut.audio.PlaybackWavFile(dut_path, self._out_card,
                                              self._out_device)
      self._dut.CheckCall(['rm', '-f', dut_record_file_path])
      self.ui.SetHTML(_MSG_AUDIO_INFO, id='audio_info')
      self.key_press = None
      self.event_value |= RECORD_VALUE

  def HandleSampleEvent(self, event):
    del event  # Unused.
    if not self.key_press:
      self.key_press = 'P'
      logging.info('start play sample')
      locale = self.ui.GetUILocale()
      for i in xrange(self.args.output_channels):
        ogg_path = os.path.join(_SOUND_DIRECTORY, locale, '%d.ogg' % (i + 1))
        number_wav_path = '%s.wav' % ogg_path
        process_utils.Spawn(
            ['sox', ogg_path, '-c1', number_wav_path], check_call=True)
        with file_utils.UnopenedTemporaryFile(suffix='.wav') as wav_path:
          # we will only keep (i + 1) channel and mute others.
          # We use number sound to indicate which channel to be played.
          # Create .wav file with n channels but ony has one channel data.
          remix_option = ['0'] * self.args.output_channels
          remix_option[i] = '1'
          process_utils.Spawn(
              ['sox', number_wav_path, wav_path, 'remix'] + remix_option,
              log=True, check_call=True)
          with self._dut.temp.TempFile() as dut_path:
            self._dut.link.Push(wav_path, dut_path)
            self.ui.SetHTML(GetPlaybackLabel(i + 1), id='audio_info')
            self._dut.audio.PlaybackWavFile(dut_path, self._out_card,
                                            self._out_device)
        os.unlink(number_wav_path)
      logging.info('stop play sample')
      self.ui.SetHTML(_MSG_AUDIO_INFO, id='audio_info')
      self.key_press = None
      self.event_value |= PLAY_SAMPLE_VALUE

  def MarkPass(self, event):
    del event  # Unused.
    if self.event_value == PASS_VALUE:
      self.ui.Pass()

  def runTest(self):
    self.ui.Run()
