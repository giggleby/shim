# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test and check cec power control feature on Chrome OS device.

Description
-----------
This test checks cec power control feature by turning off and turning on the
display power. Cec power control consists of following functions:
(1) Wake up a monitor.
(2) Put a monitor on standby.
(3) Get the display status of a monitor.

To check if a ChromeOS device support this feature or not:
(1) It depends on the HW design. There is an HDMI CEC pin in the HDMI connector.
(2) CEC function(i.e. ``cec-ctl``) has to be implemented to support it.

In case when a monitor cannot return the power status, we can set
``manual_mode`` to check the power status manually.

Test Procedure
--------------
This is an automated test without user interaction. The HDMI port should be
connected to a CEC-enabled TV.

If ``manual_mode`` is set, the operator has to press the key to indicate the
display status is on. Else the display status is off.

Dependency
----------
- HDMI-CEC support for display control in ChromeOS(cec-ctl)
- The driver of specified button source: GPIO.

Examples
--------
Read system information and power status for the monitor in /dev/cec1 and
verify that it is on::

  {
    "pytest_name": "cec",
    "args": {
      "index": 1,
      "power_on": true
    }
  }

Read system information for the monitor in /dev/cec0 and check power status
manually. Verify that display can be turned on/off via CEC::

  {
    "pytest_name": "cec",
    "args": {
      "manual_mode": true,
      "power_on": true,
      "power_off": true
    }
  }
"""

from enum import IntEnum
import logging
import re
import subprocess

from cros.factory.device import device_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg

_CSS_CEC = """
  #cec-title {
    font-size: 2em;
    width: 70%;
  }
"""
_CSS_CEC_MANUAL = """
  #cec-manual {
    font-size: 1.6em;
    width: 70%;
  }
"""
_HTML_CEC = '<div id="cec-title"></div>'
_HTML_CEC_MANUAL = '<div id="cec-manual"></div>'
_MSG_CEC_INFO = i18n_test_ui.MakeI18nLabel(
    'This test will control TV display power via HDMI CEC pin.<br>'
    'Display would be turned off and then turned on back')
_MSG_CEC_MANUAL_INFO = i18n_test_ui.MakeI18nLabel(
    '<br>Currently in manual mode.<br>Press Enter if display status is ON.'
    '<br>Press Space if display status is OFF')


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
    """Returns the display status of the monitor.

    Gets the display status by sending a status request and analyze output
    text via the CEC controller.

    Returns:
      display power status:
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
      Arg(
          'index', int, 'The index of the CEC device. The CEC device is at '
          '/dev/cec``index``', 0),
      Arg('manual_mode', bool, 'Manually check if power status is on or off.',
          False)
  ]

  def runTest(self):
    """ This test task checks HDMI CEC feature. """
    status = self.GetDisplayStatus()
    if status == Status.ERROR:
      raise RuntimeError('The CEC connection is broken.')
    if status != self.args.initial_status:
      raise RuntimeError(
          f'The TV is in wrong power state. Current status: {status}; '
          f'Expected status: {self.args.initial_status}.')
    if self.args.power_off:
      logging.info('Turning off the TV...')
      self.CheckDisplayTurnOff()
    if self.args.power_on:
      logging.info('Turning on the TV...')
      self.CheckDisplayTurnOn()

  def setUp(self):
    """ Initializes CEC environment. """
    self.ui.AppendCSS(_CSS_CEC)
    self.ui.SetState(_HTML_CEC)
    self.ui.SetHTML(_MSG_CEC_INFO, id='cec-title')
    if self.args.manual_mode:
      self.ui.AppendCSS(_CSS_CEC_MANUAL)
      self.ui.SetState(_HTML_CEC_MANUAL, append=True)
      self.ui.SetHTML(_MSG_CEC_MANUAL_INFO, id='cec-manual')
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
    """ Sends an image_view_on CEC message and checks the display status.

    Turns on the monitor from the device via the CEC controller and checks
    that the display status is Status.ON or Status.TO_ON.

    Returns:
      None.

    Raises:
      RuntimeError if the display status if not Status.ON or Status.TO_ON.
    """
    self.cec.DisplayTurnOn()
    self.Sleep(self.args.image_view_on_wait_time)

    status = self.GetDisplayStatus()
    logging.info('Display status: %s.', status)
    if status in (Status.ON, Status.TO_ON):
      return
    raise RuntimeError('CEC display turn on test failed.')

  def CheckDisplayTurnOff(self):
    """ Sends a sendby CEC message and checks the display status.

    Turns off the monitor from the device via the CEC controller and checks
    that the display status is Status.OFF or Status.TO_OFF.

    Returns:
      None.

    Raises:
      RuntimeError if the display status if not Status.OFF or Status.TO_OFF.
    """
    self.cec.DisplayTurnOff()
    self.Sleep(self.args.standby_wait_time)

    status = self.GetDisplayStatus()
    logging.info('Display status: %s.', status)
    if status in (Status.OFF, Status.TO_OFF):
      return
    raise RuntimeError('CEC display stand by test failed.')

  def GetDisplayStatus(self):
    """ Gets the display status.

    Gets the display status in different mode:
    (1) Manual mode: An operator pressing the keys to send display status.
    (2) Normal mode: CEC controller API.

    Returns:
      A status defined in ``class Status``.
    """
    if self.args.manual_mode:
      key_pressed = self.ui.WaitKeysOnce([test_ui.ENTER_KEY, test_ui.SPACE_KEY])
      return Status.ON if key_pressed == test_ui.ENTER_KEY else Status.OFF
    return self.cec.GetDisplayStatus()
