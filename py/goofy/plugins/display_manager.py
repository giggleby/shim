# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from cros.factory.goofy.plugins import plugin
from cros.factory.test import state
from cros.factory.utils import type_utils


class DisplayManager(plugin.Plugin):
  """Goofy Plugin to manage display settings."""

  def __init__(self, goofy, mirror_mode):
    super().__init__(goofy, used_resources=[plugin.Resource.DISPLAY])
    self.mirror_mode = mirror_mode

  @type_utils.Overrides
  def OnStop(self):
    super().OnStop()
    if self.mirror_mode:
      err = state.GetInstance().DeviceSetDisplayMirrorMode({'mode': 'off'})
      if err is not None:
        logging.warning('Failed to turn off the mirror mode: %s', err)
      else:
        logging.info('Turned off display mirror mode.')

  @type_utils.Overrides
  def OnStart(self):
    super().OnStart()
    if self.mirror_mode:
      err = state.GetInstance().DeviceSetDisplayMirrorMode({'mode': 'normal'})
      if err is not None:
        logging.warning('Failed to turn on the mirror mode: %s', err)
      else:
        logging.info('Turned on display mirror mode.')
