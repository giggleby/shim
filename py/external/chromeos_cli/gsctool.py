# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import re

from cros.factory.utils.gsc_utils import GSCUtils
from cros.factory.utils import type_utils

from cros.factory.external.chromeos_cli import shell


# Path to the relied `gsctool` command line utility.
GSCTOOL_PATH = '/usr/sbin/gsctool'


class FirmwareVersion(type_utils.Obj):

  def __init__(self, ro_version, rw_version):
    super().__init__(ro_version=ro_version, rw_version=rw_version)


class ImageInfo(type_utils.Obj):

  def __init__(self, ro_fw_version, rw_fw_version, board_id_flags):
    super().__init__(ro_fw_version=ro_fw_version, rw_fw_version=rw_fw_version,
                     board_id_flags=board_id_flags)


class BoardID(type_utils.Obj):

  def __init__(self, type_, flags):
    super().__init__(type=type_, flags=flags)


class UpdateResult(str, enum.Enum):
  NOOP = 'NOOP'
  ALL_UPDATED = 'ALL_UPDATED'
  RW_UPDATED = 'RW_UPDATED'

  def __str__(self) -> str:
    return self.name


class FeatureManagementFlags(type_utils.Obj):

  def __init__(self, is_chassis_branded_: bool, hw_compliance_version_: int):
    super().__init__(is_chassis_branded=is_chassis_branded_,
                     hw_compliance_version=hw_compliance_version_)


class APROResult(enum.Enum):
  # ref: platform/cr50/include/ap_ro_integrity_check.h
  # Results of cr50.
  AP_RO_NOT_RUN = 0
  AP_RO_PASS = 1
  AP_RO_FAIL = 2
  AP_RO_UNSUPPORTED_UNKNOWN = 3  # Deprecated
  AP_RO_UNSUPPORTED_NOT_TRIGGERED = 4
  AP_RO_UNSUPPORTED_TRIGGERED = 5

  # V2 results of ti50.
  AP_RO_V2_SUCCESS = 20
  AP_RO_V2_FAILED_VERIFICATION = 21
  AP_RO_V2_INCONSISTENT_GSCVD = 22
  AP_RO_V2_INCONSISTENT_KEYBLOCK = 23
  AP_RO_V2_INCONSISTENT_KEY = 24
  AP_RO_V2_SPI_READ = 25
  AP_RO_V2_UNSUPPORTED_CRYPTO_ALGORITHM = 26
  AP_RO_V2_VERSION_MISMATCH = 27
  AP_RO_V2_OUT_OF_MEMORY = 28
  AP_RO_V2_INTERNAL = 29
  AP_RO_V2_TOO_BIG = 30
  AP_RO_V2_MISSING_GSCVD = 31
  AP_RO_V2_BOARD_ID_MISMATCH = 32
  AP_RO_V2_SETTING_NOT_PROVISIONED = 33
  AP_RO_V2_NON_ZERO_GBB_FLAGS = 36
  AP_RO_V2_WRONG_ROOT_KEY = 37
  AP_RO_V2_UNKNOWN = 255


class GSCToolError(Exception):
  pass


class GSCTool:
  """Helper class to operate on GSC firmware by the `gsctool` cmdline utility.
  """

  def __init__(self, dut=None):
    self._shell = shell.Shell(dut)

  def ClearInactiveGSCSlot(self):
    """Clears the inactive GSC RW slot."""
    cmd = [GSCTOOL_PATH, '-a', '-c']
    self._InvokeCommand(cmd, 'failed to clear inactive GSC slot.')

  def GetGSCFirmwareVersion(self):
    """Get the version of the current GSC firmware.

    Returns:
      Instance of `FirmwareVersion`.

    Raises:
      `GSCToolError` if fails.
    """
    cmd = [GSCTOOL_PATH, '-M', '-a', '-f']
    return self._GetAttrs(cmd, FirmwareVersion, {
        'RO_FW_VER': 'ro_version',
        'RW_FW_VER': 'rw_version'
    }, 'firmware versions.')

  def UpdateCr50Firmware(self, image_file, upstart_mode=True,
                         force_ro_mode=False):
    """Update the Cr50 firmware.

    Args:
      image_file: Path to the image file that contains the cr50 firmware image.
      upstart_mode: Use upstart mode.
      force_ro_mode: Force to update the inactive RO.

    Returns:
      Enum element of `UpdateResult` if succeeds.

    Raises:
      `GSCToolError` if update fails.
    """
    cmd = [GSCTOOL_PATH, '-a']
    if force_ro_mode:
      cmd += ['-q']
    if upstart_mode:
      cmd += ['-u']
    cmd += [image_file]

    # 0: noop. 1: all_updated, 2: rw_updated, 3: update_error
    # See platform/ec/extra/usb_updater/gsctool.h for more detail.
    cmd_result_checker = lambda result: 0 <= result.status <= 2
    cmd_result = self._InvokeCommand(cmd, 'Failed to update Cr50 firmware',
                                     cmd_result_checker=cmd_result_checker)
    return {
        0: UpdateResult.NOOP,
        1: UpdateResult.ALL_UPDATED,
        2: UpdateResult.RW_UPDATED
    }[cmd_result.status]

  def GetImageInfo(self, image_file):
    """Get the version and the board id of the specified Cr50 firmware image.

    Args:
      image_file: Path to the Cr50 firmware image file.

    Returns:
      Instance of `ImageVersion`.

    Raises:
      `GSCToolError` if fails.
    """
    cmd = [GSCTOOL_PATH, '-M', '-b', image_file]
    info = self._GetAttrs(
        cmd, ImageInfo, {
            'IMAGE_RO_FW_VER': 'ro_fw_version',
            'IMAGE_RW_FW_VER': 'rw_fw_version',
            'IMAGE_BID_FLAGS': 'board_id_flags'
        }, 'image versions.')
    # pylint: disable=attribute-defined-outside-init
    info.board_id_flags = int(info.board_id_flags, 16)
    return info

  def _GetAttrs(self, cmd, AttrClass, fields, target_name):
    cmd_result = self._InvokeCommand(cmd, f'failed to get {target_name}')

    translated_kwargs = {}
    for line in cmd_result.stdout.splitlines():
      line = line.strip()
      for field_name, attr_name in fields.items():
        if line.startswith(field_name + '='):
          translated_kwargs[attr_name] = line[len(field_name) + 1:]
    missing_fields = [
        field_name for field_name, attr_name in fields.items()
        if attr_name not in translated_kwargs
    ]
    if missing_fields:
      raise GSCToolError(
          f'{missing_fields!r} Field(s) are missing, gsctool stdout='
          f'{cmd_result.stdout!r}')

    return AttrClass(**translated_kwargs)

  def SetFactoryMode(self, enable):
    """Enable or disable the cr50 factory mode.

    Args:
      enable: `True` to enable the factory mode;  `False` to disable the
          factory mode.

    Raises:
      `GSCToolError` if fails.
    """
    enable_str = 'enable' if enable else 'disable'
    cmd = [GSCTOOL_PATH, '-a', '-F', enable_str]
    self._InvokeCommand(cmd, f'failed to {enable_str} cr50 factory mode')

  def IsFactoryMode(self):
    """Queries if the cr50 is in factory mode or not.

    Returns:
      `True` if it's in factory mode.

    Raises:
      `GSCToolError` if fails.
    """
    result = self._InvokeCommand([GSCTOOL_PATH, '-a', '-I'],
                                 'getting ccd info fails in cr50')

    # The pattern of output is as below in case of factory mode enabled:
    # State: Locked
    # Password: None
    # Flags: 000000
    # Capabilities, current and default:
    #   ...
    # Capabilities are modified.
    #
    # If factory mode is disabed then the last line would be
    # Capabilities are default.
    return bool(
        re.search('^Capabilities are modified.$', result.stdout, re.MULTILINE))

  def GetBoardID(self):
    """Get the board ID of the Cr50 firmware.

    Returns:
      Instance of `BoardID`.

    Raises:
      `GSCToolError` if fails.
    """
    _BID_TYPE_MASK = 0xffffffff

    result = self._GetAttrs(
        [GSCTOOL_PATH, '-a', '-M', '-i'], type_utils.Obj,
        {k: k
         for k in ('BID_TYPE', 'BID_TYPE_INV', 'BID_FLAGS', 'BID_RLZ')},
        'board ID')
    if result.BID_RLZ == '????':
      rlz_num = 0xffffffff
      result.BID_RLZ = None
    elif re.fullmatch(r'[A-Z]{4}', result.BID_RLZ):
      rlz_num = int.from_bytes(result.BID_RLZ.encode('utf-8'), 'big')
    else:
      raise GSCToolError(f'Unexpected RLZ format: {result.BID_RLZ!r}.')
    try:
      bid_type = int(result.BID_TYPE, 16)
      bid_type_inv = int(result.BID_TYPE_INV, 16)
      bid_flags = int(result.BID_FLAGS, 16)
    except Exception as e:
      raise GSCToolError(e) from None

    # The output of the gsctool command contains 4 fields, check if they are
    # not conflicted to each other.
    is_bid_type_programmed = (
        bid_type != _BID_TYPE_MASK or bid_type_inv != _BID_TYPE_MASK)
    is_bid_type_complement = ((bid_type & bid_type_inv) == 0 and
                              (bid_type | bid_type_inv) == _BID_TYPE_MASK)
    if is_bid_type_programmed and not is_bid_type_complement:
      raise GSCToolError(
          f'BID_TYPE({bid_type:x}) and BID_TYPE_INV({bid_type_inv:x}) are not '
          'complement to each other')
    if rlz_num != bid_type:
      raise GSCToolError(
          f'BID_TYPE({bid_type:x}) and RLZ_CODE({result.BID_RLZ}) mismatch.')
    return BoardID(bid_type, bid_flags)

  def ClearROHash(self):
    """Clear the AP-RO hash in Cr50."""
    self._InvokeCommand([GSCTOOL_PATH, '-a', '-H'],
                        'Failed to clear the AP-RO hash.')

  # TODO(stevesu): Refactor this function to make adding new flag/mask easy.
  def EncodeFeatureManagementBits(self, chassis_branded: bool,
                                  hw_compliance_version: int) -> str:
    """Encodes the factory config hex string from feature management flags.

    According to b/275356839, factory configs can now be stored in GSC INFO
    page with 64 bit length. The lower 5 bits are now allocated to the
    feature management flags. The function constructs the raw 64 bit hex string
    input for the later GSC command call.

    Args:
      chassis_branded: Chassis branded feature flag (bool)
      hw_compliance_version: Compliance version of the feature (int)

    Returns:
      64 bit hex string.
    """
    factory_config = (((chassis_branded & 0x1) << 4) |
                      (hw_compliance_version & 0xF))
    return f'{factory_config:016x}'

  def ParseFeatureManagementConfigs(self,
                                    feature_config) -> FeatureManagementFlags:
    """Parse the feature config from gsctool -a --factory_config output.

    Example factory_config output:
      raw_value: 0000000000000000
      chassis_x_branded: false
      hw_x_compliance_version: 01

    Args:
      feature_config: The output string from from gsctool -a --factory_config.

    Returns:
      `FeatureManagementFlags` instance.

    Raises:
      `GSCToolError` if the output cannot be correctly parsed.
    """
    chassis_pattern = r'chassis_x_branded: (true|false)'
    hw_compliance_version_pattern = r'hw_x_compliance_version: (\d{2})'

    match_chassis = re.search(chassis_pattern, feature_config, re.MULTILINE)
    if not match_chassis:
      raise GSCToolError('Unable to parse chassis_x_branded from output.')

    match_compliance_version = re.search(hw_compliance_version_pattern,
                                         feature_config, re.MULTILINE)
    if not match_compliance_version:
      raise GSCToolError('Unable to parse hw_x_compliance_version from output.')

    chassis_branded = match_chassis.group(1) == 'true'
    hw_compliance_version = int(match_compliance_version.group(1), 16)
    return FeatureManagementFlags(chassis_branded, hw_compliance_version)

  def SetFeatureManagementFlags(self, chassis_branded: bool,
                                hw_compliance_version: int):
    """Sets the feature config chassis_branded and hw_compliance_version.

    Raises:
      `GSCToolError` if fails.
      `TypeError` if the input argument type incorrect.
      `ValueError` if `hw_compliance_version` is not within valid 4 bit range.
    """

    if not isinstance(chassis_branded, bool):
      raise TypeError('chassis_branded should be bool type.')
    if not isinstance(hw_compliance_version, int):
      raise TypeError('hw_compliance_version should be int type.')
    if isinstance(hw_compliance_version, bool):
      # Add this because bool is sub-type of int.
      raise TypeError('hw_compliance_version should be int type, not boolean.')
    if hw_compliance_version > 0xF:
      raise ValueError('hw_compliance_version should be a 4 bit integer.')

    feature_bits = self.EncodeFeatureManagementBits(chassis_branded,
                                                    hw_compliance_version)
    self._InvokeCommand([GSCTOOL_PATH, '-a', '--factory_config', feature_bits],
                        'Failed to set feature flags.')

  def GetFeatureManagementFlags(self) -> FeatureManagementFlags:
    """Gets the chassis_branded and hw_compliance_version feature flags.

    Returns:
      `FeatureManagementFlags` instance.

    Raises:
      `GSCToolError` if fails.
    """
    result = self._InvokeCommand([GSCTOOL_PATH, '-a', '--factory_config'],
                                 'Failed to get feature flags.')
    return self.ParseFeatureManagementConfigs(result.stdout)

  def _IsGSCBoardIdSet(self) -> bool:
    """A simpler implementation of `IsGSCBoardIDSet` in gooftool.Core."""
    # TODO(stevesu): The current formal way of checking BoardID is to leverage
    # `Gooftool.Core.IsGSCBoardIDSet()` however this complicates the whole
    # issue as when probing we shouldn't care about the correctness of
    # the RLZ code. Requires a refactor to make `IsGSCBoardIDSet` in
    # gooftool.Core leverages this function.
    try:
      board_id = self.GetBoardID()
    except GSCToolError as e:
      raise RuntimeError(
          f'Failed to get boardID with gsctool command: {e!r}') from None
    return board_id.type != 0xffff_ffff

  def IsGSCFeatureManagementFlagsLocked(self) -> bool:
    """Check if GSC feature management flags locked to write operation.

    GSC is locked to feature management flags write operation if:
      1. It has been written once already, or
      2. the chip is Cr50 and Board ID is set, or
      3. the chip is Ti50 and initial factory mode is disabled.

    This function checks if the above case is true.

    Returns:
      `True` if the write operation to GSC is locked.
    """

    # Flags already been set.
    feature_flags = self.GetFeatureManagementFlags()
    if feature_flags != FeatureManagementFlags(False, 0):
      return True

    # Write locked after board ID set / initial factory mode disabled.
    if GSCUtils().IsTi50():
      # TODO(stevesu) The write operation for Ti50 is actually locked when the
      # chip left the initial factory mode. However currently we don't have an
      # OS level API to probe for initial factory mode, only Ti50 console
      # command `sysinfo`. Discussion is being made with b/286998283 and before
      # the API is ready we can only use `IsFactoryMode` as an approximation.
      return not self.IsFactoryMode()
    return self._IsGSCBoardIdSet()

  def _InvokeCommand(self, cmd, failure_msg, cmd_result_checker=None):
    cmd_result_checker = cmd_result_checker or (lambda result: result.success)
    result = self._shell(cmd)
    if not cmd_result_checker(result):
      raise GSCToolError(failure_msg + f' (command result: {result!r})')
    return result
