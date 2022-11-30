# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import logging
from typing import Any, Dict, List, Optional

from cros.factory.goofy import goofy_rpc
from cros.factory.goofy.plugins import plugin
from cros.factory.test import state
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


_KEEP_LIST = (
    'edid',
    'id',
    'isInternal',
    'isPrimary',
    'mirroringDestinationIds',
    'mirroringSourceId',
    'name',
)


class MirrorMode(str, enum.Enum):
  off = 'off'
  normal = 'normal'

  def __str__(self):
    return self.value


def HasMirror(server_proxy: goofy_rpc.GoofyRPC):
  display_info = server_proxy.DeviceGetDisplayInfo()
  return any(info['mirroringDestinationIds'] for info in display_info)


class DisplayManager(plugin.Plugin):
  """Goofy Plugin to manage display settings."""

  def __init__(self, goofy, mirror_mode):
    super().__init__(goofy, used_resources=[plugin.RESOURCE.DISPLAY])
    self.mirror_mode = mirror_mode

  @type_utils.Overrides
  def OnStop(self):
    super().OnStop()
    if self.mirror_mode:
      self.SetMirrorMode(MirrorMode.off, timeout=-1)

  @type_utils.Overrides
  def OnStart(self):
    super().OnStart()
    if self.mirror_mode:
      self.SetMirrorMode(MirrorMode.normal, timeout=-1)

  @plugin.RPCFunction
  def SetMirrorMode(self, mode: str, timeout: Optional[int]):
    """Sets mirror mode.

    Args:
      mode: One of value of MirrorMode.
      timeout: maximum number of seconds to wait, None means forever, -1 means
      nonblocking.

    Raises:
      ValueError if mode is not a value of MirrorMode.
    """
    server_proxy: goofy_rpc.GoofyRPC = state.GetInstance()
    # Value type check.
    MirrorMode(mode)
    info = {
        'mode': mode
    }
    err = server_proxy.DeviceSetDisplayMirrorMode(info)
    if err is not None:
      logging.warning('Failed to turn %s the mirror mode: %s', mode, err)
    else:
      logging.info('Turned %s display mirror mode.', mode)

    if timeout == -1:
      return

    def MirrorModeMatchEvent():
      has_mirror = HasMirror(server_proxy)
      return (mode == MirrorMode.off) != has_mirror

    sync_utils.WaitFor(MirrorModeMatchEvent, timeout)

  @plugin.RPCFunction
  def SetMainDisplay(self, display_id: str, timeout: Optional[int]):
    """Sets main display.

    Args:
      display_id: The id of the display. Use ListDisplayInfo to find id.
      timeout: In seconds. -1 means nonblocking.
    """
    server_proxy: goofy_rpc.GoofyRPC = state.GetInstance()
    err = server_proxy.DeviceSetDisplayProperties(display_id,
                                                  {'isPrimary': True})
    if err is not None:
      raise RuntimeError(f'Failed to set the main display: {err}')

    if timeout == -1:
      return

    def BecomePrimaryEvent():
      display_info = server_proxy.DeviceGetDisplayInfo()
      for info in display_info:
        if info['id'] == display_id:
          return info['isPrimary']
      return False

    sync_utils.WaitFor(BecomePrimaryEvent, timeout)

  @plugin.RPCFunction
  def ListDisplayInfo(self, verbose: bool = False):
    """Lists display info.

    Args:
      verbose: Show full information.

    Returns:
      A list of display info.
    """
    server_proxy: goofy_rpc.GoofyRPC = state.GetInstance()
    display_info: List[Dict[str, Any]] = server_proxy.DeviceGetDisplayInfo()
    if not verbose:
      for index, info in enumerate(display_info):
        display_info[index] = {
            key: value
            for key, value in info.items()
            if key in _KEEP_LIST
        }
    return display_info
