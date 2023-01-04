# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A plugin that controls the camera.

This plugin is used to control the camera. User should use the command
line interface under `py/tools/camera_manager.py` to interact with the plugin.

Examples
--------
To start the plugin and set the default arguments, add this to
`goofy_plugin_chromeos.json`::

  {
    "camera_manager.camera_manager": {}
  }

"""

from cros.factory.goofy.plugins import plugin
from cros.factory.test import event
from cros.factory.utils import type_utils


class CameraManager(plugin.Plugin):
  """A plugin which is used to enable the camera."""

  def _PostEvent(self, facing_mode: str, enable: bool, hidden: bool):
    """Sends `UPDATE_CAMERA_MANAGER` event to goofy."""
    event.PostNewEvent(event.Event.Type.UPDATE_CAMERA_MANAGER,
                       facingMode=facing_mode, enable=enable, hidden=hidden)

  @classmethod
  def MapFacing(cls, camera_facing: str):
    """Maps camera_facing to facing mode.

    Args:
      camera_facing: camera_facing. Must be one of ('front', 'rear').

    Returns:
      The facing mode.
    """
    facing_mode = {
        'front': 'user',
        'rear': 'environment'
    }[camera_facing]
    return facing_mode

  @plugin.RPCFunction
  def EnableCamera(self, camera_facing: str, hidden: bool = False):
    """Enables a camera in Goofy UI.

    Args:
      camera_facing: camera_facing.
      hidden: Set to hide the video.
    """
    self._PostEvent(self.MapFacing(camera_facing), True, hidden)

  @plugin.RPCFunction
  def DisableCamera(self, camera_facing: str):
    """Disables a camera in Goofy UI.

    Args:
      camera_facing: camera_facing.
    """
    self._PostEvent(self.MapFacing(camera_facing), False, True)

  @type_utils.Overrides
  def GetUILocation(self):
    return 'camera'
