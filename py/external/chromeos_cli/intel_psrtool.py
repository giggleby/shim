# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple
import logging
import re
import time

from cros.factory.external.chromeos_cli import shell


PSRStatus = namedtuple('PSRStatus', 'state availability')


class IntelPSRTool:
  """Helper class to operate `intel-psrtool` cmdline utility."""

  def __init__(self, dut=None) -> None:
    self._shell = shell.Shell(dut)

  def StartPSREventLog(self):
    stdout = self._shell(['intel-psrtool', '-a']).stdout
    match = re.search(r'ACTION_NOT_ALLOWED', stdout)
    if match:
      logging.warning(
          'Failed to start PSR event log. It has been started already')

  def CommitOEMData(self):
    """Commits OEM Data and saves the values to ME FW."""
    assert self.GetManufacturingNVAR() == 0, (
        'Committing is disabled after closing manufacturing.')
    assert self.GetPSRStateAndAvailability().state == 'NOT STARTED', (
        'Committing is disabled after PSR logging started.')
    self._shell(['intel-psrtool', '-c'])
    time.sleep(1)

  def GetPSRStateAndAvailability(self):
    """Returns a PSRStatus with state and availability"""
    stdout = self._shell(['intel-psrtool', '-s']).stdout
    match_state = re.search(r'state:\s*((NOT\s)?\w+)', stdout)
    if not match_state:
      raise RuntimeError(f'Failed to get PSR state from output: {stdout}')
    match_availability = re.search(r'availability:\s*(\w+)', stdout)
    if not match_availability:
      raise RuntimeError(
          f'Failed to get PSR availability from output: {stdout}')
    return PSRStatus(match_state.group(1), match_availability.group(1))

  def DisplayPSRLog(self):
    return self._shell(['intel-psrtool', '-d'])

  def ReadAndCreateOEMDataConfig(self, filename):
    """Reads OEM data in ME FW and creates a config with `filename`.

    Creates a config file with OEM data values copied from ME FW.
    """
    self._shell(['intel-psrtool', '-g', filename])

  def WriteNVAR(self, NVAR_name, NVAR_value):
    """Writes a `NVAR_value` to the `NVAR_name`"""
    self._shell(['intel-psrtool', '-w', NVAR_name, '-v', NVAR_value])

  def UpdateOEMDataFromConfig(self, filename):
    self._shell(['intel-psrtool', '-u', filename])

  def VerifyOEMData(self, filename):
    """Verifies OEM Data saved in ME FW is identical to the config `filename`"""
    ret = self._shell(['intel-psrtool', '-k', filename])
    if not ret.success:
      raise RuntimeError(ret.stderr)

  def GetManufacturingNVAR(self):
    """Returns Manufacturing(EOM) NVAR, which can be an integer 0 or 1 """
    stdout = self._shell(['intel-psrtool', '-m']).stdout
    match = re.search(r'NVAR\svalue\s=\s*(\w+)', stdout)
    if not match:
      raise RuntimeError(f'Failed to get PSR EOM NVAR from output: {stdout}')
    return int(match.group(1))

  def CloseManufacturing(self):
    """Closes Manufacturing and sets EOM NVAR to '1'"""
    self._shell(['intel-psrtool', '-e'])

  def GetMEstatus(self):
    return self._shell(['intel-psrtool', '-l'])

  def ClearAndStopPSREventLog(self):
    self._shell(['intel-psrtool', '-x'])