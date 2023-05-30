#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.probe.lib import runtime_probe_function
from cros.factory.utils import json_utils


class FakeRuntimeProbeFunction(runtime_probe_function.RuntimeProbeFunction):
  FUNCTION_NAME = 'fake_probe_function'


@mock.patch('cros.factory.probe.runtime_probe.runtime_probe_adapter'
            '.process_utils.CheckOutput')
class RuntimeProbeFunctionTest(unittest.TestCase):

  def testProbe(self, mockCheckOutput):
    mockCheckOutput.return_value = '''
      {
        "adaptor_category": [
          {
            "name": "device_a",
            "values": {
              "vendor_id": "abc",
              "device_id": "def"
            }
          },
          {
            "name": "device_b",
            "values": {
              "vendor_id": "abc",
              "device_id": "ghi"
            }
          }
        ]
      }
    '''

    func = FakeRuntimeProbeFunction()
    self.assertEqual(func(), [
        {
            'vendor_id': 'abc',
            'device_id': 'def'
        },
        {
            'vendor_id': 'abc',
            'device_id': 'ghi'
        },
    ])
    # TODO(chungsheng): Use mockCheckOutput.call_args.args[0] after python3.8.
    called_command = mockCheckOutput.call_args[0][0]
    self.assertEqual(called_command[0],
                     '/usr/local/usr/bin/factory_runtime_probe')
    self.assertEqual(
        json_utils.LoadStr(called_command[1]), {
            'adaptor_category': {
                'adaptor_component': {
                    'eval': {
                        'fake_probe_function': {}
                    },
                    'expect': {}
                }
            }
        })


if __name__ == '__main__':
  unittest.main()
