# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time
import subprocess

import factory_common  # pylint: disable=unused-import
from cros.factory.test import test_ui
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils
from cros.factory.utils.arg_utils import Arg

_MSG_CEC_SELF_TEST_INFO = i18n_test_ui.MakeI18nLabel(
    'Please disconnect HDMI, then press SPACE<br>'
    'after one second reconnect HDMI.')

_MSG_CEC_MANUAL_INFO = i18n_test_ui.MakeI18nLabel(
    'The TV will turn off and then on again<br>'
    'Press SPACE to start the test.')

_MSG_CEC_TEST = i18n_test_ui.MakeI18nLabel(
    'Did the TV turn off then on again?<br>'
    'Press SPACE if yes, "F" if no.')

_HTML_CEC = '<div id="cec-title"></div>'

_CSS_CEC = """
  #cec-title {
    font-size: 2em;
    width: 70%;
  }
"""

class DisplayCecTest(test_ui.TestCaseWithUI):
  ARGS = [
      Arg('run_external_display_test',
          bool,
          'Whether to run the full test with external monitor',
          default=False)
  ]

  def setUp(self):
    self.ui.AppendCSS(_CSS_CEC)
    self.template.SetState(_HTML_CEC)

  def runTest(self):
    self.SelfTest()
    if self.args.run_external_display_test:
      self.ExternalDisplayTest()

  def SelfTest(self):
    self.ui.SetHTML(_MSG_CEC_SELF_TEST_INFO, id='cec-title')
    self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    # Check that CEC_IN and CEC_PULL_UP is connected
    self.InvokeGPIO('set', 'CEC_OUT', 1)
    self.InvokeGPIO('set', 'CEC_PULL_UP', 1)
    self.InvokeGPIO('get', 'CEC_IN', 1)
    self.InvokeGPIO('set', 'CEC_PULL_UP', 0)
    self.InvokeGPIO('get', 'CEC_IN', 0)

    # Check that CEC_OUT is connected with the others
    self.InvokeGPIO('set', 'CEC_OUT', 0)
    self.InvokeGPIO('set', 'CEC_PULL_UP', 1)
    self.InvokeGPIO('get', 'CEC_IN', 0)

    # Restore to default settings
    self.InvokeGPIO('set', 'CEC_OUT', 1)
    self.InvokeGPIO('set', 'CEC_PULL_UP', 1)

  def ExternalDisplayTest(self):
    self.ui.SetHTML(_MSG_CEC_MANUAL_INFO, id='cec-title')
    self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    self.Ectool(['cec', 'tv_off'])
    time.sleep(1)
    self.Ectool(['cec', 'status'])
    time.sleep(10)
    self.Ectool(['cec', 'tv_on'])
    time.sleep(1)
    self.Ectool(['cec', 'status'])

    self.ui.SetHTML(_MSG_CEC_TEST, id='cec-title')
    key = self.ui.WaitKeysOnce([test_ui.SPACE_KEY] + ['F'])
    if key == 'F':
      raise type_utils.TestFailure('Failed to send CEC commands')

  def InvokeGPIO(self, direction, pin_name, value):
    """Sets or checks GPIO value using 'ectool'.

    Args:
      direction: 'get' or 'set'
      pin_name: Name of pin used by 'ectool', e.g. CEC_IN
      value: If direction=='set' set pin to this value,
       if direction=='get' assert that this value is read

     Raises:
       TestFailure if value does not match what is returned by ectool

    """
    if direction == 'get':
      ectool_output = self.Ectool(['gpioget', pin_name]).rstrip()
      desired_string = 'GPIO %s = %d' % (pin_name, value)
      self.assertEqual(
          desired_string, ectool_output,
          'Wrong GPIO value: %s (%s)' % (ectool_output, desired_string))
    elif direction == 'set':
      ectool_output = self.Ectool(['gpioset', pin_name, str(value)])
    else:
      raise ValueError("direction must be either 'get' or 'set'")

  def Ectool(self, args):
    """Calls 'ectool' with the given args.

    Args:
      args: The args to pass along with 'ectool'.

    Raises:
      TestFailure if the ectool command returns non-zero exit code.
    """
    try:
      return process_utils.CheckOutput(['ectool'] + args, log=True)
    except subprocess.CalledProcessError as e:
      raise type_utils.TestFailure(
          'Non-zero exit code from ectool command: %d' % e.returncode)
