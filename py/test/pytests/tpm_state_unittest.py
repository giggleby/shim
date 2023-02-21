#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for TPM state"""

import unittest
from unittest import mock

from cros.factory.test.pytests import tpm_state


class TPMStateTest(unittest.TestCase):

  def setUp(self) -> None:
    self.tpm = tpm_state.VerifyTPMState()

  def testTPMFailState(self) -> None:
    failed_state = 'HSP Secure state:      0x0\n'
    output_mock = mock.Mock()
    output_mock.CallOutput.return_value = failed_state

    # pylint: disable=protected-access
    self.tpm._dut = output_mock
    result = self.tpm._CheckTPMFusedOff()
    # pylint: enable=protected-access
    self.assertFalse(result)

  def testTPMSuccessState(self) -> None:
    success_state = 'HSP Secure state:      0x20\n'
    output_mock = mock.Mock()
    output_mock.CallOutput.return_value = success_state

    # pylint: disable=protected-access
    self.tpm._dut = output_mock
    result = self.tpm._CheckTPMFusedOff()
    # pylint: enable=protected-access
    self.assertTrue(result)

  def testTPMIncorrectState(self) -> None:
    incorrect_state = ''
    output_mock = mock.Mock()
    output_mock.CallOutput.return_value = incorrect_state

    # pylint: disable=protected-access
    self.tpm._dut = output_mock
    self.assertRaises(tpm_state.TPMStateNotFoundException,
                      self.tpm._CheckTPMFusedOff)
    # pylint: enable=protected-access


if __name__ == '__main__':
  unittest.main()
