# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test that sets privacy screen to specific state.

Description
-----------
This test measures the functionality of the privacy screen. It sets privacy
screen to a specific state then checks if privacy screen is refreshed to that
state.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

Dependency
----------
- Need a built-in privacy screen.
- Command ``cros-health-tool``.

Examples
--------
Turn privacy screen on and then validate state::

  {
    "pytest_name": "privacy_screen",
    "args": {
      "target_state": "on"
    }
  }

Argument ``target_state`` is required and must be either ``on`` or ``off``.
"""

import json
import logging
from typing import Any, Dict

from cros.factory.device.device_types import CalledProcessError
from cros.factory.device.device_types import DeviceBoard
from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils
from cros.factory.utils.type_utils import Enum
from cros.factory.utils.type_utils import Error


class PrivacyScreenNotSupportedException(Error):
  """Privacy screen is not supported."""


class PrivacyScreenTest(test_case.TestCase):
  """Pytest to measure functionality of built-in privacy screen."""

  _STATE_TYPE = Enum(['on', 'off'])

  ARGS = [
      Arg('target_state', _STATE_TYPE, 'Privacy screen target state.'),
  ]

  dut: DeviceBoard

  def setUp(self):
    self.AddTask(self._RunDiagnosticsRoutine)
    self.dut = device_utils.CreateDUTInterface()

  def _RunDiagnosticsRoutine(self):
    self.ui.SetState(_('Running diagnostics privacy screen routine...'))

    arg_state = f'--set_privacy_screen={self.args.target_state}'
    try:
      process_utils.Spawn([
          'cros-health-tool', 'diag', '--action=run_routine',
          '--routine=privacy_screen', arg_state
      ], check_call=True)

    except CalledProcessError as e:
      current_state = 'on' if self._IsPrivacyScreenOn() else 'off'
      logging.error('Privacy screen routine failed with exit code %d.',
                    e.returncode)
      logging.error('Privacy screen expected state: %s, current state: %s',
                    self.args.target_state, current_state)
      logging.error('Privacy screen routine stderr: %s', e.stderr)

      ui_msg = _(
          'Diagnostics privacy screen routine failed. '
          'Expected state: {expected_state}, current state: {current_state}',
          expected_state=self.args.target_state, current_state=current_state)
      self.ui.SetState(ui_msg)
      raise

    ui_msg = _('Privacy screen state "{state}" verified.',
               state=self.args.target_state)
    self.ui.SetState(ui_msg)

  def _IsPrivacyScreenOn(self) -> bool:
    try:
      stdout: str = self.dut.CheckOutput(
          ['cros-health-tool', 'telem', '--category=display'])
    except CalledProcessError:
      logging.error('Failed to execute cros-health-tool.')
      raise

    try:
      stdout_obj: dict = json.loads(stdout)
    except json.decoder.JSONDecodeError:
      logging.error('Unexpected stdout format from cros-health-tool: %r',
                    stdout)
      raise

    # The stdout_obj is like this:
    #
    # {
    #   "edp": {
    #     "display_height": "170",
    #     "display_width": "310",
    #     "edid_version": "1.4",
    #     "input_type": "Digital",
    #     "manufacture_year": 2021,
    #     "manufacturer": "IVO",
    #     "model_id": 35962,
    #     "privacy_screen_enabled": false,
    #     "privacy_screen_supported": true,
    #     "refresh_rate": 60.00968456004427,
    #     "resolution_horizontal": "1920",
    #     "resolution_vertical": "1080",
    #     "serial_number": "4"
    #   }
    # }

    display_info: Dict[str, Any] = stdout_obj.get('edp', None)
    self.assertIsInstance(
        display_info, dict,
        msg=f'Unexpected stdout format from cros-health-tool:\n{stdout}')

    privacy_screen_supported = display_info.get('privacy_screen_supported',
                                                False)
    self.assertIsInstance(
        privacy_screen_supported, bool,
        msg=f'Unexpected stdout format from cros-health-tool:\n{stdout}')

    if not privacy_screen_supported:
      raise PrivacyScreenNotSupportedException()

    privacy_screen_enabled = display_info.get('privacy_screen_enabled', False)
    self.assertIsInstance(
        privacy_screen_enabled, bool,
        msg=f'Unexpected stdout format from cros-health-tool:\n{stdout}')

    return privacy_screen_enabled
