#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import unittest
from unittest import mock

from cros.factory.test.pytests import camera
from cros.factory.test.rules import phase
from cros.factory.test import test_ui
from cros.factory.test.utils import camera_utils
from cros.factory.utils import type_utils

from cros.factory.external.py_lib import cv2 as cv
from cros.factory.external.py_lib import numpy as np


class FakeArgs:

  def __init__(self, **kwargs):
    self.mode = 'frame_count'
    self.num_frames_to_pass = 10
    self.process_rate = 5
    self.QR_string = 'hello'
    self.brightness_range = [None, None]
    self.capture_fps = 30
    self.timeout_secs = 20
    self.show_image = True
    self.e2e_mode = True
    self.resize_ratio = 0.4
    self.camera_facing = camera_utils.CameraFacing.front
    self.camera_usb_vid_pid = None
    self.flip_image = None
    self.camera_args = {}
    self.flicker_interval_secs = 0.5
    self.fullscreen = False
    self.video_start_play_timeout_ms = 5000
    self.get_user_media_retries = 0
    self.reinitialization_delay_ms = 5000
    self.min_luminance_ratio = 0.5
    for k, v in kwargs.items():
      setattr(self, k, v)


class FakeCvImage():

  def __init__(self, height=0, width=0):
    self.shape = [height, width]


class CameraUnitTest(unittest.TestCase):

  def setUp(self):
    self.test = camera.CameraTest()
    self.test.args = FakeArgs()
    self.ui = mock.create_autospec(test_ui.StandardUI)
    type_utils.LazyProperty.Override(self.test, 'ui', self.ui)
    logging.disable()
    patcher = mock.patch.object(self.test, 'GetCamera', autospec=True)
    self.camera = patcher.start().return_value
    patcher = mock.patch.object(camera.device_utils, 'CreateDUTInterface',
                                autospec=True)
    self.dut = patcher.start().return_value
    patcher = mock.patch.object(camera.camera_utils,
                                'GetCameraTypeFromCameraFacing', autospec=True)
    self.mock_type = patcher.start()
    self.addCleanup(mock.patch.stopall)
    self.time = 0

  def testSetUpMipi(self):
    self.mock_type.return_value = camera_utils.CameraType.mipi
    self.test.args = FakeArgs(e2e_mode=False)

    self.assertRaisesRegex(Exception,
                           r'e2e_mode should be enabled for MIPI camera\.',
                           self.test.setUp)

  def testSetUp_NoFacingAndNoUpVidPid_Fail(self):
    self.test.args = FakeArgs(e2e_mode=False, camera_facing=None)

    # Check if camera_usb_vid_pid and camera_facing are mentioned in the error
    # messages.
    with self.assertRaisesRegex(AssertionError,
                                r'camera_usb_vid_pid.*camera_facing'):
      self.test.setUp()

  def testSetUpVidPid(self):
    self.test.args = FakeArgs(e2e_mode=False, camera_usb_vid_pid=['vid', 'pid'],
                              camera_facing=None)

    self.test.setUp()

    self.assertEqual(self.test.camera_device,
                     self.camera.GetCameraDeviceByUsbVidPid.return_value)
    self.camera.GetCameraDeviceByUsbVidPid.assert_called_with('vid', 'pid')

  def testSetUpFacing(self):
    self.test.args = FakeArgs(e2e_mode=False, camera_usb_vid_pid=None,
                              camera_facing='facing')

    self.test.setUp()

    self.assertEqual(self.test.camera_device,
                     self.camera.GetCameraDevice.return_value)
    self.camera.GetCameraDevice.assert_called_with('facing')

  def testSetUpE2e(self):
    self.test.args = FakeArgs(
        e2e_mode=True, flip_image=True, camera_facing='rear',
        video_start_play_timeout_ms=1, get_user_media_retries=2,
        reinitialization_delay_ms=3, camera_args={'resolution': (100, 200)})

    self.test.setUp()

    self.ui.RunJS.assert_called_with(
        'window.cameraTest = new CameraTest(args.options)', options={
            'facingMode': 'environment',
            'videoStartPlayTimeoutMs': 1,
            'getUserMediaRetries': 2,
            'reinitializationDelayMs': 3,
            'width': 100,
            'height': 200,
            'flipImage': True
        })
    self.assertIsNone(self.test.camera_device)

  def testSetUpE2eNotLocal(self):
    self.test.args = FakeArgs(e2e_mode=True)
    self.dut.link.IsLocal.return_value = False

    self.assertRaisesRegex(
        ValueError, r'e2e mode does not work on remote DUT\.', self.test.setUp)

  def testSetUpFullScreen(self):
    self.test.args = FakeArgs(fullscreen=True)

    self.test.setUp()

    self.ui.RunJS.assert_has_calls([mock.call('test.setFullScreen(true)')],
                                   any_order=True)

  @mock.patch.object(camera.phase, 'GetPhase', autospec=True)
  def testRunTestManual(self, mock_phase):
    self.test.args = FakeArgs(mode=camera.TestModes.manual,
                              camera_facing='front')
    self.test.setUp()

    for p in [phase.PVT_DOGFOOD, phase.PVT]:
      mock_phase.return_value = p
      self.assertRaisesRegex(Exception,
                             '"manual" mode cannot be used after DVT',
                             self.test.runTest)

    with mock.patch.object(self.test, 'CaptureTest',
                           autospec=True) as mock_test:
      for p in [phase.PROTO, phase.EVT, phase.DVT]:
        mock_test.reset_mock()
        mock_phase.return_value = p

        self.test.runTest()

        mock_test.assert_called_with(camera.TestModes.manual)

  @mock.patch.object(camera.phase, 'GetPhase', autospec=True)
  def testRunTestShowImage(self, mock_phase):
    mock_phase.return_value = phase.DVT

    for mode in [
        camera.TestModes.manual, camera.TestModes.camera_assemble,
        camera.TestModes.qr, camera.TestModes.camera_assemble_qr,
        camera.TestModes.face
    ]:
      self.test.args = FakeArgs(mode=mode, show_image=False)
      self.test.setUp()

      self.assertRaisesRegex(Exception, 'show_image should be set to true!',
                             self.test.runTest)

  def testRunTestLed(self):
    self.test.args = FakeArgs(mode=camera.TestModes.manual_led,
                              show_image=False)
    self.test.setUp()

    with mock.patch.object(self.test, 'LEDTest', autospec=True) as mock_test:
      self.test.runTest()

      mock_test.assert_called_once()

  def _testLEDTest(self, flicker):
    self.test.setUp()

    with mock.patch.multiple(
        self.test,
        autospec=True,
        EnableDevice=mock.DEFAULT,
        ReadSingleFrame=mock.DEFAULT,
        Sleep=mock.DEFAULT,
        DisableDevice=mock.DEFAULT,
    ) as mock_methods:
      mock_methods['Sleep'].side_effect = [None, TimeoutError]

      self.assertRaises(TimeoutError, self.test.LEDTest)

      mock_methods['EnableDevice'].assert_called()
      mock_methods['ReadSingleFrame'].assert_called()
      if flicker:
        mock_methods['DisableDevice'].assert_called()
        mock_methods['Sleep'].assert_called_with(
            self.test.args.flicker_interval_secs)
      else:
        mock_methods['DisableDevice'].assert_not_called()
        mock_methods['Sleep'].assert_called_with(0.5)

  @mock.patch.object(camera.random, 'randint', autospec=True)
  def testLEDTestFlicker(self, mock_rand):
    self.test.args = FakeArgs(flicker_interval_secs=2)
    mock_rand.return_value = 1
    self._testLEDTest(True)

  @mock.patch.object(camera.random, 'randint', autospec=True)
  def testLEDTestLit(self, mock_rand):
    mock_rand.return_value = 0
    self._testLEDTest(False)

  def _testCaptureFrame(self, show_image):
    # The function CaptureTest in camera.py reads a frame <capture_fps> times
    # for each second, and check the frame <process_rate> times for each
    # second. So there will be about <capture_fps> / <process_rate> loops to
    # get a valid frame.
    process_rate = 3
    num_frames_to_pass = 2
    capture_fps = 6
    self.test.args = FakeArgs(show_image=show_image, process_rate=process_rate,
                              num_frames_to_pass=num_frames_to_pass,
                              capture_fps=capture_fps)
    self.test.setUp()
    self._SetupTimeUtils()

    with mock.patch.multiple(
        self.test,
        autospec=True,
        EnableDevice=mock.DEFAULT,
        ReadSingleFrame=mock.DEFAULT,
        CaptureTestFrame=mock.DEFAULT,
        ShowImage=mock.DEFAULT,
        DisableDevice=mock.DEFAULT,
    ) as mock_methods:
      self.test.CaptureTest(camera.TestModes.manual)

      mock_methods['EnableDevice'].assert_called_once()
      if show_image:
        self.assertGreaterEqual(mock_methods['ShowImage'].call_count,
                                capture_fps / process_rate * num_frames_to_pass)
      else:
        mock_methods['ShowImage'].assert_not_called()
      self.assertGreaterEqual(mock_methods['ReadSingleFrame'].call_count,
                              capture_fps / process_rate * num_frames_to_pass)
      mock_methods['CaptureTestFrame'].assert_has_calls([
          mock.call(camera.TestModes.manual,
                    mock_methods['ReadSingleFrame'].return_value)
      ] * 2, any_order=True)
      mock_methods['DisableDevice'].assert_called_once()

  def testCaptureFrameNotShowImage(self):
    self._testCaptureFrame(False)

  def testCaptureFrameShowImage(self):
    self._testCaptureFrame(True)

  def testCaptureTestFrame(self):
    img = FakeCvImage(1, 1)

    def Action(mode):
      return self.test.CaptureTestFrame(mode, img)

    with mock.patch.multiple(
        self.test, autospec=True, DetectAssemblyIssue=mock.DEFAULT,
        ScanQRCode=mock.DEFAULT, DetectAssemblyIssueAndScanQRCode=mock.DEFAULT,
        DetectFaces=mock.DEFAULT, BrightnessCheck=mock.DEFAULT) as mock_methods:
      self.assertTrue(Action(camera.TestModes.frame_count))

      self.assertEqual(
          Action(camera.TestModes.camera_assemble),
          mock_methods['DetectAssemblyIssue'].return_value)
      mock_methods['DetectAssemblyIssue'].assert_called_with(img)

      self.assertEqual(
          Action(camera.TestModes.qr), mock_methods['ScanQRCode'].return_value)
      mock_methods['ScanQRCode'].assert_called_with(img)

      self.assertEqual(
          Action(camera.TestModes.camera_assemble_qr),
          mock_methods['DetectAssemblyIssueAndScanQRCode'].return_value)
      mock_methods['DetectAssemblyIssueAndScanQRCode'].assert_called_with(img)

      self.assertEqual(
          Action(camera.TestModes.face),
          mock_methods['DetectFaces'].return_value)
      mock_methods['DetectFaces'].assert_called_with(img)

      self.assertEqual(
          Action(camera.TestModes.brightness),
          mock_methods['BrightnessCheck'].return_value)
      mock_methods['BrightnessCheck'].assert_called_with(img)

      self.assertFalse(Action(camera.TestModes.manual))
      self.assertFalse(Action(camera.TestModes.manual_led))
      self.assertFalse(Action(camera.TestModes.timeout))

  @mock.patch.object(camera.cv, 'rectangle', autospec=True)
  @mock.patch.object(camera.camera_assemble, 'GetQRCodeDetectionRegion',
                     autospec=True)
  def testDrawQRDetectionRegion(self, mock_region, mock_rectangle):
    mock_region.return_value = (1, 2, 100, 200)
    img = FakeCvImage(5, 6)
    self.test.args = FakeArgs(e2e_mode=False)
    self.test.setUp()

    self.test.DrawQRDetectionRegion(img)

    mock_region.assert_called_with(5, 6)
    mock_rectangle.assert_called_with(img, (1, 2), (101, 202), 255)

  @mock.patch.object(camera.camera_assemble, 'GetQRCodeDetectionRegion',
                     autospec=True)
  def testDrawQRDetectionRegionE2e(self, mock_region):
    mock_region.return_value = (1, 2, 100, 200)
    img = FakeCvImage(5, 10)
    self.test.args = FakeArgs(e2e_mode=True)
    self.test.setUp()

    with mock.patch.object(self.test, 'RunJSBlocking',
                           autospec=True) as mock_runjs:
      self.test.DrawQRDetectionRegion(img)

      mock_region.assert_called_with(5, 10)
      mock_runjs.assert_has_calls([
          mock.call('cameraTest.clearOverlay()'),
          mock.call(f'cameraTest.drawRect({float(1 / 10)}, '
                    f'{float(2/5)}, {float(100/10)}, {float(200/5)})')
      ])

  @mock.patch.object(camera.codecs, 'encode', autospec=True)
  def testShowImage(self, mock_encode):
    self.test.args = FakeArgs(e2e_mode=False, resize_ratio=0.5, flip_image=True)
    img = FakeCvImage()
    self.test.setUp()
    with mock.patch.multiple(camera.cv, autospec=True, resize=mock.DEFAULT,
                             flip=mock.DEFAULT,
                             imencode=mock.DEFAULT) as mock_methods:
      mock_jpg_data = mock.Mock()
      mock_methods['imencode'].return_value = ('unused', mock_jpg_data)

      self.test.ShowImage(img)

      mock_methods['resize'].assert_called_with(img, None, fx=0.5, fy=0.5,
                                                interpolation=cv.INTER_AREA)
      mock_methods['flip'].assert_called_with(
          mock_methods['resize'].return_value, 1)
      mock_methods['imencode'].assert_called_with(
          '.jpg', mock_methods['flip'].return_value,
          (cv.IMWRITE_JPEG_QUALITY, 70))
      mock_encode.assert_called_with(mock_jpg_data.tobytes.return_value,
                                     'base64')

  @mock.patch.object(camera.cv, 'cvtColor', autospec=True)
  def testBrightnessCheck(self, mock_bright):
    self.test.args = FakeArgs(brightness_range=[10, 20])
    self.test.setUp()
    img = FakeCvImage()

    mock_bright.return_value.max.return_value = 20
    self.assertTrue(self.test.BrightnessCheck(img))

    mock_bright.return_value.max.return_value = 9
    self.assertFalse(self.test.BrightnessCheck(img))

    mock_bright.assert_called_with(img, cv.COLOR_BGR2GRAY)

  @mock.patch.object(camera.barcode, 'ScanQRCode', autospec=True)
  def testScanQRCode(self, mock_scan):
    self.test.args = FakeArgs(QR_string='test')
    img = FakeCvImage()

    mock_scan.return_value = ['test']
    self.assertTrue(self.test.ScanQRCode(img))

    mock_scan.return_value = ['test1']
    self.assertFalse(self.test.ScanQRCode(img))

    mock_scan.return_value = None
    self.assertFalse(self.test.ScanQRCode(img))

    mock_scan.assert_called_with(img)

  @mock.patch.object(camera.cv, 'rectangle', autospec=True)
  @mock.patch.object(camera.camera_assemble, 'DetectCameraAssemblyIssue',
                     autospec=True)
  def testDetectAssemblyIssue(self, mock_issue, mock_draw):
    self.test.args = FakeArgs(min_luminance_ratio=0.1, e2e_mode=False)
    self.mock_type.return_value = camera_utils.CameraType.usb
    too_dark = True
    img = FakeCvImage(20, 20)
    mock_issue.return_value.IsBoundaryRegionTooDark.return_value = (too_dark, [[
        False, False
    ], [True, False]], (10, 10))
    self.test.setUp()

    self.assertEqual(self.test.DetectAssemblyIssue(img), not too_dark)
    mock_draw.assert_called_with(img, (0, 10), (10, 20), (0, 0, 255), -1)
    mock_issue.assert_called_with(img, 0.1)

  @mock.patch.object(camera.camera_assemble, 'DetectCameraAssemblyIssue',
                     autospec=True)
  def testDetectAssemblyIssueE2e(self, mock_issue):
    self.test.args = FakeArgs(e2e_mode=True)
    self.mock_type.return_value = camera_utils.CameraType.usb
    too_dark = True
    img = FakeCvImage(20, 20)
    mock_issue.return_value.IsBoundaryRegionTooDark.return_value = (too_dark, [[
        False, False
    ], [True, False]], (10, 10))
    self.test.setUp()

    with mock.patch.object(self.test, 'RunJSBlocking',
                           autospec=True) as mock_runjs:
      self.assertEqual(self.test.DetectAssemblyIssue(img), not too_dark)

      mock_runjs.assert_called_with(
          'cameraTest.clearOverlay();cameraTest.'
          'drawRect(0.0, 0.5, 0.5, 0.5, "red", true);')

  @mock.patch.object(camera.camera_assemble, 'DetectCameraAssemblyIssue',
                     autospec=True)
  def testDetectAssemblyIssueNotTooDark(self, mock_issue):
    self.test.args = FakeArgs(e2e_mode=False)
    self.mock_type.return_value = camera_utils.CameraType.usb
    too_dark = False
    img = FakeCvImage(20, 20)
    mock_issue.return_value.IsBoundaryRegionTooDark.return_value = (too_dark, [[
        False, False
    ], [True, False]], (10, 10))
    self.test.setUp()

    self.assertEqual(self.test.DetectAssemblyIssue(img), not too_dark)

  @mock.patch.object(camera.cv, 'rectangle', autospec=True)
  @mock.patch.object(camera.cv, 'CascadeClassifier', autospec=True)
  def testDetectFaces(self, mock_cascade, mock_draw):
    self.test.args = FakeArgs(e2e_mode=False)
    img = FakeCvImage(20, 20)
    self.test.setUp()
    mock_cascade.return_value.detectMultiScale.return_value = [(0, 0, 20, 30)]

    self.assertTrue(self.test.DetectFaces(img))
    mock_draw.assert_called_with(img, (0, 0), (20, 30), 255, 1)
    mock_cascade.assert_called_with('/usr/local/share/opencv4/haarcascades/'
                                    'haarcascade_frontalface_default.xml')
    mock_cascade.return_value.detectMultiScale.assert_called_with(
        img, scaleFactor=1.2, minNeighbors=2, flags=1, minSize=(2, 2))

  @mock.patch.object(camera.cv, 'CascadeClassifier', autospec=True)
  def testDetectFacesE2e(self, mock_cascade):
    self.test.args = FakeArgs(e2e_mode=True)
    img = FakeCvImage(20, 20)
    self.test.setUp()
    mock_cascade.return_value.detectMultiScale.return_value = [(0, 0, 20, 30)]

    with mock.patch.object(self.test, 'RunJSBlocking',
                           autospec=True) as mock_runjs:
      self.assertTrue(self.test.DetectFaces(img))
      mock_runjs.assert_called_with(
          'cameraTest.clearOverlay();cameraTest.'
          'drawRect(0.0, 0.0, 1.0, 1.5, "white", false);')
      mock_cascade.assert_called_with('/usr/local/share/opencv4/haarcascades/'
                                      'haarcascade_frontalface_default.xml')
      mock_cascade.return_value.detectMultiScale.assert_called_with(
          img, scaleFactor=1.2, minNeighbors=2, flags=1, minSize=(2, 2))

  @mock.patch.object(camera.cv, 'CascadeClassifier', autospec=True)
  def testDetectFacesNoDetect(self, mock_cascade):
    self.test.args = FakeArgs(e2e_mode=False)
    img = FakeCvImage()
    self.test.setUp()
    mock_cascade.return_value.detectMultiScale.return_value = []

    self.assertFalse(self.test.DetectFaces(img))

  def testEnableDevice(self):
    self.test.args = FakeArgs(e2e_mode=False)
    self.test.setUp()

    self.test.EnableDevice()

    self.test.camera_device.EnableCamera.assert_called_once()

  def testEnableDeviceE2e(self):
    self.test.args = FakeArgs(e2e_mode=True)
    self.test.setUp()

    with mock.patch.object(self.test, 'RunJSPromiseBlocking') as mock_runjs:
      self.test.EnableDevice()

      mock_runjs.assert_called_with('cameraTest.enable()')

  def testDisableDevice(self):
    self.test.args = FakeArgs(e2e_mode=False)
    self.test.setUp()

    self.test.DisableDevice()

    self.test.camera_device.DisableCamera.assert_called_once()

  def testDisableDeviceE2e(self):
    self.test.args = FakeArgs(e2e_mode=True)
    self.test.setUp()

    with mock.patch.object(self.test, 'RunJSBlocking') as mock_runjs:
      self.test.DisableDevice()

      mock_runjs.assert_called_with('cameraTest.disable()')

  def testReadSingleFrame(self):
    self.test.args = FakeArgs(e2e_mode=False)
    self.test.setUp()

    self.assertEqual(self.test.ReadSingleFrame(),
                     self.test.camera_device.ReadSingleFrame.return_value)

    self.test.camera_device.ReadSingleFrame.assert_called_once()

  def testReadSingleFrameE2e(self):
    self.test.args = FakeArgs(e2e_mode=True, need_transmit_from_ui=False)
    self.test.setUp()

    with mock.patch.object(self.test, 'RunJSPromiseBlocking') as mock_runjs:
      self.assertIsNone(self.test.ReadSingleFrame())

      mock_runjs.assert_called_with('cameraTest.grabFrame()')

  @mock.patch.object(camera.np, 'fromstring', autospec=True)
  @mock.patch.object(camera.os, 'unlink', autospec=True)
  @mock.patch.object(camera.file_utils, 'ReadFile', autospec=True)
  @mock.patch.object(camera.codecs, 'decode', autospec=True)
  @mock.patch.object(camera.cv, 'imdecode', autospec=True)
  def testReadSingleFrameE2eTransmit(self, mock_cvdecode, mock_decode,
                                     mock_readfile, mock_unlink, mock_numpy):
    self.test.args = FakeArgs(e2e_mode=True, mode='qr')
    self.test.setUp()

    with mock.patch.object(self.test, 'RunJSPromiseBlocking') as mock_runjs:
      self.test.ReadSingleFrame()

      mock_runjs.assert_called_with('cameraTest.grabFrameAndTransmitBack()')
      mock_readfile.assert_called_with(mock_runjs.return_value, encoding=None)
      mock_decode.assert_called_with(mock_readfile.return_value, 'base64')
      mock_unlink.assert_called_with(mock_runjs.return_value)
      mock_numpy.assert_called_with(mock_decode.return_value, dtype=np.uint8)
      mock_cvdecode.assert_called_with(mock_numpy.return_value, cv.IMREAD_COLOR)

  def _SetupTimeUtils(self):
    self.time = 0

    def FakeTime():
      return self.time

    mock.patch.object(camera.time, 'time', autospec=True,
                      side_effect=FakeTime).start()

    def FakeSleep(time):
      self.time += time

    mock.patch.object(self.test, 'Sleep', autospec=True,
                      side_effect=FakeSleep).start()


if __name__ == '__main__':
  unittest.main()
