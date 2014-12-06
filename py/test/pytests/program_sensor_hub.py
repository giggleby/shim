# -*- coding: utf-8 -*-
#
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Programs sensor hub with stm32mon."""

import logging
import os
import subprocess
import threading
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test.args import Arg
from cros.factory.test.test_ui import Escape, MakeLabel, UI
from cros.factory.test.ui_templates import OneScrollableSection
from cros.factory.utils.process_utils import Spawn, LogAndCheckCall

_TEST_TITLE = MakeLabel('Program Sensor Hub', u'更新传感器集线器韧体')
_CSS = '#state {text-align:left;}'


class UpdateFirmwareTest(unittest.TestCase):
  ARGS = [
    Arg('boot0_gpio', int, 'GPIO number for BOOT0 pin.', optional=False),
    Arg('reset_gpio', int, 'GPIO number for reset pin.', optional=False),
    Arg('i2c_adapter', int, 'I2C adapter number.', optional=False),
    Arg('firmware_path', str, 'Full path of sensor hub firmware.',
        optional=False),
    Arg('reset_only', bool, 'Reset the sensor hub without programming it',
        default=False),
  ]

  def _SensorHubHello(self):
    """Checks if the sensor hub is responsive."""
    try:
      LogAndCheckCall(['ectool', '--name', 'cros_sh', 'hello'])
      return True
    except:
      return False

  def setUp(self):
    self.assertTrue(os.path.isfile(self.args.firmware_path),
                    msg='%s is missing.' % self.args.firmware_path)
    self._ui = UI()
    self._template = OneScrollableSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    self._ui.AppendCSS(_CSS)
    self.boot0_path = '/sys/class/gpio/gpio%d' % self.args.boot0_gpio
    self.reset_path = '/sys/class/gpio/gpio%d' % self.args.reset_gpio

  def ExportGPIO(self):
    """Exports GPIOs that we need."""
    if not os.path.exists(self.boot0_path):
      with open('/sys/class/gpio/export', 'w') as f:
        f.write(str(self.args.boot0_gpio))
    if not os.path.exists(self.reset_path):
      with open('/sys/class/gpio/export', 'w') as f:
        f.write(str(self.args.reset_gpio))

  def ResetSensorHub(self):
    """Resets the sensor hub."""
    with open(os.path.join(self.reset_path, 'direction'), 'w') as f:
      f.write('out')
    # Here we assumes the kernel doesn't invert the signal level.
    with open(os.path.join(self.reset_path, 'value'), 'w') as f:
      f.write('0')
    time.sleep(0.2)
    with open(os.path.join(self.reset_path, 'value'), 'w') as f:
      f.write('1')

  def EnableBootLoader(self):
    """Puts the sensor hub in boot loader mode."""
    self.ExportGPIO()
    with open(os.path.join(self.boot0_path, 'direction'), 'w') as f:
      f.write('out')
    with open(os.path.join(self.boot0_path, 'value'), 'w') as f:
      f.write('1')
    self.ResetSensorHub()

  def DisableBootLoader(self):
    """Restores the sensor hub to normal mode."""
    self.ExportGPIO()
    with open(os.path.join(self.boot0_path, 'direction'), 'w') as f:
      f.write('out')
    with open(os.path.join(self.boot0_path, 'value'), 'w') as f:
      f.write('0')
    self.ResetSensorHub()

  def UpdateFirmware(self):
    """Runs firmware updater.

    While running updater, it shows updater activity on factory UI.
    """
    if not self.args.reset_only:
      self.EnableBootLoader()
      p = Spawn(
          ['stm32mon', '-a', str(self.args.i2c_adapter),
           '-w', self.args.firmware_path],
          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, log=True)
      for line in iter(p.stdout.readline, ''):
        logging.info(line.strip())
        self._template.SetState(Escape(line), append=True)
      if p.poll() != 0:
        self._ui.Fail('Firmware update failed: %d.' % p.returncode)
        return
    self.DisableBootLoader()
    self._template.SetState('Checking Sensor Hub...', append=True)
    if not self._SensorHubHello():
      self._ui.Fail('Failed to talk to sensor hub.')
    self._ui.Pass()

  def runTest(self):
    threading.Thread(target=self.UpdateFirmware).start()
    self._ui.Run()
