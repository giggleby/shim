#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import subprocess
import textwrap
import unittest
from unittest import mock

from cros.factory.probe.functions import embedded_controller


class EmbeddedControllerFunctionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    patcher = mock.patch('cros.factory.utils.process_utils.CheckOutput')
    self._mock_check_output = patcher.start()
    self.addCleanup(self._mock_check_output.stop)

    embedded_controller.EmbeddedControllerFunction.CleanCachedData()

  def testSubprocessFails(self):
    self._mock_check_output.side_effect = subprocess.CalledProcessError(
        1, 'unused error info')

    results = embedded_controller.EmbeddedControllerFunction()()

    self.assertEqual(results, [])

  def testFailedToParseSubprocessOutput(self):
    testdata = {
        'incorrect head line':
            textwrap.dedent('''\
                Chip info v2:
                  vendor:   aaa
                  name:     bbb
                  revision: ccc'''),
        'unparsable data field line':
            'Chip info:\nthis line is unrecognizable by the probe function.',
    }
    for sub_test_name, check_output_return_value in testdata.items():
      with self.subTest(sub_test_name):
        self._mock_check_output.return_value = check_output_return_value

        embedded_controller.EmbeddedControllerFunction.CleanCachedData()
        results = embedded_controller.EmbeddedControllerFunction()()

        self.assertEqual(results, [])

  def testMissingRequiredFields(self):
    self._mock_check_output.return_value = 'Chip info:\n  vendor:  aaa'

    results = embedded_controller.EmbeddedControllerFunction()()

    self.assertEqual(results, [])

  def testProbedSuccessfully(self):
    testdata = {
        'normal case': (
            'Chip info:\n  vendor:   a\n  name:     b\n  revision: c',
            {
                'vendor': 'a',
                'name': 'b',
                'revision': 'c'
            },
        ),
        'value has spaces': (
            'Chip info:\n  vendor:   a a\n  name:     b\n  revision: c',
            {
                'vendor': 'a a',
                'name': 'b',
                'revision': 'c'
            },
        ),
        'value ending spaces to be trimmed': (
            'Chip info:\n  vendor:   a  \n  name:     b\n  revision: c',
            {
                'vendor': 'a',
                'name': 'b',
                'revision': 'c'
            },
        ),
        'has extra fields and ignored': (
            ('Chip info:\n  vendor:   a  \n  name:     b\n  revision: c\n'
             '  other: d'),
            {
                'vendor': 'a',
                'name': 'b',
                'revision': 'c',
            },
        ),
    }
    for sub_test_name, (check_output_return_value,
                        expect_probed_result) in (testdata.items()):
      with self.subTest(sub_test_name):
        self._mock_check_output.return_value = check_output_return_value

        embedded_controller.EmbeddedControllerFunction.CleanCachedData()
        results = embedded_controller.EmbeddedControllerFunction()()

        self.assertEqual(results, [expect_probed_result])


if __name__ == '__main__':
  unittest.main()
