# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verifies the TPM endorsement key.

This test (whether it succeeds or fails) always requests a TPM clear
on reboot.  It works even if run multiple times without rebooting.

If the TPM is somehow owned but no password is available, the test
will fail but emit a reasonable error message (and it will pass on the
next boot).
"""

import logging
import os
import tempfile
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.device import device_utils
from cros.factory.utils import sync_utils
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.string_utils import ParseDict


class TPMVerifyEK(unittest.TestCase):
  ARGS = [
      # Chromebooks and Chromeboxes should set this to False.
      Arg('is_cros_core', bool, 'Verify with ChromeOS Core endoresement',
          default=False),
      Arg('tpm_version', str, 'Check tpm_version is equal or not', default=None)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def VerifyByCryptoHome(self):
    """Verifies TPM endorsement by CryptoHome service."""

    def _TPMStatus():
      """Returns TPM status as a dictionary.

      e.g., {'TPM Being Owned': 'false',
             'TPM Ready': 'true',
             'TPM Password': 'd641b63ce6ff',
             'TPM Enabled': 'true',
             'TPM Owned': 'true'}
      """
      status_txt = self.dut.CheckOutput(['cryptohome', '--action=tpm_status'],
                                        log=True)
      status = ParseDict(status_txt.splitlines())
      logging.info('TPM status: %r', status)
      return status

    # Make sure TPM is enabled.
    status = _TPMStatus()
    self.assertEquals('true', status['TPM Enabled'])

    # Check explicitly for the case where TPM is owned but password is
    # unavailable.  This shouldn't really ever happen, but in any case
    # the TPM will become un-owned on reboot (thanks to the crossystem
    # command above).
    self.assertFalse(
        status['TPM Owned'] == 'true' and not status['TPM Password'],
        'TPM is owned but password is not available. Reboot and re-run.')

    # Take ownership of the TPM (if not already taken).
    self.dut.CheckCall(['cryptohome', '--action=tpm_take_ownership'],
                       log=True)
    # Wait for TPM ownership to complete.  No check_call=True since this
    # may fail if the TPM is already owned.
    self.dut.Call(['cryptohome', '--action=tpm_wait_ownership'],
                  log=True)
    # Sync, to make sure TPM password was written to disk.
    self.dut.CheckCall(['sync'], log=True)

    self.assertEquals('true', _TPMStatus()['TPM Owned'])

    # Verify the endorsement key.
    with tempfile.TemporaryFile() as stderr:
      self.dut.CheckCall(['cryptohome', '--action=tpm_verify_ek'] + (
          ['--cros_core'] if self.args.is_cros_core else []),
                         log=True, stderr=stderr)
      # Make sure there's no stderr from tpm_verify_ek (since that, plus
      # check_call=True, is the only reliable way to make sure it
      # worked).
      stderr.seek(0)
      self.assertEquals('', stderr.read())

  def VerifyByTpmManager(self):
    """Verifies TPM endorsement by tpm-manager (from CryptoHome package)."""

    # Take ownership of the TPM (if not already taken).
    self.dut.CheckCall(['tpm-manager', 'initialize'], log=True)

    # Verify TPM endorsement.
    self.dut.CheckCall(['tpm-manager', 'verify_endorsement'] + (
        ['--cros_core'] if self.args.is_cros_core else []), log=True)

  def UpdateTpmFirmware(self):
    tpm_tool_dir = '/usr/local/factory/third_party/'

    self.dut.CheckCall(['crossystem', 'clear_tpm_owner_request=1'], log=True)
    self.dut.CheckCall(['stop', 'tcsd'], log=True)
    self.dut.CheckCall([os.path.join(tpm_tool_dir, 'TPMFactoryUpd'), '-update',
                        'tpm12-takeownership', '-firmware',
                        os.path.join(tpm_tool_dir, 'TPM12_133.32.80.0_to_TPM12_133.33.227.2.BIN')],
                       log=True)
    self.dut.CheckCall(['reboot'], log=True)

    # Wait for DUT reboot.
    time.sleep(5)
    sync_utils.WaitFor(self.dut.IsReady, timeout_secs=60, poll_interval=1)

  def runTest(self):
    if self.args.tpm_version:
      # Check tpm_version on DUT equals to given tpm_version or not.
      output = self.dut.CheckOutput(['tpm_version'], log=True)

      # If tpm_version on DUT is "1.2.133.32", should update tpm version.
      if "1.2.133.32" in output:
        self.UpdateTpmFirmware()

        output = self.dut.CheckOutput(['tpm_version'], log=True)

      self.assertTrue(self.args.tpm_version in output)

    # Always clear TPM on next boot, in case any problems arise.
    self.dut.CheckCall(['crossystem', 'clear_tpm_owner_request=1'], log=True)

    # Check if we have tpm-manager in system.
    if self.dut.Call(['which', 'tpm-manager']) == 0:
      self.VerifyByTpmManager()
    else:
      self.VerifyByCryptoHome()
