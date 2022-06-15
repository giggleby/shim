# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Test and check cec power control feature on Chrome OS device.
Description
-----------
# TODO(jimmysun) Add this part

Test Procedure
--------------
# TODO(jimmysun) Add this part

Dependency
----------
# TODO(jimmysun) Add this part

Examples
--------
# TODO(jimmysun) Add this part
"""

from enum import IntEnum
import logging
import re
import subprocess

from cros.factory.device import device_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


_CSS_CEC = """
  #cec-title {
    font-size: 2em;
    width: 70%;
  }
"""
_HTML_CEC = '<div id="cec-title"></div>'
_MSG_CEC_INFO = i18n_test_ui.MakeI18nLabel(
    'This test will control TV display power via HDMI CEC pin.<br>'
    'Display would be turned off and then turned on back')


class Status(IntEnum):
  ERROR = -1
  ON = 0
  OFF = 1
  TO_ON = 2
  TO_OFF = 3


class CecController:
  """Base class for CEC controllers."""

  def __init__(self, dut):
    """Constructor.

    Args:
      dut: the DUT environment object.
    """
    self._dut = dut

  def SetUp(self):
    """Configure the CEC adapter."""
    raise NotImplementedError

  def GetDisplayStatus(self):
    """Return display power status by sending a status request
    and analyze output text.
    @return: display power status:
      -1: connection error
       0: On
       1: Standby
       2: In transition Standby to On
       3: In transition On to Standby
    """
    raise NotImplementedError

  def DisplayTurnOn(self):
    """Turns on the TV."""
    raise NotImplementedError

  def DisplayTurnOff(self):
    """Turns off the TV."""
    raise NotImplementedError


class EcCecController(CecController):
  """Class for EC-based CEC controller."""

  def GetDisplayStatus(self):
    raise NotImplementedError

  def DisplayTurnOn(self):
    raise NotImplementedError

  def DisplayTurnOff(self):
    raise NotImplementedError


class ApCecController(CecController):
  """Class for AP-based CEC controller."""

  def __init__(self, dut, index):
    super().__init__(dut)
    self.index = index

  def SetUp(self):
    self._dut.CheckCall('cec-ctl --playback -S -d %d' % self.index)

  def GetDisplayStatus(self):
    try:
      output = self._dut.CheckOutput(
          'cec-ctl --to 0 --give-device-power-status -s -d %d' % self.index)
    except subprocess.CalledProcessError:
      return Status.ERROR
    logging.info(output)
    match = re.search(r'pwr-state: \w+ \((?P<status>\w+)\)', output)
    if match is None:
      raise RuntimeError('Power status not received.')
    status = int(match['status'], 16)
    if status not in set(Status):
      return Status.ERROR
    return status

  def DisplayTurnOn(self):
    self._dut.CheckCall('cec-ctl --to 0 --image-view-on -s -d %d' % self.index)

  def DisplayTurnOff(self):
    self._dut.CheckCall('cec-ctl --to 0 --standby -s -d %d' % self.index)


class CecTest(test_case.TestCase):
  """ The task to check CEC display power message feature. """
  ARGS = [
      Arg(
          'standby_wait_time', float,
          'Waiting time after standby test to make sure status request could '
          'return correct value. Increase it if needed.', 5.0),
      Arg(
          'image_view_on_wait_time', float,
          'Waiting time after image view on test to make sure status request '
          'could get correct value. Adjust it according to testing machine.',
          10.0),
      Arg('description_wait_time', float,
          'Waiting time for tester to read description.', 2.0),
      Arg('initial_status', int, 'Initial TV status (0 = ON, 1 = OFF).', 0),
      Arg('power_on', bool, 'Test power on command.', True),
      Arg('power_off', bool, 'Test power off command.', True),
      Arg('controller_type', str,
          'The CEC controller type (EC or AP) for the device.', 'AP'),
      Arg('index', int, 'The index of the CEC device', 0)
  ]

  def runTest(self):
    """ This test task check HDMI cec feature. """
    status = self.cec.GetDisplayStatus()
    if status == Status.ERROR:
      raise RuntimeError('The CEC connection is broken.')
    if status != self.args.initial_status:
      raise RuntimeError('The TV is in wrong power state.')
    if self.args.power_off:
      logging.info('Turning off the TV...')
      self.CheckDisplayTurnOff()
    if self.args.power_on:
      logging.info('Turning on the TV...')
      self.CheckDisplayTurnOn()

  def setUp(self):
    """ Initialize cec environment. """
    self.ui.AppendCSS(_CSS_CEC)
    self.ui.SetState(_HTML_CEC)
    self.ui.SetHTML(_MSG_CEC_INFO, id='cec-title')
    self.Sleep(self.args.description_wait_time)

    self._dut = device_utils.CreateDUTInterface()
    if self.args.controller_type == 'EC':
      self.cec = EcCecController(self._dut)
    elif self.args.controller_type == 'AP':
      self.cec = ApCecController(self._dut, self.args.index)
    else:
      raise ValueError(
          'Controller type %s not supported.' % self.args.controller_type)

    self.cec.SetUp()

  def CheckDisplayTurnOn(self):
    """ Send image_view_on cec message from the device, and check it by another
    status request.
    """
    self.cec.DisplayTurnOn()
    self.Sleep(self.args.image_view_on_wait_time)

    status = self.cec.GetDisplayStatus()
    logging.info('Display status: %d.', status)
    if status in (Status.ON, Status.TO_ON):
      return
    raise RuntimeError('CEC display turn on test failed.')

  def CheckDisplayTurnOff(self):
    """ Send standby cec message from the device to make connected display turn
    off.  And check it via another status request.
    """
    self.cec.DisplayTurnOff()
    self.Sleep(self.args.standby_wait_time)

    status = self.cec.GetDisplayStatus()
    logging.info('Display status: %d.', status)
    if status in (Status.OFF, Status.TO_OFF):
      return
    raise RuntimeError('CEC display stand by test failed.')
