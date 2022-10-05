#!/usr/bin/env python3
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unit tests for mrc_cache."""

import textwrap
import unittest
from unittest import mock

from cros.factory.tools import mrc_cache


_SYSTEM_BOOT = '78 | 2022-10-05 20:23:14 | System boot | 70\n'
_CACHE_UPDATE = '77 | 2022-10-05 20:23:03 | Memory Cache Update | %s | %s\n'


def _GenerateEventLog(
    normal_res: mrc_cache.Result,
    recovery_res: mrc_cache.Result = mrc_cache.Result.NoUpdate,
    has_recovery_sec: bool = False):
  """Generate the eventlog for the unit test.

    Args:
      normal_res: The result of the normal MRC training.
      recovery_res: The result of the recovery MRC training.
      has_recovery_sec: FMAP contains `RECOVERY_MRC_CACHE` section or not.

    Returns:
      An eventlog string.
    """

  def GenerateUpdateEvent(mode: mrc_cache.Mode, result: mrc_cache.Result):
    eventlog = ''
    if result != mrc_cache.Result.NoUpdate:
      eventlog += _CACHE_UPDATE % (mode.value, result.value)
    eventlog += _SYSTEM_BOOT
    return eventlog

  eventlog = _SYSTEM_BOOT
  if has_recovery_sec:
    eventlog += GenerateUpdateEvent(mrc_cache.Mode.Recovery, recovery_res)
  eventlog += GenerateUpdateEvent(mrc_cache.Mode.Normal, normal_res)

  return eventlog


class MRCCacheTestHasRecovery(unittest.TestCase):

  FMAP_SECTION = textwrap.dedent("""\
    SI_ALL 0 3866624
    SI_DESC 0 4096
    SI_ME 4096 3862528
    CSE_LAYOUT 4096 8192
    CSE_RO 12288 1392640
    CSE_DATA 1404928 430080
    CSE_RW 1835008 2031616
    SI_BIOS 3866624 29687808
    RW_SECTION_A 3866624 4448256
    VBLOCK_A 3866624 8192
    FW_MAIN_A 3874816 2971584
    RW_FWID_A 6846400 64
    ME_RW_A 6846464 1468416
    RW_LEGACY 8314880 1048576
    RW_MISC 9363456 155648
    UNIFIED_MRC_CACHE 9363456 131072
    RECOVERY_MRC_CACHE 9363456 65536
    RW_MRC_CACHE 9428992 65536
    RW_ELOG 9494528 4096
    RW_SHARED 9498624 4096
    SHARED_DATA 9498624 4096
    RW_VPD 9502720 8192
    RW_NVRAM 9510912 8192
    RW_UNUSED_1 9519104 7258112
    RW_SECTION_B 16777216 4448256
    VBLOCK_B 16777216 8192
    FW_MAIN_B 16785408 2971584
    RW_FWID_B 19756992 64
    ME_RW_B 19757056 1468416
    RW_UNUSED_2 21225472 8134656
    WP_RO 29360128 4194304
    RO_VPD 29360128 16384
    RO_GSCVD 29376512 8192
    RO_SECTION 29384704 4169728
    FMAP 29384704 2048
    RO_FRID 29386752 64
    GBB 29388800 12288
    COREBOOT 29401088 4153344
  """)

  def setUp(self):
    self.dut = mock.MagicMock()
    self.mrc_sections = ['RECOVERY_MRC_CACHE', 'RW_MRC_CACHE']

  def testGetMRCSections(self):
    self.dut.CheckOutput.return_value = self.FMAP_SECTION
    self.assertEqual(mrc_cache.GetMRCSections(self.dut), self.mrc_sections)

  @mock.patch('cros.factory.tools.mrc_cache.GetMRCSections')
  def testEraseTrainingData(self, get_mrc_section_mock):
    get_mrc_section_mock.return_value = self.mrc_sections

    mrc_cache.EraseTrainingData(self.dut)

    check_call_calls = [
        mock.call([
            'flashrom', '-p', 'host', '-E', '-i', 'RECOVERY_MRC_CACHE', '-i',
            'RW_MRC_CACHE'
        ], log=True),
    ]
    self.assertEqual(self.dut.CheckCall.call_args_list, check_call_calls)

  @mock.patch('cros.factory.tools.mrc_cache.GetMRCSections')
  def testSetRecoveryRequest(self, get_mrc_section_mock):
    get_mrc_section_mock.return_value = self.mrc_sections

    mrc_cache.SetRecoveryRequest(self.dut)

    check_call_calls = [
        mock.call('crossystem recovery_request=0xC4', log=True),
    ]
    self.assertEqual(self.dut.CheckCall.call_args_list, check_call_calls)

  @mock.patch('cros.factory.utils.file_utils.ReadFile')
  @mock.patch('cros.factory.tools.mrc_cache.GetMRCSections')
  def testVerifyTrainingResult(self, get_mrc_section_mock, read_file_mock):
    get_mrc_section_mock.return_value = self.mrc_sections

    # Both sections updates successfully.
    read_file_mock.return_value = _GenerateEventLog(
        mrc_cache.Result.Success, mrc_cache.Result.Success, True)
    mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.Success)

    # Recovery MRC cache does not update.
    read_file_mock.return_value = _GenerateEventLog(
        mrc_cache.Result.Success, mrc_cache.Result.NoUpdate, True)
    with self.assertRaises(mrc_cache.MRCCacheUpdateError):
      mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.Success)

    # Both sections fails to update.
    read_file_mock.return_value = _GenerateEventLog(mrc_cache.Result.Fail,
                                                    mrc_cache.Result.Fail)
    with self.assertRaises(mrc_cache.MRCCacheUpdateError):
      mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.Success)

    # Both sections do not update.
    read_file_mock.return_value = _GenerateEventLog(mrc_cache.Result.NoUpdate,
                                                    mrc_cache.Result.NoUpdate)
    mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.NoUpdate)


class MRCCacheTestNoRecovery(unittest.TestCase):

  FMAP_SECTION = textwrap.dedent("""\
    WP_RO 0 4194304
    RO_SECTION 0 4161536
    BOOTBLOCK 0 131072
    FMAP 131072 4096
    COREBOOT 135168 4014080
    GBB 4149248 12032
    RO_FRID 4161280 256
    RO_VPD 4161536 32768
    RW_SECTION_A 4194304 1536000
    VBLOCK_A 4194304 8192
    FW_MAIN_A 4202496 1527552
    RW_FWID_A 5730048 256
    RW_MISC 5730304 36864
    RW_VPD 5730304 16384
    RW_NVRAM 5746688 8192
    RW_MRC_CACHE 5754880 8192
    RW_ELOG 5763072 4096
    RW_SECTION_B 5767168 1536000
    VBLOCK_B 5767168 8192
    FW_MAIN_B 5775360 1527552
    RW_FWID_B 7302912 256
    RW_SHARED 7303168 36864
    SHARED_DATA 7303168 4096
    RW_UNUSED 7307264 32768
    RW_LEGACY 7340032 1048576""")

  def setUp(self):
    self.dut = mock.MagicMock()
    self.mrc_sections = ['RW_MRC_CACHE']

  def testGetMRCSections(self):
    self.dut.CheckOutput.return_value = self.FMAP_SECTION
    self.assertEqual(mrc_cache.GetMRCSections(self.dut), self.mrc_sections)

  @mock.patch('cros.factory.tools.mrc_cache.GetMRCSections')
  def testEraseTrainingData(self, get_mrc_section_mock):
    get_mrc_section_mock.return_value = self.mrc_sections

    mrc_cache.EraseTrainingData(self.dut)

    check_call_calls = [
        mock.call(['flashrom', '-p', 'host', '-E', '-i', 'RW_MRC_CACHE'],
                  log=True),
    ]
    self.assertEqual(self.dut.CheckCall.call_args_list, check_call_calls)

  @mock.patch('cros.factory.tools.mrc_cache.GetMRCSections')
  def testSetRecoveryRequest(self, get_mrc_section_mock):
    get_mrc_section_mock.return_value = self.mrc_sections
    mrc_cache.SetRecoveryRequest(self.dut)
    self.assertEqual(self.dut.CheckCall.call_args_list, [])

  @mock.patch('cros.factory.utils.file_utils.ReadFile')
  @mock.patch('cros.factory.tools.mrc_cache.GetMRCSections')
  def testVerifyTrainingData(self, get_mrc_section_mock, read_file_mock):
    get_mrc_section_mock.return_value = self.mrc_sections

    # RW cache updates successfully.
    read_file_mock.return_value = _GenerateEventLog(mrc_cache.Result.Success)
    mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.Success)

    # RW cache fails to update.
    read_file_mock.return_value = _GenerateEventLog(mrc_cache.Result.Fail)
    with self.assertRaises(mrc_cache.MRCCacheUpdateError):
      mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.Success)

    # RW cache does not update.
    read_file_mock.return_value = _GenerateEventLog(mrc_cache.Result.NoUpdate)
    mrc_cache.VerifyTrainingData(self.dut, mrc_cache.Result.NoUpdate)


if __name__ == '__main__':
  unittest.main()
