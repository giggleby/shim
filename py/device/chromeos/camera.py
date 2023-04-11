# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Camera device controller for Chrome OS.

This module provides accessing camera devices.
"""

import os
import re

from cros.factory.device import camera
from cros.factory.test.utils.camera_utils import CVCameraReader
from cros.factory.test.utils.camera_utils import CameraDevice
from cros.factory.test.utils.camera_utils import CameraError
from cros.factory.test.utils.camera_utils import GetValidCameraPaths
from cros.factory.utils import type_utils

CAMERA_CONFIG_PATH = '/etc/camera/camera_characteristics.conf'
ALLOWED_FACING = type_utils.Enum(['front', 'rear', None])


class ChromeOSCamera(camera.Camera):
  """System module for camera device.

    The default implementation contains only one camera device, which is the
    default camera opened by OpenCV.

    Subclass should override GetCameraDevice(index).
  """

  _index_mapping = {}

  def GetDeviceIndex(self, facing):
    """Search the video device index from the camera characteristics file.

    Args:
      facing: Direction the camera faces relative to device screen. Only allow
              'front', 'rear' or None. None is automatically searching one.

    Since the video device index may change after device reboot/suspend resume,
    we search the video device index from the camera characteristics file.
    """
    if facing not in ALLOWED_FACING:
      raise CameraError('The facing (%s) is not in ALLOWED_FACING (%s)' %
                        (facing, ALLOWED_FACING))

    if facing in self._index_mapping:
      return self._index_mapping[facing]

    camera_paths = GetValidCameraPaths(self._device)
    index_to_vid_pid = {}
    for path, index in camera_paths:
      vid = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'idVendor')).strip()
      pid = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'idProduct')).strip()
      index_to_vid_pid[index] = '%s:%s' % (vid, pid)

    num_camera = int(
        self._device.CallOutput(['cros_config', '/camera', 'count']))

    if num_camera == 0:
      raise CameraError('No camera detected')

    self.GetCameraIndexFromCameraConfig(index_to_vid_pid)
    if facing is None:
      if len(self._index_mapping) > 1:
        raise CameraError('Multiple cameras are found')
      if not self._index_mapping:
        raise CameraError('No camera is found')
      return next(iter(self._index_mapping.values()))

    if facing not in self._index_mapping:
      raise CameraError('No %s camera is found' % facing)
    return self._index_mapping[facing]

  def GetCameraIndexFromCameraConfig(self, index_to_vid_pid):
    """Search the video device index from the camera characteristics file.

    Args:
      index_to_vid_pid: store the ids of the vendor and the product.
    """
    camera_config = self._device.ReadFile(CAMERA_CONFIG_PATH)
    index_to_camera_id = {}
    for index, vid_pid in index_to_vid_pid.items():
      # In CAMERA_CONFIG_PATH, usb_vid_pid hex string could be in uppercase or
      # lowercase, so we make the matching case insensitive.
      camera_id = re.findall(
          r'^camera(\d+)\.module\d+\.usb_vid_pid=%s$' % vid_pid,
          camera_config, re.IGNORECASE | re.MULTILINE)
      if len(camera_id) > 1:
        raise CameraError(
            'Multiple cameras have the same usb_vid_pid (%s)'
            ' There are duplicated usb_vid_pid in the'
            ' camera_characteristics.conf file. Please submit'
            ' a CL to fix this. See sample CL at https://crrev.com/c/419375' %
            vid_pid)
      if not camera_id:
        raise CameraError(
            'No camera has the usb_vid_pid (%s)'
            ' Please submit a CL to update the camera_characteristics.conf'
            ' file. See sample CL at https://crrev.com/c/419375' % vid_pid)
      camera_id = int(camera_id[0])
      index_to_camera_id[index] = camera_id

    for index, camera_id in index_to_camera_id.items():
      camera_facing = int(re.search(
          r'^camera%d\.lens_facing=(\d+)$' % camera_id,
          camera_config, re.MULTILINE).group(1))
      camera_facing = {
          0: 'front',
          1: 'rear'
      }[camera_facing]
      self._index_mapping[camera_facing] = index

  # pylint: disable=arguments-renamed
  def GetCameraDevice(self, facing):
    """Get the camera device of the given direction the camera faces.

    Args:
      facing: Direction the camera faces relative to device screen. Only allowed
              'front', 'rear' or None. None is automatically searching one.

    Returns:
      Camera device object that implements
      cros.factory.test.utils.camera_utils.CameraDevice.
    """
    device_index = self.GetDeviceIndex(facing)
    return self._devices.setdefault(facing, CameraDevice(
        dut=self._device, sn_format=None,
        reader=CVCameraReader(device_index, self._device)))

  def GetCameraDeviceByUsbVidPid(self, vid, pid):
    """Get the camera device with the given USB vendor and device id.

    Args:
      vid: The USB vendor id of the external video device to open.
      pid: The USB product id of the external video device to open.

    Returns:
      Camera device object that implements
      cros.factory.test.utils.camera_utils.CameraDevice.
    """
    camera_paths = GetValidCameraPaths(self._device)
    match_index = -1
    for path, index in camera_paths:
      dev_removable = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'removable')).strip()
      dev_vid = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'idVendor')).strip()
      dev_pid = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'idProduct')).strip()
      if (dev_removable != 'fixed' and vid.lower() == dev_vid and
          pid.lower() == dev_pid):
        if match_index != -1:
          raise CameraError(
              'Found multiple cameras with VID:PID %s:%s' % (vid, pid))
        match_index = index
    if match_index == -1:
      raise CameraError('Did not find camera with VID:PID %s:%s' % (vid, pid))

    return self._devices.setdefault(
        None,
        CameraDevice(dut=self._device, sn_format=None, reader=CVCameraReader(
            match_index, self._device)))
