#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import subprocess
import textwrap
import unittest
from unittest import mock

from cros.factory.probe import function
from cros.factory.probe.functions import generic_cpu


class GenericCPUFunctionTest(unittest.TestCase):

  def setUp(self):
    patcher = mock.patch('cros.factory.utils.process_utils.CheckOutput')
    self.mock_check_output = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.probe.functions.file.ReadFile')
    self.mock_read_file = patcher.start()
    self.addCleanup(patcher.stop)

  def testProbeX86_Suceed(self):
    self.mock_check_output.return_value = textwrap.dedent('''\
      Model name:             Intel(R) Xeon(R) Gold 6154 CPU @ 3.00GHz
      CPU(s):                 72
      On-line CPU(s) list:    0-71''')

    probe_result = generic_cpu.GenericCPUFunction(cpu_type='x86').Probe()

    self.assertDictEqual(
        probe_result, {
            'model': 'Intel(R) Xeon(R) Gold 6154 CPU @ 3.00GHz',
            'cores': '72',
            'online_cores': '72'
        })

  def testProbeX86_CalledProcessError(self):
    self.mock_check_output.side_effect = subprocess.CalledProcessError(1, 'cmd')

    probe_result = generic_cpu.GenericCPUFunction(cpu_type='x86').Probe()

    self.assertEqual(probe_result, function.NOTHING)

  def testProbeArm_V7(self):
    cpu_info = textwrap.dedent('''\
      Processor       : ARMv7 Processor rev 0 (v7l)
      Hardware        : Qualcomm (Flattened Device Tree)
      CPU architecture: 7''')
    self.mock_read_file.side_effect = [cpu_info, 'jep106:0070:0000']
    self.mock_check_output.return_value = '2'

    probe_result = generic_cpu.GenericCPUFunction(cpu_type='arm').Probe()

    self.assertDictEqual(
        probe_result, {
            'cores': '2',
            'hardware': 'Qualcomm (Flattened Device Tree)',
            'model': 'ARMv7 Processor rev 0 (v7l)'
        })

  def testProbeArm_V8(self):
    cpu_info = 'CPU architecture: 8'
    self.mock_read_file.side_effect = [
        cpu_info, 'jep106:0426:8186', b'\x01\x10\x86\x81'
    ]
    self.mock_check_output.return_value = '8'

    probe_result = generic_cpu.GenericCPUFunction(cpu_type='arm').Probe()

    self.assertDictEqual(probe_result, {
        'cores': '8',
        'hardware': '0x81861001',
        'model': 'ARMv8 Vendor0426 8186',
    })

  def testProbeArm_V8_InvalidVendorID(self):
    cpu_info = 'CPU architecture: 8'
    self.mock_read_file.side_effect = [cpu_info, 'invalid_vendor_id']
    with self.assertRaises(ValueError):
      generic_cpu.GenericCPUFunction(cpu_type='arm').Probe()

  def testProbeArm_V8_UnsupportedVendorID(self):
    cpu_info = 'CPU architecture: 8'
    self.mock_read_file.side_effect = [cpu_info, 'jep106:1234']
    with self.assertRaises(ValueError):
      generic_cpu.GenericCPUFunction(cpu_type='arm').Probe()


if __name__ == '__main__':
  unittest.main()
