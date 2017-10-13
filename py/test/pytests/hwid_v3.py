# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Uses HWID v3 to generate, encode, and verify the device's HWID."""

import json
import logging
import os
import unittest
import yaml

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.hwid.v3 import common
from cros.factory.test import factory
from cros.factory.test.i18n import _
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test.rules import phase
from cros.factory.test import shopfloor
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.utils import deploy_utils
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils

# If present,  these files will override the board and probe results
# (for testing).
OVERRIDE_BOARD_PATH = os.path.join(
    common.DEFAULT_HWID_DATA_PATH,
    'OVERRIDE_BOARD')
# OVERRIDE_PROBED_RESULTS should be generated with:
#    `gootool probe --include_vpd`
# to include all the VPD in it.
OVERRIDE_PROBED_RESULTS_PATH = os.path.join(
    common.DEFAULT_HWID_DATA_PATH,
    'OVERRIDE_PROBED_RESULTS')


class HWIDV3Test(unittest.TestCase):
  """A test for generating and verifying HWID v3."""
  ARGS = [
      Arg('generate', bool,
          'Generate and write the HWID (if False, only verify it).',
          True),
      Arg('skip_shopfloor', bool,
          'Set this value to True to skip updating hwid data from shopfloor '
          'server.',
          default=False, optional=True),
      Arg('rma_mode', bool,
          'Enable rma_mode, do not check for deprecated components.',
          default=False, optional=True),
      Arg('verify_checksum', bool,
          'Enable database checksum verification.', default=True, optional=True)
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self.factory_tools = deploy_utils.CreateFactoryTools(self._dut)
    self.tmpdir = self._dut.temp.mktemp(is_dir=True, prefix='hwid_v3')

  def tearDown(self):
    self._dut.Call(['rm', '-rf', self.tmpdir])

  def runTest(self):
    ui = test_ui.UI()
    template = ui_templates.OneSection(ui)

    phase.AssertStartingAtPhase(
        phase.EVT,
        self.args.verify_checksum,
        'HWID checksum must be verified')

    if not self.args.skip_shopfloor:
      shopfloor.update_local_hwid_data(self._dut)

    template.SetState(i18n_test_ui.MakeI18nLabel('Probing components...'))
    # check if we are overriding probed results.
    probed_results_file = self._dut.path.join(self.tmpdir,
                                              'probed_results_file')
    if os.path.exists(OVERRIDE_PROBED_RESULTS_PATH):
      self._dut.SendFile(OVERRIDE_PROBED_RESULTS_PATH, probed_results_file)
      probed_results = file_utils.ReadFile(OVERRIDE_PROBED_RESULTS_PATH)
    else:
      probed_results = self.factory_tools.CallOutput(
          ['gooftool', 'probe', '--include_vpd'])
      self._dut.WriteFile(probed_results_file, probed_results)
    testlog.LogParam(name='probed_results', value=probed_results)

    # check if we are overriding the board name.
    if os.path.exists(OVERRIDE_BOARD_PATH):
      with open(OVERRIDE_BOARD_PATH) as f:
        board = f.read().strip()
      logging.info('overrided board name: %s', board)
    else:
      board = None

    # pass device info to DUT
    device_info_file = self._dut.path.join(self.tmpdir, 'device_info')
    device_info = state.GetAllDeviceData()
    with file_utils.UnopenedTemporaryFile() as f:
      yaml.dump(device_info, open(f, 'w'))
      self._dut.SendFile(f, device_info_file)

    if self.args.generate:
      template.SetState(i18n_test_ui.MakeI18nLabel('Generating HWID (v3)...'))
      generate_cmd = ['hwid', 'generate',
                      '--probed-results-file', probed_results_file,
                      '--device-info-file', device_info_file,
                      '--json-output']
      if board:
        generate_cmd += ['-b', board.upper()]
      if self.args.rma_mode:
        generate_cmd += ['--rma-mode']
      if not self.args.verify_checksum:
        generate_cmd += ['--no-verify-checksum']

      output = self.factory_tools.CallOutput(generate_cmd)
      self.assertIsNotNone(output, 'HWID generate failed.')
      hwid = json.loads(output)

      encoded_string = hwid['encoded_string']
      factory.console.info('Generated HWID: %s', encoded_string)

      # try to decode HWID
      decode_cmd = ['hwid', 'decode'] + (['-b', board] if board else [])
      decode_cmd += [encoded_string]
      decoded_hwid = self.factory_tools.CallOutput(decode_cmd)
      self.assertIsNotNone(decoded_hwid, 'HWID decode failed.')

      logging.info('HWDB checksum: %s', hwid['hwdb_checksum'])

      testlog.LogParam(name='generated_hwid', value=encoded_string)
      testlog.LogParam(name='hwdb_checksum', value=hwid['hwdb_checksum'])
      testlog.LogParam(name='decoded_hwid', value=decoded_hwid)

      state.UpdateDeviceData({'hwid': encoded_string})
    else:
      encoded_string = self.factory_tools.CheckOutput(['hwid', 'read']).strip()

    template.SetState(
        i18n_test_ui.MakeI18nLabel(
            'Verifying HWID (v3): {encoded_string}...',
            encoded_string=(encoded_string or _('(unchanged)'))))

    verify_cmd = ['hwid', 'verify',
                  '--probed-results-file', probed_results_file,
                  '--phase', str(phase.GetPhase())]
    if board:
      verify_cmd += ['-b', board]
    if self.args.rma_mode:
      verify_cmd += ['--rma-mode']
    if not self.args.verify_checksum:
      verify_cmd += ['--no-verify-checksum']
    verify_cmd += [encoded_string]

    output = self.factory_tools.CheckOutput(verify_cmd)
    self.assertTrue('Verification passed.' in output)
    testlog.LogParam(name='verified_hwid', value=encoded_string)

    if self.args.generate:
      template.SetState(
          i18n_test_ui.MakeI18nLabel(
              'Setting HWID (v3): {encoded_string}...',
              encoded_string=encoded_string))
      self.factory_tools.CheckCall(['hwid', 'write', encoded_string])
