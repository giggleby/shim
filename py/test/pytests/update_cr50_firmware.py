# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Update Cr50 firmware.

Description
-----------
This test provides two functionalities, toggled by the test argument ``method``.

1. This test calls `gsctool` on DUT to update Cr50 firmware.
   By default, the update of RO happens if the version of the given firmware is
   newer than the version on the chip. The update of RW happens if the version
   of the given firmware is newer or the same as the version on the chip.
   In force RO mode (-q), it forces to update the RO even if the version of the
   given firmware is the same as the version on the chip. The chip will reboot
   automatically after the update.
   In upstart mode (-u), it prevents RW update if the version of the given
   firmware is the same as version on the chip. It also prevents the immediate
   reboot after the update.
2. In `check mode`, this test calls `gsctool` on DUT to check if the cr50
   firmware version is greater than or equal to the given firmware image.

The Cr50 firmware image to update or compare is either from a given path in
station or DUT, or from the release partition on DUT.

To prepare Cr50 firmware image on station, download the release image with
desired Cr50 firmware image and find the image in DEFAULT_FIRMWARE_PATH below.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

1. Firstly, this test will create a DUT link.
2. If Cr50 firmware image source is from station, the image would be sent to
   DUT.
3. If the Cr50 image is in release partition, the test mounts the release
   partition to get the Cr50 image.
4. If `method` is set to `UPDATE`, DUT runs `gsctool` to update
   Cr50 firmware using the specified Cr50 image.
5. If `method` is set to `CHECK_VERSION`, DUT runs `gsctool` to check
   whether the Cr50 firmware version is greater than or equals to the
   specified Cr50 image.

Dependency
----------
- DUT link must be ready before running this test.
- `gsctool` on DUT.
- Cr50 firmware image must be prepared.

Examples
--------
To update Cr50 firmware with the Cr50 firmware image in DUT release partition,
add this in test list::

  {
    "pytest_name": "update_cr50_firmware"
  }

To update Cr50 firmware without upstart mode, unset `upstart_mode` argument and
set the pytest as `allow_reboot`. After updated and reboot, the test will be run
again and succeeds in the second run::

  {
    "pytest_name": "update_cr50_firmware",
    "allow_reboot": true,
    "args": {
      "upstart_mode": false
    }
  }

To update Cr50 firmware with the Cr50 firmware image in station::

  {
    "pytest_name": "update_cr50_firmware",
    "args": {
      "firmware_file": "/path/on/station/to/cr50.bin.prod",
      "from_release": false
    }
  }

To check if Cr50 firmware version is greater than or equals to the Cr50 image
in the release image::

  {
    "pytest_name": "update_cr50_firmware",
    "args": {
      "method": "CHECK_VERSION"
    }
  }

To update the Ti50 firmware version from 0.0.15 (or less) to 0.0.16+ with
prepvt firmware::

  {
    "pytest_name": "update_cr50_firmware"
    "allow_reboot": true,
    "args": {
      "firmware_file": "/path/to/ti50.bin.prepvt",
      "skip_prepvt_flag_check": "eval! constants.phase != 'PVT'",
      "upstart_mode": false,
      "force_ro_mode": true,
      "is_ti50": true
    }
  }

"""

from distutils import version
import functools
import logging
import os

from cros.factory.device import device_utils
from cros.factory.gooftool import common as gooftool_common
from cros.factory.gooftool import gsctool
from cros.factory.test import device_data
from cros.factory.test.rules import phase
from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sys_utils
from cros.factory.utils import type_utils

DEFAULT_FIRMWARE_PATH = '/opt/google/cr50/firmware/cr50.bin.prod'
PREPVT_FLAG_MASK = 0x7F
KEY_ATTEMPT_CR50_UPDATE_RO_VERSION = device_data.JoinKeys(
    device_data.KEY_FACTORY, 'attempt_cr50_update_ro_version')
KEY_ATTEMPT_CR50_UPDATE_RW_VERSION = device_data.JoinKeys(
    device_data.KEY_FACTORY, 'attempt_cr50_update_rw_version')


class UpdateCr50FirmwareTest(test_case.TestCase):
  _METHOD_TYPE = type_utils.Enum(['UPDATE', 'CHECK_VERSION'])

  ARGS = [
      Arg('firmware_file', str, 'The full path of the firmware.', default=None),
      Arg('from_release', bool, 'Find the firmware from release rootfs.',
          default=True),
      Arg(
          'skip_prepvt_flag_check', bool,
          'Skip prepvt flag check. For non-dogfood devcies, '
          'we should always use prod firmware, rather than prepvt one. '
          'A dogfood device can use prod firmware, as long as the board id'
          'setting is correct. The dogfood device will update to the prepvt '
          'firmware when first time boot to recovery image. '
          'http://crbug.com/802235', default=False),
      Arg(
          'method', _METHOD_TYPE,
          'Specify whether to update the Cr50 firmware or to check the '
          'firmware version.', default=_METHOD_TYPE.UPDATE),
      Arg(
          'upstart_mode', bool,
          'Use upstart mode to update Cr50 firmware. The DUT will not reboot '
          'automatically after the update.', default=True),
      Arg(
          'force_ro_mode', bool,
          'Force to update the inactive RO even if the RO version on DUT is '
          'the same as given firmware. The DUT will reboot automatically '
          'after the update', default=False),
      # Since we cannot get the information of which TPM the DUT is using,
      # we need to turn on this flag manually. (b/225943881)
      Arg(
          'is_ti50', bool,
          'If set to true, the test will check the ti50 firmware version '
          'before updating. If the user would like to update from RW 0.0.15 '
          ' (or less) to 0.0.16, then `force_ro_mode` should set to true and '
          '`upstart_mode` should set to false.', default=False),
      Arg(
          'set_recovery_request_train_and_reboot', bool,
          'Set recovery request to VB2_RECOVERY_TRAIN_AND_REBOOT. '
          'For some boards, the device will reboot into recovery mode with '
          'default (v0.0.22) cr50 firmware. Setting this will make the device '
          'update the cr50 firmware and then automatically reboot back to '
          'normal mode after updating cr50 firmware. '
          'See b/154071064 for more details', default=False),
      Arg(
          'check_version_retry_timeout', int,
          'If the version is not matched, retry the check after the specific '
          'seconds.  Set to `0` to disable the retry.', default=10)
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

    dut_shell = functools.partial(gooftool_common.Shell, sys_interface=self.dut)
    self.gsctool = gsctool.GSCTool(shell=dut_shell)
    self.fw_ver = self.gsctool.GetCr50FirmwareVersion()
    self.board_id = self.gsctool.GetBoardID()
    self.image_info = None

  def tearDown(self):
    # Clear the device data for the previous attempt.
    device_data.DeleteDeviceData(KEY_ATTEMPT_CR50_UPDATE_RO_VERSION, True)
    device_data.DeleteDeviceData(KEY_ATTEMPT_CR50_UPDATE_RW_VERSION, True)

  def runTest(self):
    """Update Cr50 firmware."""
    if self.args.firmware_file is None:
      self.assertTrue(
          self.args.from_release,
          'Must set "from_release" to True if not specifiying firmware_file')
      self.args.firmware_file = DEFAULT_FIRMWARE_PATH

    self.assertEqual(self.args.firmware_file[0], '/',
                     'firmware_file should be a full path')

    if phase.GetPhase() >= phase.PVT_DOGFOOD:
      self.assertFalse(
          self.args.skip_prepvt_flag_check,
          'Skipping prePVT flag check is not allowed in PVT or MP builds.')

    self._LogCr50Info()

    if self.args.from_release:
      with sys_utils.MountPartition(
          self.dut.partitions.RELEASE_ROOTFS.path, dut=self.dut) as root:
        self.CacheImageInfoAndCallMethod(
            os.path.join(root, self.args.firmware_file[1:]))
    else:
      if self.dut.link.IsLocal():
        self.CacheImageInfoAndCallMethod(self.args.firmware_file)
      else:
        with self.dut.temp.TempFile() as dut_temp_file:
          self.dut.SendFile(self.args.firmware_file, dut_temp_file)
          self.CacheImageInfoAndCallMethod(dut_temp_file)

  def CacheImageInfoAndCallMethod(self, firmware_file):
    self.image_info = self.gsctool.GetImageInfo(firmware_file)
    if self.args.method == self._METHOD_TYPE.UPDATE:
      self._UpdateCr50Firmware(firmware_file)
    else:
      self._CheckCr50FirmwareVersion()

  def _LogCr50Info(self):
    session.console.info('Cr50 firmware version: %r', self.fw_ver)
    session.console.info('Cr50 board ID: %r', self.board_id)

  def _IsPrePVTFirmware(self):
    logging.info('Cr50 firmware board ID flags: %s',
                 hex(self.image_info.board_id_flags))
    testlog.UpdateParam('board_id_flags',
                        description='Board ID of the firmware image.')
    testlog.LogParam('board_id_flags', self.image_info.board_id_flags)
    return self.image_info.board_id_flags & PREPVT_FLAG_MASK

  def _CompareFirmwareFileVersion(self, strictly_greater=False):
    """Compare if current cr50 version is newer or equal to the FW file.

    Args:
      strictly_greater: If set to true, then the current cr50 version should
        be strictly greater than the given FW file.
    """

    testlog.UpdateParam('expected_ro_fw_version',
                        description='The expected RO FW version.')
    testlog.UpdateParam('expected_rw_fw_version',
                        description='The expected RW FW version.')
    testlog.UpdateParam('ro_fw_version', description='The RO FW version.')
    testlog.UpdateParam('rw_fw_version', description='The RW FW version.')
    testlog.LogParam('expected_ro_fw_version', self.image_info.ro_fw_version)
    testlog.LogParam('expected_rw_fw_version', self.image_info.rw_fw_version)
    testlog.LogParam('ro_fw_version', self.fw_ver.ro_version)
    testlog.LogParam('rw_fw_version', self.fw_ver.rw_version)

    for name in ('ro', 'rw'):
      actual = getattr(self.fw_ver, name + '_version')
      expect = getattr(self.image_info, name + '_fw_version')
      if version.StrictVersion(actual) < version.StrictVersion(expect):
        session.console.info('%s FW version is old (actual=%r, expect=%r)',
                             name.upper(), actual, expect)
        return False
      if (strictly_greater and
          version.StrictVersion(actual) == version.StrictVersion(expect)):
        session.console.info(
            'The FW versions of the given FW and the chip are the same: %r',
            expect)
        return False

    return True


  def _CheckVersionRetry(self, check_version_func, *check_version_args):
    """Check if current Cr50 version is new enough, with a retry timeout.

    Args:
      check_version_func: A function that returns True when Cr50 version is new
                          enough.
      check_version_args: Argument passed to `check_version_func`.
    """

    def _Check():
      if not check_version_func(*check_version_args):
        raise type_utils.TestFailure('Cr50 firmware is old.')

    try:
      _Check()
    except type_utils.TestFailure:
      if self.args.check_version_retry_timeout <= 0:
        raise
      self.ui.SetState('Version is old, sleep for %d seconds and re-check.' %
                       self.args.check_version_retry_timeout)
      self.Sleep(self.args.check_version_retry_timeout)
      _Check()

  def _ValidateTi50FirmwareVersion(self):
    """Validate if we are allowed to update with the given FW file.

    The ti50 FW cannot be upgraded directly from RW version 0.0.15 (or less) to
    0.0.16+ since the FW size is different. We need to perform two stages
    upgrade for ti50: (1) upgrade to 0.0.15 then (2) upgrade to 0.0.16+.
    We need to run (1) and (2) twice respectively (4 times in total) since we
    have two slots of RO and RW FW. (RO_A, RO_B and RW_A, RW_B). Moreover, we
    need to update the ti50 FW with `gsctool -q` option (force_ro_mode) so that
    the inactive RO will be updated even if the version of the given file is
    the same as the version on the chip.
    """
    actual = getattr(self.fw_ver, 'rw' + '_version')
    expect = getattr(self.image_info, 'rw' + '_fw_version')

    if (version.StrictVersion(actual) < version.StrictVersion('0.0.15') and
        version.StrictVersion(expect) >= version.StrictVersion('0.0.16')):
      # RW FW version on DUT is < 0.0.15 and the user try to upgrade to
      # 0.0.16+. This is not allowed and we should upgrade to 0.0.15 first.
      self.FailTask('Please upgrade to RW 0.0.15 first before upgrading '
                    'to 0.0.16+. Current: %r' % self.fw_ver)

    if version.StrictVersion(actual) <= version.StrictVersion('0.0.15'):
      if not self.args.force_ro_mode or self.args.upstart_mode:
        self.FailTask('Please turn on the `force_ro_mode` flag and turn off '
                      'the `upstart_mode` flag to update the ti50 firmware '
                      'from 0.0.15 (or less) to 0.0.16+.')

  def _UpdateCr50Firmware(self, firmware_file):
    if self._IsPrePVTFirmware():
      if phase.GetPhase() >= phase.PVT_DOGFOOD:
        self.FailTask('PrePVT Cr50 firmware should never be used in PVT.')
      if not self.args.skip_prepvt_flag_check:
        self.FailTask('Cr50 firmware board ID flag is PrePVT.')

    # If device data exists, it means the FW is updated in the last round and
    # the DUT has rebooted.
    has_rebooted = (
        device_data.GetDeviceData(KEY_ATTEMPT_CR50_UPDATE_RO_VERSION)
        is not None and
        device_data.GetDeviceData(KEY_ATTEMPT_CR50_UPDATE_RW_VERSION)
        is not None)

    # `force_ro_mode` will update the RO even if the current RO version is
    # the same as the given firmware, so we require the current version
    # to be strictly greater than the given firmware.
    # After updating, the DUT will reboot and check the version again.
    force_update = self.args.force_ro_mode and not has_rebooted
    if self._CompareFirmwareFileVersion(strictly_greater=force_update):
      session.console.info('Cr50 firmware is up-to-date.')
      return

    # If the DUT has rebooted but the chip version and the given FW version
    # does not match, this means the update failed.
    if has_rebooted:
      self.FailTask('Cr50 firmware is not updated in the previous attempt '
                    '(actual=%r, expect=%r).' % (self.fw_ver, self.image_info))

    if self.args.is_ti50:
      self._ValidateTi50FirmwareVersion()

    msg = 'Update the Cr50 firmware from version %r to %r.' % (self.fw_ver,
                                                               self.image_info)
    self.ui.SetState(msg)
    session.console.info(msg)
    device_data.UpdateDeviceData({
        KEY_ATTEMPT_CR50_UPDATE_RO_VERSION: self.image_info.ro_fw_version,
        KEY_ATTEMPT_CR50_UPDATE_RW_VERSION: self.image_info.rw_fw_version
    })
    if self.args.set_recovery_request_train_and_reboot:
      self.dut.CheckCall('crossystem recovery_request=0xC4')

    update_result = self.gsctool.UpdateCr50Firmware(
        firmware_file, self.args.upstart_mode, self.args.force_ro_mode)
    session.console.info('Cr50 firmware update complete: %s.', update_result)

    # Wait for the chip to reboot itself. Otherwise, the test will trigger
    # tearDone and delete the device data.
    if not self.args.upstart_mode:
      self.WaitTaskEnd()

  def _CheckCr50FirmwareVersion(self):
    self._CheckVersionRetry(self._CompareFirmwareFileVersion)
    session.console.info('Cr50 firmware is up-to-date.')
