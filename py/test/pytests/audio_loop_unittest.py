#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import textwrap
import unittest
from unittest import mock

from cros.factory.device.audio import base
from cros.factory.test.pytests import audio_loop
from cros.factory.test import test_ui
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


class FakeArgs:

  def __init__(self, **kwargs):
    self.audio_conf = None
    self.initial_actions = None
    self.input_dev = ['input_dev', 'input_dev2']
    self.num_input_channels = 2
    self.output_dev = ['output_dev', 'output_dev2']
    self.num_output_channels = 2
    self.output_volume = None
    self.autostart = False
    self.require_dongle = False
    self.check_dongle = False
    self.check_cras = False
    self.cras_enabled = True
    self.mic_source = base.InputDevices.Extmic
    self.test_title = ''
    self.mic_jack_type = 'nocheck'
    self.audiofuntest_run_delay = None
    self.input_rate = 48000
    self.output_rate = 48000
    self.check_conformance = False
    self.conformance_rate_criteria = 0.1
    self.conformance_rate_err_criteria = 100
    self.tests_to_conduct = []
    self.keep_raw_logs = True
    for k, v in kwargs.items():
      setattr(self, k, v)


INPUT_DEV_INDEX = 0
OUTPUT_DEV_INDEX = 2


def GetCardIndex(dev):
  return {
      'input_dev': INPUT_DEV_INDEX,
      'output_dev': OUTPUT_DEV_INDEX,
  }[dev]


class AudioLoopUnitTest(unittest.TestCase):

  def setUp(self):
    self.test = audio_loop.AudioLoopTest()
    self.test.args = FakeArgs()
    self.ui = mock.create_autospec(test_ui.StandardUI)
    type_utils.LazyProperty.Override(self.test, 'ui', self.ui)
    logging.disable()
    patcher = mock.patch.object(self.test, 'GetAudio', autospec=True)
    self.audio = patcher.start().return_value
    patcher = mock.patch.object(audio_loop.device_utils, 'CreateDUTInterface',
                                autospec=True)
    self.dut = patcher.start().return_value
    patcher = mock.patch.multiple(
        audio_loop.audio_utils, autospec=True,
        GetGenerateSineWavArgs=mock.DEFAULT, GetRoughFreq=mock.DEFAULT,
        GetAudioMaximumDelta=mock.DEFAULT,
        GetAudioMaximumAmplitude=mock.DEFAULT,
        GetAudioMinimumAmplitude=mock.DEFAULT, GetAudioRms=mock.DEFAULT,
        SoxStatOutput=mock.DEFAULT, TrimAudioFile=mock.DEFAULT)
    self.audio_utils = patcher.start()
    mock.patch.object(audio_loop.file_utils, 'UnopenedTemporaryFile',
                      autospec=True).start(
                      ).return_value.__enter__.return_value = 'local_file'

    self.addCleanup(mock.patch.stopall)
    self.audio.GetCardIndexByName.side_effect = GetCardIndex

  def testsetUpLoadConf(self):
    self.test.args.audio_conf = 'conf'

    self.test.setUp()

    self.audio.LoadConfig.assert_called_with('conf')

  def testsetUpInitAction(self):
    self.test.args.initial_actions = [["input_dev", "init_speakerdmic"]]

    self.test.setUp()

    self.audio.ApplyAudioConfig.assert_called_with('init_speakerdmic',
                                                   INPUT_DEV_INDEX)

  def testsetUpInitCard(self):
    self.test.args.initial_actions = [["input_dev", None]]

    self.test.setUp()

    self.audio.Initialize.assert_called_with(INPUT_DEV_INDEX)

  def testsetUpCheckCrasEnabled(self):
    self.test.args = FakeArgs(check_cras=True, cras_enabled=True)
    self.dut.CallOutput.return_value = 'start/running'

    self.test.setUp()

    self.dut.CallOutput.return_value = 'other message'
    self.assertRaises(Exception, self.test.setUp)

  def testsetUpCheckCrasDisabled(self):
    self.test.args = FakeArgs(check_cras=True, cras_enabled=False)
    self.dut.CallOutput.return_value = 'stop/waiting'

    self.test.setUp()

    self.dut.CallOutput.return_value = 'other message'
    self.assertRaises(Exception, self.test.setUp)

  def testCheckDongleStatusPlug(self):
    self.test.args = FakeArgs(check_dongle=True, tests_to_conduct=[{
        'type': 'audiofun'
    }])
    self.audio.GetMicJackStatus.return_value = True
    self.audio.GetHeadphoneJackStatus.return_value = True
    self.test.setUp()

    self.assertRaisesRegex(ValueError,
                           r'Audiofuntest does not require dongle\.',
                           self.test.CheckDongleStatus)
    self.audio.GetMicJackStatus.assert_called_with(INPUT_DEV_INDEX)
    self.audio.GetHeadphoneJackStatus.assert_called_with(OUTPUT_DEV_INDEX)

  def testCheckDongleStatusPlugButNotRequired(self):
    self.test.args = FakeArgs(check_dongle=True, require_dongle=False,
                              tests_to_conduct=[{
                                  'type': 'sinewav'
                              }])
    self.audio.GetMicJackStatus.return_value = True
    self.audio.GetHeadphoneJackStatus.return_value = True
    self.test.setUp()

    self.assertRaisesRegex(ValueError, r'Dongle Status is wrong\.',
                           self.test.CheckDongleStatus)
    self.audio.GetMicJackStatus.assert_called_with(INPUT_DEV_INDEX)
    self.audio.GetHeadphoneJackStatus.assert_called_with(OUTPUT_DEV_INDEX)

  def testCheckDongleStatusUnplug(self):
    self.test.args = FakeArgs(check_dongle=True, require_dongle=True)
    self.test.args.check_dongle = True
    self.test.args.require_dongle = True
    self.audio.GetMicJackStatus.return_value = False
    self.audio.GetHeadphoneJackStatus.return_value = True
    self.test.setUp()

    self.assertRaisesRegex(ValueError, r'Dongle Status is wrong\.',
                           self.test.CheckDongleStatus)
    self.audio.GetMicJackStatus.assert_called_with(INPUT_DEV_INDEX)
    self.audio.GetHeadphoneJackStatus.assert_called_with(OUTPUT_DEV_INDEX)

  def testCheckDongleStatusMicJackType(self):
    self.test.args.mic_jack_type = 'lrgm'
    self.audio.GetMicJackType.return_value = base.MicJackType.lrmg
    self.test.setUp()

    self.assertRaisesRegex(ValueError, r'Mic Jack Type is wrong\.',
                           self.test.CheckDongleStatus)
    self.audio.GetMicJackType.assert_called_with(INPUT_DEV_INDEX)

  def testSetupAudio(self):
    self.test.args = FakeArgs(require_dongle=False,
                              mic_source=base.InputDevices.Extmic)
    self.test.setUp()

    self.test.SetupAudio()

    self.audio.DisableAllAudioOutputs.assert_called_with(OUTPUT_DEV_INDEX)
    self.audio.EnableSpeaker.assert_called_with(OUTPUT_DEV_INDEX)
    self.audio.DisableAllAudioInputs.assert_called_with(INPUT_DEV_INDEX)
    self.audio.EnableDevice.assert_called_with(base.InputDevices.Extmic,
                                               INPUT_DEV_INDEX)

  def testSetupAudioDongle(self):
    self.test.args = FakeArgs(require_dongle=True,
                              mic_source=base.InputDevices.Extmic)
    self.test.setUp()

    self.test.SetupAudio()

    self.audio.DisableAllAudioOutputs.assert_called_with(OUTPUT_DEV_INDEX)
    self.audio.EnableHeadphone.assert_called_with(OUTPUT_DEV_INDEX)
    self.audio.DisableAllAudioInputs.assert_called_with(INPUT_DEV_INDEX)
    self.audio.EnableDevice.assert_called_with(base.InputDevices.Extmic,
                                               INPUT_DEV_INDEX)

  @mock.patch.object(audio_loop.image_tool, 'LSBFile', autospec=True)
  def testCheckConformance(self, mock_lsb):
    mock_lsb.GetChromeOSBoard.return_value = 'test'
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], output_dev=[
        'output_dev', '5'
    ], conformance_rate_criteria=0.2, conformance_rate_err_criteria=90,
                              input_rate=1234, output_rate=4321)
    self.dut.Popen.return_value.communicate.return_value = (
        '0 passed, 0 failed', '')
    self.test.setUp()

    self.test.CheckConformance()

    input_cmd = [
        'alsa_conformance_test.py', '--test-suites', 'test_rates',
        '--rate-criteria-diff-pct', '0.200000', '--rate-err-criteria', '90',
        '--allow-rate', '1234', '-C', f'hw:{INPUT_DEV_INDEX},4'
    ]
    output_cmd = [
        'alsa_conformance_test.py', '--test-suites', 'test_rates',
        '--rate-criteria-diff-pct', '0.200000', '--rate-err-criteria', '90',
        '--allow-rate', '4321', '-P', f'hw:{OUTPUT_DEV_INDEX},5'
    ]
    self.dut.Popen.assert_has_calls([
        mock.call(input_cmd, stdout=process_utils.PIPE,
                  stderr=process_utils.PIPE, log=True),
        mock.call(output_cmd, stdout=process_utils.PIPE,
                  stderr=process_utils.PIPE, log=True)
    ], any_order=True)

  @mock.patch.object(audio_loop.image_tool, 'LSBFile', autospec=True)
  def testCheckConformanceIntelSOF(self, mock_lsb):
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], output_dev=[
        'output_dev', '5'
    ], conformance_rate_criteria=0.2, conformance_rate_err_criteria=90,
                              input_rate=1234, output_rate=4321)
    self.dut.Popen.return_value.communicate.return_value = (
        '0 passed, 0 failed', '')
    self.test.setUp()

    for b in ['brya', 'rex', 'volteer', 'hades']:
      mock_lsb.return_value.GetChromeOSBoard.return_value = b
      self.test.CheckConformance()
      input_cmd = [
          'alsa_conformance_test.py', '--test-suites', 'test_rates',
          '--rate-criteria-diff-pct', '0.200000', '--rate-err-criteria', '90',
          '--allow-rate', '1234', '-C', f'hw:{INPUT_DEV_INDEX},4',
          '--merge-thld-size', '480'
      ]
      output_cmd = [
          'alsa_conformance_test.py', '--test-suites', 'test_rates',
          '--rate-criteria-diff-pct', '0.200000', '--rate-err-criteria', '90',
          '--allow-rate', '4321', '-P', f'hw:{OUTPUT_DEV_INDEX},5',
          '--merge-thld-size', '480'
      ]
      self.dut.Popen.assert_has_calls([
          mock.call(input_cmd, stdout=process_utils.PIPE,
                    stderr=process_utils.PIPE, log=True),
          mock.call(output_cmd, stdout=process_utils.PIPE,
                    stderr=process_utils.PIPE, log=True)
      ], any_order=True)

  @mock.patch.object(audio_loop.image_tool, 'LSBFile', autospec=True)
  def testCheckConformanceUnexpectedOutput(self, mock_lsb):
    mock_lsb.GetChromeOSBoard.return_value = 'test'
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], output_dev=[
        'output_dev', '5'
    ], conformance_rate_criteria=0.2, conformance_rate_err_criteria=90,
                              input_rate=1234, output_rate=4321)
    self.dut.Popen.return_value.communicate.return_value = ('unexpected output',
                                                            '')
    self.test.setUp()

    self.assertRaisesRegex(
        ValueError,
        r'Failed to get expected output from alsa_conformance_test\.py; '
        'Please check parameters with the device info:',
        self.test.CheckConformance)

    input_cmd = [
        'alsa_conformance_test.py', '--test-suites', 'test_rates',
        '--rate-criteria-diff-pct', '0.200000', '--rate-err-criteria', '90',
        '--allow-rate', '1234', '-C', f'hw:{INPUT_DEV_INDEX},4'
    ]
    self.dut.Popen.assert_has_calls([
        mock.call(input_cmd, stdout=process_utils.PIPE, stderr=-1, log=True),
        mock.call([
            'alsa_conformance_test', '--dev_info_only', '-C',
            f'hw:{INPUT_DEV_INDEX},4'
        ], stdout=process_utils.PIPE, stderr=process_utils.PIPE, log=True),
    ], any_order=True)

  def testAudioFunTestWrongChannelCount(self):
    self.test.args = FakeArgs(input_rate=1234, output_rate=4321,
                              num_output_channels=2)
    self.test.setUp()

    self.assertRaisesRegex(ValueError, 'Incorrect number of output channels',
                           self.test.AudioFunTest, {
                               'type': 'audiofun',
                               'input_channels': [0],
                               'output_channels': [3]
                           })

  def testAudioFunTestUnknownEncoding(self):
    self.test.setUp()

    self.assertRaisesRegex(ValueError, 'Unknown audiofuntest encoding',
                           self.test.AudioFunTest, {
                               'type': 'audiofun',
                               'sample_format': 'x16',
                           })

    self.assertRaisesRegex(ValueError, 'Unknown player encoding',
                           self.test.AudioFunTest, {
                               'type': 'audiofun',
                               'player_format': 'x16',
                           })

  @mock.patch.object(audio_loop.session, 'GetCurrentTestPath', autospec=True)
  def testAudioFunTest(self, mock_test_path):
    del mock_test_path  # unused
    self.test.args = FakeArgs(
        input_rate=1234, output_rate=4321, num_output_channels=300,
        input_dev=['input_dev', '4'], output_dev=['output_dev', '5'])
    input_channels = [0, 1]
    self.test.setUp()
    self.dut.path.join.return_value = 'test_path'
    self.dut.Popen.return_value.communicate.side_effect = [
        ('',
         '--played-file-path --recorded-file-path --frequency-sample-strategy'),
        (textwrap.dedent('''\
    carrier
    O: channel =  0, success =   1, fail =   0, rate = 100.0
    X: channel =  1, success =   0, fail =   1, rate = 0.0
    '''), '')
    ]

    self.test.AudioFunTest({
        'type': 'audiofun',
        'input_channels': input_channels,
        'output_channels': [200],
        'iteration': 123,
        'volume_gain': 10,
        'sample_format': 's16',
        'player_format': 'u32',
        'min_frequency': 1000,
        'max_frequency': 4000,
        'input_gain': 20,
        'rms_threshold': 0.1,
        'frequency_sample_strategy': 'pure_random'
    })

    self.ui.CallJSFunction.assert_has_calls([
        mock.call('testInProgress', 'Mic 0: 100.0%, Mic 1: 0.0%'),
        mock.call('testFailResult', 'Mic 0: 100.0%, Mic 1: 0.0%')
    ])
    player_cmd = ('sox -b16 -c300 -esigned -r4321 -traw - -b32 '
                  f'-eunsigned -talsa hw:{OUTPUT_DEV_INDEX},5')
    recorder_cmd = (
        f'sox -talsa hw:{INPUT_DEV_INDEX},4 -b16 -c{len(input_channels)}'
        ' -esigned -r1234 -traw - remix 1 2 gain 20')

    self.dut.Popen.assert_called_with([
        'audiofuntest', '-P', player_cmd, '-R', recorder_cmd, '-t', 's16', '-I',
        '1234', '-O', '4321', '-T', '123', '-a', '200', '-c',
        f'{len(input_channels)}', '-C', '300', '-g', '10', '-i', '1000', '-x',
        '4000', '-p', '0.100000', '--played-file-path', 'test_path',
        '--recorded-file-path', 'test_path', '--frequency-sample-strategy',
        'random'
    ], stdout=process_utils.PIPE, stderr=process_utils.PIPE, log=True)

  @mock.patch.object(audio_loop.AudioLoopTest, 'FailTask', autospec=True)
  def testAudioFunTestNotSupport(self, mock_fail_task):
    self.test.setUp()
    self.dut.Popen.return_value.communicate.return_value = ('', '')

    self.test.AudioFunTest({
        'type': 'audiofun',
        'frequency_sample_strategy': 'pure_random',
    })
    mock_fail_task.assert_called_with(
        self.test, "audiofuntest doesn't support '--frequency-sample-strategy'")

  @mock.patch.object(audio_loop.time, 'time', autospec=True)
  @mock.patch.object(audio_loop.AudioLoopTest, 'RecordAndCheck', autospec=True)
  @mock.patch.object(audio_loop.process_utils, 'Spawn', autospec=True)
  def testSinewavTest(self, mock_process, mock_record, mock_time):
    mock_time.return_value = 123
    self.test.args = FakeArgs(output_volume=100, output_rate=4321,
                              output_dev=['output_dev', '5'])
    self.dut.temp.TempFile.return_value.__enter__.return_value = 'remote_file'
    self.audio_utils['GetGenerateSineWavArgs'].return_value = 'cmd args'
    test_arg = {
        'type': 'sinewav',
        'output_channels': [200],
        'duration': 10
    }
    self.test.setUp()

    self.test.SinewavTest(test_arg)

    self.audio_utils['GetGenerateSineWavArgs'].assert_called_with(
        'local_file', 200, 4321, 1000, 10 + 8)  # 8 is the duration margin.
    mock_process.assert_called_with(['cmd', 'args'], log=True, check_call=True)
    self.dut.link.Push.assert_called_with('local_file', 'remote_file')
    self.audio.PlaybackWavFile.assert_called_with(
        'remote_file', OUTPUT_DEV_INDEX, '5', blocking=False)
    mock_record.assert_called_with(self.test, test_arg,
                                   '/tmp/record-100-200-123.raw')
    self.audio.StopPlaybackWavFile.assert_called_once()

  @mock.patch.object(audio_loop.time, 'time', autospec=True)
  @mock.patch.object(audio_loop.AudioLoopTest, 'RecordAndCheck', autospec=True)
  def testNoiseTest(self, mock_record, mock_time):
    mock_time.return_value = 123
    test_arg = {
        'type': 'noise',
    }
    self.test.setUp()

    self.test.NoiseTest(test_arg)

    mock_record.assert_called_with(self.test, test_arg, '/tmp/noise-123.wav')

  def testRecordAndCheck(self):
    self.dut.temp.TempFile.return_value.__enter__.return_value = 'remote_file'
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], input_rate=1234)
    sox_output = mock.Mock()

    self.audio_utils['SoxStatOutput'].return_value = sox_output
    self.audio_utils['GetAudioRms'].return_value = 0.01

    test_arg = {
        'type': 'noise',
        'rms_threshold': [0.08, 0.10],
        'duration': 10
    }
    self.test.setUp()

    self.test.RecordAndCheck(test_arg, 'file_path')

    self.audio.RecordRawFile.assert_called_with('remote_file', INPUT_DEV_INDEX,
                                                '4', 10, 2, 1234)
    self.dut.link.Pull.assert_called_with('remote_file', 'local_file')
    self.audio_utils['TrimAudioFile'].assert_called_with(
        in_path='local_file', out_path='file_path', start=0.5, end=None,
        num_channels=2, sample_rate=1234)
    self.audio_utils['SoxStatOutput'].assert_called_with(
        'file_path', 2, 1, 1234)
    self.audio_utils['GetAudioRms'].assert_called_with(sox_output)

  @mock.patch.object(audio_loop.AudioLoopTest, 'AppendErrorMessage',
                     autospec=True)
  def testRecordAndCheckErrorTooLow(self, mock_error_msg):
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], input_rate=1234)
    sox_output = mock.Mock()
    self.audio_utils['SoxStatOutput'].return_value = sox_output
    self.audio_utils['GetAudioRms'].return_value = 0.01
    self.audio_utils['GetAudioMinimumAmplitude'].return_value = 1
    self.audio_utils['GetAudioMaximumAmplitude'].return_value = 4
    self.audio_utils['GetAudioMaximumDelta'].return_value = 1

    test_arg = {
        'type': 'noise',
        'rms_threshold': [0.08, 0.10],
        'amplitude_threshold': [3, 5],
        'max_delta_threshold': [3, 5]
    }
    self.test.setUp()

    self.test.RecordAndCheck(test_arg, 'file_path')

    mock_error_msg.assert_has_calls([
        mock.call(
            self.test,
            'Audio RMS value 0.010000 too low. Minimum pass is 0.080000.'),
        mock.call(
            self.test, 'Audio minimum amplitude 1.000000 too low. '
            'Minimum pass is 3.000000.'),
        mock.call(
            self.test,
            'Audio max delta value 1.000000 too low. Minimum pass is 3.000000.'
        ),
    ])

  @mock.patch.object(audio_loop.AudioLoopTest, 'AppendErrorMessage',
                     autospec=True)
  def testRecordAndCheckErrorTooHigh(self, mock_error_msg):
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], input_rate=1234)
    sox_output = mock.Mock()
    self.audio_utils['SoxStatOutput'].return_value = sox_output
    self.audio_utils['GetAudioRms'].return_value = 0.11
    self.audio_utils['GetAudioMinimumAmplitude'].return_value = 4
    self.audio_utils['GetAudioMaximumAmplitude'].return_value = 6
    self.audio_utils['GetAudioMaximumDelta'].return_value = 6

    test_arg = {
        'type': 'noise',
        'rms_threshold': [0.08, 0.10],
        'amplitude_threshold': [3, 5],
        'max_delta_threshold': [3, 5]
    }
    self.test.setUp()

    self.test.RecordAndCheck(test_arg, 'file_path')

    mock_error_msg.assert_has_calls([
        mock.call(
            self.test,
            'Audio RMS value 0.110000 too high. Maximum pass is 0.100000.'),
        mock.call(
            self.test, 'Audio maximum amplitude 6.000000 too high. '
            'Maximum pass is 5.000000.'),
        mock.call(
            self.test,
            'Audio max delta value 6.000000 too high. Minimum pass is 5.000000.'
        ),
    ])

  @mock.patch.object(audio_loop.AudioLoopTest, 'AppendErrorMessage',
                     autospec=True)
  def testRecordAndCheckErrorSinewav(self, mock_error_msg):
    del mock_error_msg  # unused
    self.test.args = FakeArgs(input_dev=['input_dev', '4'], input_rate=1234)
    sox_output = mock.Mock()
    self.audio_utils['SoxStatOutput'].return_value = sox_output
    self.audio_utils['GetRoughFreq'].return_value = 2001

    test_arg = {
        'type': 'sinewav',
        'rms_threshold': [None, None],
        'amplitude_threshold': [None, None],
        'max_delta_threshold': [None, None],
        'freq_threshold': 1000
    }
    self.test.setUp()

    self.test.RecordAndCheck(test_arg, 'file_path')

  def testRunTest(self):
    with mock.patch.multiple(
        self.test,
        autospec=True,
        FailTest=mock.DEFAULT,
        MayPassTest=mock.DEFAULT,
        NoiseTest=mock.DEFAULT,
        SinewavTest=mock.DEFAULT,
        AudioFunTest=mock.DEFAULT,
        CheckConformance=mock.DEFAULT,
        SetupAudio=mock.DEFAULT,
        CheckDongleStatus=mock.DEFAULT,
    ) as mock_methods:
      self.test.args = FakeArgs(output_dev=['output_dev', '5'],
                                check_conformance=True)
      audio_test = {
          'type': 'audiofun'
      }
      sinewav_test = {
          'type': 'sinewav'
      }
      noise_test = {
          'type': 'noise'
      }
      self.test.args.tests_to_conduct = [audio_test, sinewav_test, noise_test]
      mock_methods['MayPassTest'].return_value = False
      self.test.setUp()

      self.test.runTest()

      self.ui.WaitKeysOnce.assert_called_with('S')
      mock_methods['CheckDongleStatus'].assert_called_once()
      mock_methods['SetupAudio'].assert_called_once()
      mock_methods['CheckConformance'].assert_called_once()
      mock_methods['AudioFunTest'].assert_called_with(audio_test)
      mock_methods['SinewavTest'].assert_called_with(sinewav_test)
      mock_methods['NoiseTest'].assert_called_with(noise_test)
      mock_methods['FailTest'].assert_called_once()

  @mock.patch.object(audio_loop.AudioLoopTest, 'NoiseTest', autospec=True)
  @mock.patch.object(audio_loop.AudioLoopTest, 'SetupAudio', autospec=True)
  @mock.patch.object(audio_loop.AudioLoopTest, 'CheckDongleStatus',
                     autospec=True)
  def testRunTestAutoStart(self, mock_check_dongle, mock_setup_audio,
                           mock_test):
    del mock_check_dongle, mock_setup_audio, mock_test  # unused
    self.test.args.autostart = True
    self.test.setUp()

    self.test.runTest()

    self.ui.RunJS.assert_called_with('window.template.innerHTML = "";')

  @mock.patch.object(audio_loop.AudioLoopTest, 'NoiseTest', autospec=True)
  def testRunTestOutputVolumeDongle(self, mock_test):
    del mock_test  # unused
    self.test.args = FakeArgs(output_volume=10, require_dongle=True,
                              tests_to_conduct=[{
                                  'type': 'noise'
                              }])
    self.test.setUp()

    self.test.runTest()

    self.audio.SetHeadphoneVolume.assert_called_with(10, OUTPUT_DEV_INDEX)

  @mock.patch.object(audio_loop.AudioLoopTest, 'NoiseTest', autospec=True)
  def testRunTestOutputVolume(self, mock_test):
    del mock_test  # unused
    self.test.args = FakeArgs(output_volume=10, require_dongle=False,
                              tests_to_conduct=[{
                                  'type': 'noise'
                              }])
    self.test.setUp()

    self.test.runTest()

    self.audio.SetSpeakerVolume.assert_called_with(10, OUTPUT_DEV_INDEX)

  def testRunTestUnknownTest(self):
    self.test.args = FakeArgs(tests_to_conduct=[{
        'type': 'unknown'
    }])
    self.test.setUp()

    self.assertRaisesRegex(ValueError, r'Test type "unknown" not supported\.',
                           self.test.runTest)


if __name__ == '__main__':
  unittest.main()
