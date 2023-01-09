#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for factory_log_extractor."""

import os
import textwrap
import unittest

from cros.factory.tools import factory_log_extractor
from cros.factory.utils import file_utils


class ExtractAndMergeLogsTest(unittest.TestCase):

  _FACTORY_TEST_LOG_1 = textwrap.dedent("""\
    {"count": 1, "success": true, "time": 1664758814.8908494}
    {"filePath": "/usr/local/factory/py/cli/goofy.py", "time": 1664758814.8924632, "message": "Received a notify to update system info."}
    """)

  _EXPECTED_FILTERED_LOGS = textwrap.dedent("""\
    {"filePath": "/usr/local/factory/py/cli/goofy.py", "message": "Received a notify to update system info."}
    """)

  _FACTORY_TEST_LOG_2 = textwrap.dedent("""\
    {"time": 1664758861.421798, "logLevel": "INFO", "message": "Testlog(dade3d78-909d-4171-ab7d-297e2e17cd2b) is capturing logging at level INFO"}
    {"time": 1664758861.433593, "logLevel": "INFO", "message": "Starting goofy server"}
    {"time": 1664758861.508313, "logLevel": "INFO", "message": "No test list constants config found"}
    """)

  _VAR_LOG_MESSAGES = textwrap.dedent("""\
    {"time": 1664758814.89215, "logLevel": "INFO", "message": "goofy[1636]: Goofy (factory test harness) starting"}
    {"time": 1664758814.892269, "logLevel": "INFO", "message": "goofy[1636]: Boot sequence = 0"}
    {"time": 1664758814.892331, "logLevel": "INFO", "message": "goofy[1636]: Goofy init count = 1"}
    {"time": 1664957250.023325, "logLevel": "INFO", "message": "smbproviderd[3272]: smbproviderd stopping with exit code 0"}
    """)

  _EXPECTED_MERGED_LOGS_FILTER_LOG_LEVEL = textwrap.dedent("""\
    {"time": 1664758814.89215, "message": "goofy[1636]: Goofy (factory test harness) starting"}
    {"time": 1664758814.892269, "message": "goofy[1636]: Boot sequence = 0"}
    {"time": 1664758814.892331, "message": "goofy[1636]: Goofy init count = 1"}
    {"time": 1664758861.421798, "message": "Testlog(dade3d78-909d-4171-ab7d-297e2e17cd2b) is capturing logging at level INFO"}
    {"time": 1664758861.433593, "message": "Starting goofy server"}
    {"time": 1664758861.508313, "message": "No test list constants config found"}
    {"time": 1664957250.023325, "message": "smbproviderd[3272]: smbproviderd stopping with exit code 0"}
    """)

  def _CreateAndWriteFile(self, root, name, content):
    path = os.path.join(root, name)
    file_utils.WriteFile(path, content)
    return path

  def testKeepFields(self):
    with file_utils.TempDirectory() as temp_dir:
      testlog_path = self._CreateAndWriteFile(temp_dir, 'factory_testlog.json',
                                              self._FACTORY_TEST_LOG_1)
      output_path = os.path.join(temp_dir, 'extracted_logs.json')

      factory_log_extractor.ExtractAndMergeLogs([testlog_path], output_path,
                                                ['filePath', 'message'])
      self.assertEqual(
          file_utils.ReadFile(output_path), self._EXPECTED_FILTERED_LOGS)

  def testExtractAndMergeMultiFiles(self):
    with file_utils.TempDirectory() as temp_dir:
      testlog_path = self._CreateAndWriteFile(temp_dir, 'factory_testlog.json',
                                              self._FACTORY_TEST_LOG_2)
      var_log_msg_path = self._CreateAndWriteFile(temp_dir, 'var_log_msg.json',
                                                  self._VAR_LOG_MESSAGES)
      output_path = os.path.join(temp_dir, 'extracted_logs.json')

      factory_log_extractor.ExtractAndMergeLogs(
          [testlog_path, var_log_msg_path], output_path, ['time', 'message'])
      self.assertEqual(
          file_utils.ReadFile(output_path),
          self._EXPECTED_MERGED_LOGS_FILTER_LOG_LEVEL)


if __name__ == '__main__':
  unittest.main()
