# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" Test if the memory size is correctly written in the firmware.

Test memory size by comparing the result of mosys and kernel meminfo.
Optionally, we can check memory size by the information on shopfloor if factory
supports it.
"""

import logging
import re
import threading
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import shopfloor
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import debug_utils
from cros.factory.utils import process_utils


_SHOPFLOOR_METHOD_NAME = 'GetMemSize'


class MemorySize(unittest.TestCase):
  ARGS = [
      Arg('compare_with_shopfloor', bool,
          'compare the memory size info with factory shopfloor', default=True),
      Arg('shopfloor_method_name', str,
          'Shopfloor method name for getting memory info',
          default=_SHOPFLOOR_METHOD_NAME),
      Arg('max_diff_gb', float,
          'maxmum difference between memory size detected by kernel and mosys',
          default=0.5),
  ]

  def setUp(self):
    self._event = threading.Event()
    self.ui = test_ui.UI()
    self.ui.AppendCSS('.large { font-size: 200% }')
    self.template = ui_templates.OneSection(self.ui)

  def Done(self):
    self._event.set()

  def runTest(self):
    self.ui.RunInBackground(self._runTest)
    self.ui.Run(on_finish=self.Done)

  def _runTest(self):
    self.template.SetState(
        i18n_test_ui.MakeI18nLabel('Checking memory info...'))

    # Get memory info using mosys.
    ret = process_utils.CheckOutput(
        ['mosys', '-k', 'memory', 'spd', 'print', 'geometry'])
    mosys_mem_mb = sum([int(x) for x in re.findall('size_mb="([^"]*)"', ret)])
    mosys_mem_gb = round(mosys_mem_mb / 1024.0, 1)

    # Get kernal meminfo.
    with open('/proc/meminfo', 'r') as f:
      kernel_mem_kb = int(re.search(r'^MemTotal:\s*([0-9]+)\s*kB',
                                    f.read()).group(1))
    kernel_mem_gb = round(kernel_mem_kb / 1024.0 / 1024.0, 1)

    diff = abs(kernel_mem_gb - mosys_mem_gb)
    if diff > self.args.max_diff_gb:
      self.fail('Memory size detected by kernel is different from mosys by '
                '%.1f GB' % diff)
      return

    if not self.args.compare_with_shopfloor:
      return

    self.ui.AddEventHandler('retry', lambda dummy_event: self._event.set())

    method_name = self.args.shopfloor_method_name
    method = getattr(shopfloor.get_instance(detect=True), method_name)
    mlb_serial_number = state.GetSerialNumber(state.KEY_MLB_SERIAL_NUMBER)
    message = 'Invoking %s(%s)' % (method_name, mlb_serial_number)

    while True:
      logging.info(message)
      self.template.SetState(test_ui.Escape(message))

      def HandleError(trace):
        self.template.SetState(
            i18n_test_ui.MakeI18nLabelWithClass(
                'Shop floor exception:',
                'test-status-failed large') +
            '<p>' +
            test_ui.Escape(trace) +
            '<p><br>' +
            """<button onclick="test.sendTestEvent('retry')">""" +
            i18n_test_ui.MakeI18nLabel('Retry') +
            '</button>')
        process_utils.WaitEvent(self._event)
        self._event.clear()

      try:
        result = method(mlb_serial_number)
        logging.info('%s: %s', method_name, result)
      except Exception:
        exception_str = debug_utils.FormatExceptionOnly()
        logging.exception('Exception invoking shopfloor method\n' +
                          exception_str)
        HandleError(exception_str)
        continue

      sf_mem_gb = round(float(result['mem_size']), 1)

      # The memory size info in mosys should be the same as that in shopfloor.
      if abs(mosys_mem_gb - sf_mem_gb) > 10e-6:
        msg = ('Memory size detected in mosys (%.1f GB) is different from the '
               'reocrd in shopfloor (%.1f GB)' % (mosys_mem_gb, sf_mem_gb))
        self.fail(msg)
      break
