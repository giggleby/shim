#!/usr/bin/env python3
#
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import logging
import unittest
from unittest import mock

from cros.factory.device.power import Power
from cros.factory.test.utils import charge_manager


class ChargeManagerTest(unittest.TestCase):

  def setUp(self):
    self._power = mock.Mock(Power)
    # Patch in the ChargeState Enum.
    self._power.ChargeState = Power.ChargeState
    self._charge_manager = charge_manager.ChargeManager(70, 80, self._power)

    patcher = mock.patch('cros.factory.utils.process_utils.CheckCall')
    self._mock_check_call = patcher.start()
    self.addCleanup(patcher.stop)

  def testCharge(self):
    self._power.CheckBatteryPresent.return_value = True
    self._power.CheckACPresent.return_value = True
    self._power.GetChargePct.return_value = 65

    self._charge_manager.AdjustChargeState()

    self._power.CheckBatteryPresent.assert_called_once_with()
    self._power.CheckACPresent.assert_called_once_with()
    self._power.GetChargePct.assert_called_once_with()
    self._power.SetChargeState.assert_called_once_with(
        self._power.ChargeState.CHARGE)

    dps_calls = [
        mock.call(['ectool', 'usbpddps', 'disable']),
        mock.call(['ectool', 'usbpddps', 'enable'])
    ]
    self._mock_check_call.assert_has_calls(dps_calls, any_order=False)

  def testDischarge(self):
    self._power.CheckBatteryPresent.return_value = True
    self._power.CheckACPresent.return_value = True
    self._power.GetChargePct.return_value = 85

    self._charge_manager.AdjustChargeState()

    self._power.CheckBatteryPresent.assert_called_once_with()
    self._power.CheckACPresent.assert_called_once_with()
    self._power.GetChargePct.assert_called_once_with()
    self._power.SetChargeState.assert_called_once_with(
        self._power.ChargeState.DISCHARGE)

  def testStopCharge(self):
    self._power.CheckBatteryPresent.return_value = True
    self._power.CheckACPresent.return_value = True
    self._power.GetChargePct.return_value = 75

    self._charge_manager.AdjustChargeState()

    self._power.CheckBatteryPresent.assert_called_once_with()
    self._power.CheckACPresent.assert_called_once_with()
    self._power.GetChargePct.assert_called_once_with()
    self._power.SetChargeState.assert_called_once_with(
        self._power.ChargeState.IDLE)

  def testNoAC(self):
    self._power.CheckBatteryPresent.return_value = True
    self._power.CheckACPresent.return_value = False

    self._charge_manager.AdjustChargeState()

    self._power.CheckBatteryPresent.assert_called_once_with()
    self._power.CheckACPresent.assert_called_once_with()


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()
