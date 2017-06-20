# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""This test auto read module serial numbers and save the serial number to the
factory test state. If you need manual input sn, you should check scan.py.

Usage examples::

    OperatorTest(
        id='GetCameraModuleSerialNumber',
        label=_('GetCameraModuleSerialNumber'),
        action_on_failure='PARENT',
        pytest_name='get_module_serial_number',
        dargs={
            'component': 'camera',
            'method_names': ['GetCameraDevice', 'GetSerialNumber'],
            'method_kwargs': [{'index': 0}, {}],
            'serial_number_name': 'camera_serial_number'
        })

"""


import logging
import re
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import state
from cros.factory.utils.arg_utils import Arg


class GetModuleSerialNumber(unittest.TestCase):
  ARGS = [
      Arg('component',
          str,
          'Read the serial number from the given component.',
          optional=False),
      Arg('method_names',
          list,
          'A list of methods that recurrsively called.',
          optional=False),
      Arg('method_kwargs',
          list,
          'A list of kwargs passed to recurrsively called methods.',
          optional=False),
      Arg('serial_number_name',
          str,
          'The name of the serial number to save in state, defaults to '
          'args.component + _serial_number',
          default=None,
          optional=True),
      Arg('regexp',
          str,
          'Regexp that the serial number must match. None for no check',
          default=None,
          optional=True),
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.module_sn = None
    self.serial_number_name = self.args.serial_number_name or (
        '%s_serial_number' % self.args.component)
    if len(self.args.method_names) != len(self.args.method_kwargs):
      raise ValueError('The length of method_names and method_kwargs must be '
                       'the same.')

  def runTest(self):
    current_instance = getattr(self.dut, self.args.component)
    for name, kwarg in zip(self.args.method_names, self.args.method_kwargs):
      method = getattr(current_instance, name)
      current_instance = method(**kwarg)

    if not isinstance(current_instance, (str, unicode)):
      raise ValueError('Serial number must be types of str or unicode.')

    self.module_sn = str(current_instance)
    logging.info('%s: %s', self.serial_number_name, self.module_sn)

    if self.args.regexp:
      if re.match(self.args.regexp, self.module_sn) is None:
        raise ValueError('Serial number %s does not match the regexp %r' %
                         (self.module_sn, self.args.regexp))
    try:
      state.SetSerialNumber(self.serial_number_name, self.module_sn)
    except Exception as e:
      logging.exception('Error setting serial number to state: %s', e.message)
      raise e
