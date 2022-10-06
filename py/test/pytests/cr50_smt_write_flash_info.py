# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Write cr50 flash info in SMT stage.

Description
-----------
There are a few parameters:

1. Is this MLB going to leave current factory, and be assembled in another
   location?  Such as RMA centers or local OEM factories?  This is specified by
   argument `mlb_mode`, default false.
2. Is this an RMA spare board? This is specified by argument `rma_mode`, default
   false.
3. Is this a custom label device?  This is auto detected via `cros_config`.

If `rma_mode=False`, `mlb_mode=False`, and it's not custom label device, this
test does nothing. The cr50 flash info will be set in GRT stage.

Otherwise, `gooftool cr50_smt_write_flash_info` is called. The command falls
back to regular cr50 Board ID setting when the device is not a custom label
device.

Test Procedure
--------------
1. Call `cros_config` to check if current device is a custom label device.
2. Log `is_custom_label` and `custom_label_tag`.
3. If `is_custom_label` or `mlb_mode`, call `gooftool
   cr50_smt_write_flash_info`.

Dependency
----------
- DUT link must be ready.
- Command `cros_config` on DUT.
- Script `cr50-set-board-id.sh` needs to support
  `cr50-set-board-id.sh whitelabel_<pvt|dev>_flags`
- Script `cr50-set-sn-bits.sh` needs to be supported when `enable_zero_touch` is
  set.

Examples
--------
This test is added to SMTEnd test group by default.  If you want to place it at
different timing, add "Cr50WriteCustomLabelFlags" test item to your test group.

If you are manufacturing MLBs for RMA parts or LOEM projects, please set test
list constant "mlb_mode" to true.
"""

import functools
import logging

from cros.factory.device import device_utils
from cros.factory.gooftool import common as gooftool_common
from cros.factory.gooftool import cros_config as cros_config_module
from cros.factory.test import test_case
from cros.factory.test.utils import deploy_utils
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg


class Cr50WriteCustomLabelFlags(test_case.TestCase):
  ARGS = [
      Arg('enable_zero_touch', bool, (
          'Enable zero touch enrollment.  This will set the cr50 SN bits using '
          'VPD field attested_device_id.'), default=False),
      Arg('rma_mode', bool,
          ('Whether this MLB is for RMA purpose or not.  Note that currently, '
           'rma_mode=false will override and DISABLE enable_zero_touch.'),
          default=False),
      Arg('mlb_mode', bool,
          ('Whether this MLB will be assembled in a different factory or not. '
           'For example, original ODMs in an LOEM project should set this to '
           'True.'), default=False)
  ]

  def setUp(self):
    # Setups the DUT environments.
    self.dut = device_utils.CreateDUTInterface()
    dut_shell = functools.partial(gooftool_common.Shell, sys_interface=self.dut)
    self.cros_config = cros_config_module.CrosConfig(dut_shell)

  def runTest(self):
    is_custom_label, custom_label_tag = self.cros_config.GetCustomLabelTag()

    testlog.LogParam('is_custom_label', is_custom_label)
    testlog.LogParam('custom_label_tag', custom_label_tag)

    if (not self.args.mlb_mode and not self.args.rma_mode and
        not is_custom_label):
      return

    args = []
    if self.args.enable_zero_touch:
      args.append('--enable_zero_touch')

    if self.args.rma_mode:
      args.append('--rma_mode')

    # cr50_smt_write_flash_info implies mlb_mode, no need to set the argument.

    factory_tools = deploy_utils.CreateFactoryTools(self.dut)
    try:
      factory_tools.CheckCall(['gooftool', 'cr50_smt_write_flash_info', *args])
    except Exception:
      logging.exception('Failed to set cr50 custom label flags.')
      raise
