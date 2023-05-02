# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import time

from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


SERVOD_BIN = 'servod'
DUT_CONTROL_TIMEOUT = 10
SERVOD_INIT_TIMEOUT_SEC = 10
SERVOD_KILL_TIMEOUT_SEC = 3


class _DutControl:
  """An interface for dut-control."""

  def __init__(self, port, check_servod_callback):
    self._base_cmd = ['dut-control', f'--port={port}']
    self._check_servod_callback = check_servod_callback

  def _Execute(self, args):
    self._check_servod_callback()
    return process_utils.CheckOutput(self._base_cmd + args, read_stderr=True,
                                     timeout=DUT_CONTROL_TIMEOUT)

  def GetValue(self, arg):
    """Get the value of |arg| from dut_control."""
    return self._Execute(['--value_only', arg]).strip()

  def Run(self, cmd_fragment):
    """Run a dut_control command.

    Args:
      cmd_fragment (list[str]): The dut_control command to run.
    """
    self._Execute(cmd_fragment)

  def RunAll(self, cmd_fragments):
    """Run multiple dut_control commands in the order given.

    Args:
      cmd_fragments (list[list[str]]): The dut_control commands to run.
    """
    for cmd in cmd_fragments:
      self.Run(cmd)


class Servod:
  """Run servod and get the interface to execute dut-control commands.

  Args:
    port: The port to run servod.
    board: The board argument of servod. The addition board configuration will
    be loaded.
    serial_name: The serial_name argument of servod. It is necessary if there
    are multiple servo connections.
  """

  def __init__(self, port=9999, board=None, serial_name=None):
    self._port = port
    self._servod_cmd = [SERVOD_BIN, '-p', str(port)]
    if board:
      self._servod_cmd += ['-b', board]
    if serial_name:
      self._servod_cmd += ['-s', serial_name]

    self._exit_stack = contextlib.ExitStack()

  @classmethod
  def _CheckServodHasInitialized(cls, dut_control, stdout_file, stderr_file):
    """Wait until servod has initialized.

    If servod has stopped, RuntimeError should be raised.  If servod is
    initializing, dut_control should fail and CalledProcessError should be
    raised.
    """
    last_error = None
    start = time.time()
    while time.time() - start < SERVOD_INIT_TIMEOUT_SEC:
      try:
        dut_control.GetValue('servo_type')
        return
      except process_utils.CalledProcessError as e:
        last_error = e
      except process_utils.TimeoutExpired as e:
        last_error = e
    servod_logs = file_utils.ReadFile(stdout_file), file_utils.ReadFile(
        stderr_file)
    raise RuntimeError(
        f'Cannot initialize servod in {SERVOD_INIT_TIMEOUT_SEC} seconds. '
        f'Last error: {last_error!r}. Servod logs: {servod_logs}')

  def _GetDutControl(self):
    stdout_file = self._exit_stack.enter_context(
        file_utils.UnopenedTemporaryFile())
    stderr_file = self._exit_stack.enter_context(
        file_utils.UnopenedTemporaryFile())

    with open(stdout_file, 'w', encoding='utf8') as stdout, open(
        stderr_file, 'w', encoding='utf8') as stderr:
      servod_process = process_utils.Spawn(self._servod_cmd, stdout=stdout,
                                           stderr=stderr)
    self._exit_stack.callback(process_utils.TerminateOrKillProcess,
                              servod_process, SERVOD_KILL_TIMEOUT_SEC)

    def CheckServodAlive():
      if servod_process.poll() is None:
        return
      servod_logs = file_utils.ReadFile(stdout_file), file_utils.ReadFile(
          stderr_file)
      raise RuntimeError(
          f'Servod unexpectedly stopped. Servod logs: {servod_logs}')

    dut_control = _DutControl(self._port, CheckServodAlive)
    self._CheckServodHasInitialized(dut_control, stdout_file, stderr_file)
    return dut_control

  def __enter__(self):
    self._exit_stack.__enter__()
    try:
      return self._GetDutControl()
    except Exception:
      self._exit_stack.close()
      raise

  def __exit__(self, *args, **kargs):
    self._exit_stack.__exit__(*args, **kargs)
