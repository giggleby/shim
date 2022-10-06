# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.goofy.plugins import plugin
from cros.factory.utils import type_utils


class MockPlugin(plugin.Plugin):
  @type_utils.Overrides
  def GetUILocation(self):
    return True
