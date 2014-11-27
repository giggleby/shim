# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import print_function

import abc
try:
  import cv   # pylint: disable=F0401
  import cv2  # pylint: disable=F0401
except ImportError:
  pass
import glob
import os
import re

# Paths of mock images.
_MOCK_IMAGE_PATHS = ['fixture', 'camera', 'static']

_MOCK_IMAGE_720P = 'mock_A.jpg'
_MOCK_IMAGE_VGA = 'mock_B.jpg'
_MOCK_IMAGE_QR = 'mock_QR.jpg'


class CameraDeviceError(Exception):
  """Camera device exception class."""
  pass


class CameraDeviceBase(object):
  """Abstract camera device."""
  __metaclass__ = abc.ABCMeta

  @abc.abstractmethod
  def EnableCamera(self):
    """Enables camera device.

    Raise:
      CameraDeviceError on error.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def DisableCamera(self):
    """Disabled camera device.

    Raise:
      CameraDeviceError on error.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def ReadSingleFrame(self):
    """Reads a single frame from camera device.

    Returns:
      An OpenCV image.

    Raise:
      CameraDeviceError on error.
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
      raise CameraDeviceError('Unable to open video capture interface')
    self._device.set(cv.CV_CAP_PROP_FRAME_WIDTH, self._resolution[0])
    self._device.set(cv.CV_CAP_PROP_FRAME_HEIGHT, self._resolution[1])

  def DisableCamera(self):
    if self._device:
      self._device.release()
      self._device = None

  def ReadSingleFrame(self):
    if not self._device:
      raise CameraDeviceError('Try to capture image with camera disabled')
    ret, cv_img = self._device.read()
    if not ret or cv_img is None:
      raise CameraDeviceError('Error on capturing. Camera disconnected?')
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
      raise CameraDeviceError('No video capture interface found')
    if len(uvc_vid_dirs) > 1:
      raise CameraDeviceError('Multiple video capture interface found')
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
      raise CameraDeviceError('Try to capture image with camera disabled')
    img = cv2.imread(self._image_path)
    if img is None:
      raise CameraDeviceError('Can not open mock image %s' % self._image_path)
    return img

  def IsEnabled(self):
    return self._enabled
