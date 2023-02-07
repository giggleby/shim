#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.rf import modem
from cros.factory.utils import type_utils


class ModemUnittest(unittest.TestCase):

  def setUp(self) -> None:

    self.serial_mock_obj = mock.Mock(name='serial_mock')
    self.serial_mock_obj.readline.return_value = "OK"

    mock_serial_patcher = mock.patch('cros.factory.test.rf.modem.serial.Serial')
    self.mock_serial = mock_serial_patcher.start()
    self.mock_serial.return_value = self.serial_mock_obj
    self.addCleanup(mock_serial_patcher.stop)

    self.modem_test_obj = modem.Modem(123)
    self.serial_mock_obj.write.assert_called_with("AT\r")

  def testModemReadLine(self):
    self.serial_mock_obj.readline.side_effect = [
        "test1\r\n", "", "", "test2\r\n", "OK"
    ]
    self.assertEqual(self.modem_test_obj.ReadLine(), "test1")
    self.assertEqual(self.modem_test_obj.ReadLine(), "test2")

  def testModemSendCommand(self):

    self.serial_mock_obj.readline.side_effect = [
        "test1\r\n", "", "test2\r\n", "OK"
    ]
    expected_response = ["test1", "test2", "OK"]
    response = self.modem_test_obj.SendCommandWithCheck("random_str")
    self.assertEqual(response, expected_response)

  def testModemRaiseError(self):

    self.serial_mock_obj.readline.side_effect = [
        "", "", "", "", "test2\r\n", "OK"
    ]
    self.modem_test_obj.SendCommandWithCheck("random_str", 2)
    self.assertRaises(type_utils.MaxRetryError)


if __name__ == '__main__':
  unittest.main()
