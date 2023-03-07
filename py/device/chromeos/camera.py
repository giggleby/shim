# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Camera device controller for Chrome OS.

This module provides accessing camera devices.
"""

import enum
import os
import re

from cros.factory.device import camera
from cros.factory.test.utils.camera_utils import CVCameraReader
from cros.factory.test.utils.camera_utils import CameraDevice
from cros.factory.test.utils.camera_utils import CameraError
from cros.factory.test.utils.camera_utils import GetValidCameraPaths


CAMERA_CONFIG_PATH = '/etc/camera/camera_characteristics.conf'


class AllowedFacing(str, enum.Enum):
  front = 'front'
  rear = 'rear'

  def __str__(self):
    return self.value


class ChromeOSCamera(camera.Camera):
  """System module for camera device.

    The default implementation contains only one camera device, which is the
    default camera opened by OpenCV.

    Subclass should override GetCameraDevice(index).
  """

  _index_mapping = {}

  def GetDeviceIndex(self, facing):
    """Search the video device index.

    Since the video device index may change after device reboot/suspend resume,
    we search the video device index using cros_config or from the camera
    characteristics file.

    Args:
      facing: Direction the camera faces relative to device screen. Only allow
              'front', 'rear' or None. None is automatically searching one.
    """
    if facing not in AllowedFacing.__members__ and facing is not None:
      raise CameraError(f'The facing ({facing}) is not in AllowedFacing '
                        f'({list(AllowedFacing.__members__) + [None]})')

    if facing in self._index_mapping:
      return self._index_mapping[facing]

    camera_paths = GetValidCameraPaths(self._device)
    index_to_vid_pid = {}
    for path, index in camera_paths:
      vid = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'idVendor')).strip()
      pid = self._device.ReadFile(
          os.path.join(path, 'device', '..', 'idProduct')).strip()
      index_to_vid_pid[index] = f'{vid}:{pid}'

    num_camera = int(
        self._device.CallOutput(['cros_config', '/camera', 'count']))

    if num_camera == 0:
      raise CameraError('No camera detected')

    camera_facing = self._device.CallOutput(
        ['cros_config', '/camera/devices/0', 'facing'])

    # If camera_facing is empty, it means that the system does not
    # support device query using cros_config.
    if camera_facing:
      self.GetCameraIndexFromCrosConfig(index_to_vid_pid, num_camera)
    else:
      self.GetCameraIndexFromCameraConfig(index_to_vid_pid)

    if facing is None:
      if len(self._index_mapping) > 1:
        raise CameraError('Multiple cameras are found')
      if not self._index_mapping:
        raise CameraError('No camera is found')
      return next(iter(self._index_mapping.values()))

    if facing not in self._index_mapping:
      raise CameraError(f'No {facing} camera is found')
    return self._index_mapping[facing]

  def GetCameraIndexFromCrosConfig(self, index_to_vid_pid, num_camera):
    """ Search the camera index using cros_config.

    Args:
      index_to_vid_pid: store the ids of the vendor and the product.
    """
    vid_pid_to_cros_index = {}
    for cros_index in range(num_camera):
      id_index = 0

      while True:
        vid_pid = self._device.CallOutput([
            'cros_config', f'/camera/devices/{int(cros_index)}/ids',
            f'{int(id_index)}'
        ])

        if not vid_pid:
          break

        if vid_pid in vid_pid_to_cros_index:
          raise CameraError(
              f'Multiple cameras have the same usb_vid_pid ({vid_pid}) There '
              'are duplicated usb_vid_pid in the cros_config file. Please '
              'submit a CL to fix this.')

        vid_pid_to_cros_index[vid_pid] = cros_index
        id_index += 1

    for index, vid_pid in index_to_vid_pid.items():
      if vid_pid in vid_pid_to_cros_index:
        camera_facing = self._device.CallOutput([
            'cros_config',
            f'/camera/devices/{int(vid_pid_to_cros_index[vid_pid])}', 'facing'
        ])
        camera_facing = {
            'front': 'front',
            'back': 'rear'
        }[camera_facing]
        self._index_mapping[camera_facing] = index
      else:
        raise CameraError(
            f'No camera has the usb_vid_pid ({vid_pid}) Please submit a CL to '
            'update the cros_config file.')

  def GetCameraIndexFromCameraConfig(self, index_to_vid_pid):
    """Fallback function when unable to query from cros_config.

    Args:
      index_to_vid_pid: store the ids of the vendor and the product.
    """
    camera_config = self._device.ReadFile(CAMERA_CONFIG_PATH)
    index_to_camera_id = {}
    for index, vid_pid in index_to_vid_pid.items():
      # In CAMERA_CONFIG_PATH, usb_vid_pid hex string could be in uppercase or
      # lowercase, so we make the matching case insensitive.
      camera_id = re.findall(
          r'^camera(\d+)\.module\d+\.usb_vid_pid='
          f'{vid_pid}'
          r'$', camera_config, re.IGNORECASE | re.MULTILINE)
      if len(camera_id) > 1:
        raise CameraError(
            f'Multiple cameras have the same usb_vid_pid ({vid_pid})'
            ' There are duplicated usb_vid_pid in the'
            ' camera_characteristics.conf file. Please submit'
            ' a CL to fix this. See sample CL at https://crrev.com/c/419375')
      if not camera_id:
        raise CameraError(
            f'No camera has the usb_vid_pid ({vid_pid}) Please submit a CL to '
            'update the camera_characteristics.conf file. See sample CL at '
            'https://crrev.com/c/419375')
      camera_id = int(camera_id[0])
      index_to_camera_id[index] = camera_id

    for index, camera_id in index_to_camera_id.items():
      camera_facing = int(
          re.search(r'^camera'
                    f'{camera_id:d}'
                    r'\.lens_facing=(\d+)$', camera_config,
                    re.MULTILINE).group(1))
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
          raise CameraError(f'Found multiple cameras with VID:PID {vid}:{pid}')
        match_index = index
    if match_index == -1:
      raise CameraError(f'Did not find camera with VID:PID {vid}:{pid}')

    return self._devices.setdefault(
        None,
        CameraDevice(dut=self._device, sn_format=None, reader=CVCameraReader(
            match_index, self._device)))
