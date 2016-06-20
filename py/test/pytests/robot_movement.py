# -*- coding: utf-8 -*-
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Task that uses a robot to move the device."""

import logging
import time
import threading
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test import dut
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.fixture import utils as fixture_utils
from cros.factory.test.ui_templates import OneSection


_TEST_CSS = ('.info {font-size: 2em;}'
             '.warn {font-size: 3em; color: red;}')

_MSG_INIT = test_ui.MakeLabel(
    'Initializing Robot...',
    u'正在初始化机器手臂...',
    'info')

_MSG_LOAD = test_ui.MakeLabel(
    ('Please load DUT onto the robot, connect all cables, '
     'and press <b>SPACE</b> to continue.'),
    u'将DUT放上机器手臂并接上线路后按下<b>空白键</b>开始。',
    'info')

_MSG_PREPARE_MOVEMENT = test_ui.MakeLabel(
    'Prepare for movement.',
    u'准备开始移动。',
    'info')

_MSG_MOVING_TO_START_POSITION = test_ui.MakeLabel(
    'Moving to start position...',
    u'正在移动至起始位置。',
    'info')

_MSG_MOVING_TO_LOAD_POSITION = test_ui.MakeLabel(
    'Moving to LOAD / UNLOAD position...',
    u'正在移动至卸載位置。',
    'info')

_MSG_COMPUTING = test_ui.MakeLabel(
    'Computing...',
    u'校正中...',
    'info')

_MSG_PUSHING_RESULT = test_ui.MakeLabel(
    'Pushing the result...',
    u'储存结果中...',
    'info')


class RobotMovement(unittest.TestCase):
  """A general task that use a robot to move the device.

  Two detail implementation are required for this task. One is the fixture for
  controlling the robot, and the other is the algorithm for computation.

  The process of this task is as following:
  1. Initiate robot and ask operators to load the device.
  2. Prepare DUT to start movement.
  3. Move the robot arm according to the given positions.
  4. After finishing movement, kick off the computation.
  5. Push the results.
  6. Log the files and results.
  """

  ARGS = [
      Arg('robot_fixture', str,
          'The class name of the robot fixture under '
          '``cros.factory.test.fixture``, should '
          'be a subclass of ``cros.factory.test.fixture.imu.robot.Robot``.'
          'E.g. robot.dummy_robot.DummyRobot'),
      Arg('robot_fixture_args', dict,
          'A dict of the args used for the constructor of the robot_fixture.',
          default={}),
      Arg('algorithm', str,
          'The class name of the computering method under '
          '``cros.factory.test.fixture``, should be a subclass of '
          '``cros.factory.test.fixture.robot.algorithm.BaseAlgorithm``.'
          'E.g. robot.dummy_algorithm.DummyAlgorithm'),
      Arg('algorithm_args', dict,
          'A dict of the args used for the constructor of the algorithm.',
          default={}),
      Arg('period_between_movement', (float, int),
          'The pause period between two movements.', default=0.5),
      Arg('period_after_movement', (float, int),
          'The pause period after the final movements.', default=0.0),
      Arg('positions', list,
          'A list of position index for the robot to move.')
      ]

  def setUp(self):
    self._dut = dut.Create()
    self._ui = test_ui.UI()
    self._robot = fixture_utils.CreateFixture(
        self.args.robot_fixture, self.args.robot_fixture_args)
    self._algorithm = fixture_utils.CreateFixture(
        self.args.algorithm, self.args.algorithm_args)

    self._ui.AppendCSS(_TEST_CSS)
    self._template = OneSection(self._ui)

  def tearDown(self):
    try:
      self._robot.SetLED(False)
      self._robot.LoadDevice(False)
      self._robot.SetMotor(False)
    except:  # pylint: disable=bare-except
      pass
    self._robot.Disconnect()

  def WaitForSpace(self):
    """Stop until SPACE is pressed."""

    _event = threading.Event()

    def _Go():
      _event.set()
      self._ui.UnbindKey(' ')

    _event.clear()
    self._ui.BindKey(' ', lambda _unused_arg: _Go())
    _event.wait()

  def Initialize(self):
    """Initializes the robot.

    Intializes robot and move it to the LOAD / UNLOAD position.
    """
    self._template.SetState(_MSG_INIT)
    factory.console.info('Intializing robot.')
    self._robot.Connect()
    self._robot.SetMotor(True)

  def LoadDevice(self):
    """Ask operator to load DUT."""
    self._template.SetState(_MSG_LOAD)
    self._robot.LoadDevice(False)
    factory.console.info('Wait for operators to press SPACE.')
    self.WaitForSpace()
    factory.console.info('SPACE pressed by operator.')
    self._template.SetState(_MSG_PREPARE_MOVEMENT)
    self._robot.LoadDevice(True)

  def StartMoving(self):
    """Starts movement process."""
    self._template.SetState(_MSG_MOVING_TO_START_POSITION)

    factory.console.info('Start to move.')
    self._robot.SetLED(True)
    self._algorithm.OnStartMoving(self._dut)

    for position in self.args.positions:
      factory.console.info('Move to position %d.', position)
      self._robot.MoveTo(position)
      time.sleep(self.args.period_between_movement)

    time.sleep(self.args.period_after_movement)

    self._algorithm.OnStopMoving(self._dut)

    self._template.SetState(_MSG_MOVING_TO_LOAD_POSITION)
    self._robot.SetLED(False)
    # Shutdown and disconnect robot here to avoid robot overload during
    # computing.
    self._robot.LoadDevice(False)
    self._robot.SetMotor(False)
    self._robot.Disconnect()

  def Compute(self):
    """Starts computing after the movement."""
    self._template.SetState(_MSG_COMPUTING)
    factory.console.info('Compute for %s', self._dut.info.serial_number)
    self._algorithm.Compute(self._dut)

  def PushResult(self):
    """Pushes the result to the DUT."""
    self._template.SetState(_MSG_PUSHING_RESULT)
    factory.console.info('Pushing the result.')

    self._algorithm.PullResult(self._dut)

  def runTest(self):
    serial_number = self._dut.info.serial_number
    if not serial_number:
      self.fail('Failed to get the device SN')

    factory.console.info('SN: %s', serial_number)
    logging.info('SN: %s', serial_number)
    self._ui.Run(blocking=False)
    self.Initialize()
    self.LoadDevice()
    self.StartMoving()
    self.Compute()
    self.PushResult()
    # TODO (shunhsingou): log the dataset and parameters to
    # shopfloor.
