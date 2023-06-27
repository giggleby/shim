# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from cros.factory.external.chromeos_cli import shell


class FutilityError(Exception):
  """All exceptions when calling futility."""


class FlashromError(Exception):
  """All exceptions when calling flashrom."""


class Futility:
  """Helper class for cmdline utility of futility and flashrom."""

  def __init__(self, dut=None):
    self._shell = shell.Shell(dut)

  # TODO(jasonchuang) We should use futility instead of using flashrom.
  def GetFlashSize(self):
    """Parses flash size from flashrom."""
    cmd = ['flashrom', '--flash-size']
    res = self._InvokeCommand(cmd, 'Fail to get flash size.').stdout

    try:
      size = int(res.splitlines()[-1])
    except (IndexError, ValueError) as parsing_error:
      raise FlashromError(
          f'Fail to parse the flash size {res}') from parsing_error
    return size

  def GetWriteProtectInfo(self):
    """Parses the start and the length of write protect from futility."""
    res = self._InvokeCommand(['futility', 'flash', '--flash-info'],
                              'Fail to get flash info.').stdout

    wp_conf = re.search(r'\(start = (?P<start>\w+), length = (?P<length>\w+)\)',
                        res)
    if not wp_conf:
      raise FutilityError(f'Fail to parse the wp region {res}')
    return wp_conf

  def _InvokeCommand(self, cmd, failure_msg, cmd_result_checker=None):
    cmd_result_checker = cmd_result_checker or (lambda result: result.success)
    result = self._shell(cmd)
    if not cmd_result_checker(result):
      raise FutilityError(failure_msg + f' (command result: {result!r})')
    return result
