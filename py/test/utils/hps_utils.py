# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""HPS utilities"""

from typing import Optional

from cros.factory.utils import process_utils
from cros.factory.utils import sys_interface


DEFAULT_HPS_FACTORY_PATH = 'hps-factory'
IOTOOLS_PATH = 'iotools'


class HPSDevice:

  def __init__(self, dut: sys_interface.SystemInterface,
               hps_factory_path: Optional[str] = None,
               dev: Optional[str] = None):
    self._dut = dut
    self._hps_factory_path = hps_factory_path or DEFAULT_HPS_FACTORY_PATH
    self._dev = dev

  def RunFactoryProcess(self, timeout_secs):
    cmd = [self._hps_factory_path, '--verbose']
    if self._dev is not None:
      cmd.extend(['--dev', self._dev])
    cmd.append('factory')
    # TODO(cyueh) Add timeout to sys_interface.SystemInterface.Popen
    process_utils.Spawn(cmd, timeout=timeout_secs, log=True, check_call=True)
