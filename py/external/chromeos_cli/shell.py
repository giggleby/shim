# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple
from subprocess import PIPE
from typing import Optional

from cros.factory.utils import sys_interface


ShellResult = namedtuple('ShellResult', 'stdout stderr status success')


class Shell:

  def __init__(self, dut: Optional[sys_interface.SystemInterface] = None):
    if dut:
      self._dut = dut
    else:
      self._dut = sys_interface.SystemInterface()

  def __call__(self, cmd, log=True):
    process = self._dut.Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                              encoding='utf-8', log=log)
    stdout, stderr = process.communicate()
    status = process.poll()
    return ShellResult(stdout, stderr, status, status == 0)
