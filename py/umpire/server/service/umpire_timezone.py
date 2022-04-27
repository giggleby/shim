# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Chrome OS Factory Timezone Service."""

from cros.factory.umpire.server.service import umpire_service


class UmpireTimezoneService(umpire_service.UmpireService):
  """Umpire Timezone service."""

  def CreateProcesses(self, umpire_config, env):
    del umpire_config  # unused
    del env  # unused
    return ()
