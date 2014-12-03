# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Camera utilities."""

# TODO(jchuang): move to py/utils folder.

from __future__ import print_function

import abc
try:
  import cv   # pylint: disable=F0401
  import cv2  # pylint: disable=F0401
except ImportError:
  pass
import glob
import logging
import os
import re

import factory_common  # pylint: disable=W0611
from cros.factory.utils.file_utils import TryUnlink
from cros.factory.utils.process_utils import Spawn


# Paths of mock images.
_MOCK_IMAGE_PATHS = ['fixture', 'camera', 'static']

_MOCK_IMAGE_720P = 'mock_A.jpg'
_MOCK_IMAGE_VGA = 'mock_B.jpg'
_MOCK_IMAGE_QR = 'mock_QR.jpg'


class CameraError(Exception):
  """Camera device exception class."""
  pass


def ReadImageFile(filename):
  """Reads an image file.

  Args:
    filename: Image file name.

  Returns:
    An OpenCV image.

  Raise:
    CameraError on error.
  """
  img = cv2.imread(filename)
  if img is None:
    raise CameraError('Can not open image file %s' % filename)
  return img


class CameraDeviceBase(object):
  """Abstract camera device."""
  __metaclass__ = abc.ABCMeta

  @abc.abstractmethod
  def EnableCamera(self):
    """Enables camera device.

    Raise:
      CameraError on error.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def DisableCamera(self):
    """Disabled camera device.

    Raise:
      CameraError on error.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def ReadSingleFrame(self):
    """Reads a single frame from camera device.

    Returns:
      An OpenCV image.

    Raise:
      CameraError on error.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def IsEnabled(self):
    """Checks if the camera device enabled.

    Returns:
      Boolean.
    """
    raise NotImplementedError


class CVCameraDevice(CameraDeviceBase):
  """Camera device via OpenCV V4L2 interface."""

  def __init__(self, device_index, resolution):
    """Constructor.

    Args:
      device_index: Index of video device (-1 for default).
      resolution: Capture resolution.
    """
    super(CVCameraDevice, self).__init__()
    self._device_index = device_index
    self._resolution = resolution
    self._device = None

  def EnableCamera(self):
    if self._device:
      return

    if self._device_index >= 0:
      device_index = self._device_index
    else:
      device_index = self._SearchDevice()

    self._device = cv2.VideoCapture(device_index)
    if not self._device.isOpened():
      raise CameraError('Unable to open video capture interface')
    self._device.set(cv.CV_CAP_PROP_FRAME_WIDTH, self._resolution[0])
    self._device.set(cv.CV_CAP_PROP_FRAME_HEIGHT, self._resolution[1])

  def DisableCamera(self):
    if self._device:
      self._device.release()
      self._device = None

  def ReadSingleFrame(self):
    if not self._device:
      raise CameraError('Try to capture image with camera disabled')
    ret, cv_img = self._device.read()
    if not ret or cv_img is None:
      raise CameraError('Error on capturing. Camera disconnected?')
    return cv_img

  def IsEnabled(self):
    return True if self._device else False

  def _SearchDevice(self):
    """Looks for a camera device to use.

    Returns:
      The device index found.
    """
    # Search for the camera device in sysfs. On some boards OpenCV fails to
    # determine the device index automatically.
    uvc_vid_dirs = glob.glob(
        '/sys/bus/usb/drivers/uvcvideo/*/video4linux/video*')
    if not uvc_vid_dirs:
      raise CameraError('No video capture interface found')
    if len(uvc_vid_dirs) > 1:
      raise CameraError('Multiple video capture interface found')
    return int(re.search(r'video([0-9]+)$', uvc_vid_dirs[0]).group(1))


class MockCameraDevice(CameraDeviceBase):
  """Mocked camera device."""

  def __init__(self, resolution, qr=False):
    """Constructor.

    Args:
      resolution: (width, height) tuple of capture resolution.
      qr: Whether to show QR code.
    """
    super(MockCameraDevice, self).__init__()
    if qr:
      image_name = _MOCK_IMAGE_QR
    elif resolution == (1280, 720):
      image_name = _MOCK_IMAGE_720P
    else:
      image_name = _MOCK_IMAGE_VGA
    paths = _MOCK_IMAGE_PATHS[:]
    paths.append(image_name)
    self._image_path = os.path.join(os.path.dirname(__file__), *paths)
    self._enabled = False

  def EnableCamera(self):
    self._enabled = True

  def DisableCamera(self):
    self._enabled = False

  def ReadSingleFrame(self):
    if not self._enabled:
      raise CameraError('Try to capture image with camera disabled')
    return ReadImageFile(self._image_path)

  def IsEnabled(self):
    return self._enabled


class YavtaCameraDevice(CameraDeviceBase):
  """Captures image with yavta and raw2bmp."""

  _RAW_PATH = '/tmp/yavta_output.raw'
  _BMP_PATH = '/tmp/yavta_output.bmp'

  _BRIGHTNESS_SCALE = 2.0

  def __init__(self, device_index, resolution, controls, postprocess, skip=0):
    """Constructor.

    Args:
      device_index: Index of video device.
      resolution: (width, height) tuple of capture resolution.
      controls: v4l2 controls.
      postprocess: Whether to enhance image.
          (Do not use this for LSC/AWB calibration)
    """
    super(YavtaCameraDevice, self).__init__()
    self._device_index = device_index
    self._resolution = resolution
    self._controls = controls
    self._postprocess = postprocess
    self._skip = skip
    self._enabled = False

  def EnableCamera(self):
    self._enabled = True
    for ctl in self._controls:
      command = ['yavta', '/dev/video%d' % self._device_index, '-w', ctl]
      logging.info(' '.join(command))
      Spawn(command, check_call=True)

  def DisableCamera(self):
    self._enabled = False

  def GetRawImage(self, filename):
    command = ['yavta', '/dev/video%d' % self._device_index,
               '-c%d' % (self._skip + 1), '--skip', str(self._skip), '-n1',
               '-s%dx%d' % self._resolution, '-fSRGGB10', '-F%s' % filename]
    logging.info(' '.join(command))
    Spawn(command, check_call=True)

  def ReadSingleFrame(self):
    def unlink_temp_files():
      TryUnlink(self._RAW_PATH)
      TryUnlink(self._BMP_PATH)

    unlink_temp_files()
    self.GetRawImage(self._RAW_PATH)
    command = ['raw2bmp', self._RAW_PATH, self._BMP_PATH,
               str(self._resolution[0]), str(self._resolution[1]),
               '16', '2']
    logging.info(' '.join(command))
    Spawn(command, check_call=True)
    img = ReadImageFile(self._BMP_PATH)
    if self._postprocess:
      img = img * self._BRIGHTNESS_SCALE
    unlink_temp_files()
    return img

  def IsEnabled(self):
    return self._enabled
