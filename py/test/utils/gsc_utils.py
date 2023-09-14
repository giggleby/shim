# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from distutils.version import LooseVersion
import enum
import logging
import os
import re

from cros.factory.gooftool import gbb
from cros.factory.probe.functions import flash_chip
from cros.factory.test import device_data
from cros.factory.test.env import paths
from cros.factory.test.rules import phase
from cros.factory.test.utils import model_sku_utils
from cros.factory.utils import file_utils
from cros.factory.utils import interval
from cros.factory.utils import sys_interface
from cros.factory.utils import type_utils

from cros.factory.external.chromeos_cli import cros_config
from cros.factory.external.chromeos_cli import flashrom
from cros.factory.external.chromeos_cli import futility
from cros.factory.external.chromeos_cli import gsctool
from cros.factory.external.chromeos_cli.gsctool import FeatureManagementFlags
from cros.factory.external.chromeos_cli import shell
from cros.factory.external.chromeos_cli import vpd


class GSCScriptPath(str, enum.Enum):
  GSC_CONSTANTS = '/usr/share/cros/gsc-constants.sh'
  BOARD_ID = '/usr/share/cros/hwsec-utils/cr50_set_board_id'
  SN_BITS = '/usr/share/cros//hwsec-utils/cr50_set_sn_bits'
  FACTORY_CONFIG = '/usr/share/cros/hwsec-utils/cr50_set_factory_config'
  AP_RO_HASH = '/usr/local/bin/ap_ro_hash.py'

  def __str__(self):
    return self.value

class GSCUtilsError(type_utils.Error):
  """All errors when processing GSC related logic."""


class GSCUtils:
  """GSC related logic and implementation."""

  def __init__(self, gsc_constants_path=GSCScriptPath.GSC_CONSTANTS, dut=None):
    self.gsc_constants_path = gsc_constants_path
    self._dut = dut if dut else sys_interface.SystemInterface()
    self._shell = shell.Shell(dut=self._dut)
    self._gsctool = gsctool.GSCTool(dut=self._dut)
    self._futility = futility.Futility(dut=self._dut)
    self._vpd = vpd.VPDTool(dut=self._dut)

  def _GetConstant(self, constant_name):
    file_utils.CheckPath(self.gsc_constants_path)
    res = self._shell(f'. "{self.gsc_constants_path}"; "{constant_name}"')
    if res.success:
      return res.stdout.strip()
    raise GSCUtilsError(f'Fail to load constant: {constant_name}')

  @type_utils.LazyProperty
  def name(self):
    return self._GetConstant('gsc_name')

  @type_utils.LazyProperty
  def image_base_name(self):
    return self._GetConstant('gsc_image_base_name')

  @type_utils.LazyProperty
  def metrics_prefix(self):
    return self._GetConstant('gsc_metrics_prefix')

  # TODO(phoebewang): Remove the workaround once there's way to distinguish the
  # GSC.
  def IsTi50(self):
    """Checks if the device is using DT.
    Currently, there's no way to distinguish between H1 and DT.
    As a workaround, we read the file `gsc-constants.sh` to get the information
    of GSC. This file is generated in build time according to the USE flag.
    If both cr50_onboard and ti50_onboard are presented, then we assume the
    board is using DT.
    """
    return self.name == 'ti50'

  # TODO(jasonchuang): Check with gsc team if we really need to add -D.
  def GetGSCToolCmd(self):
    GSCTOOL_PATH = '/usr/sbin/gsctool'
    gsctool_cmd = [GSCTOOL_PATH]
    if self.IsTi50():
      gsctool_cmd.append('-D')
    return gsctool_cmd

  def IsGSCFieldLocked(self) -> bool:
    """Check if fields GSC is unable to modified.

    In Ti50, check the initial factory mode bit.
    In Cr50, check the board ID type.
    With different implementation, some fields can still be provisioned if
    empty. Check the doc for the details.
    https://chromeos.google.com/partner/dlm/docs/factory/setting-gsc-factory-process.html

    Returns:
      `True` if the write operation to GSC is locked.
    """

    if self.IsTi50():
      return not self._gsctool.IsTi50InitialFactoryMode()
    return self._gsctool.IsGSCBoardIdTypeSet()

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
    feature_flags = self._gsctool.GetFeatureManagementFlags()
    if feature_flags != FeatureManagementFlags(False, 0):
      return True

    return self.IsGSCFieldLocked()

  def VerifySnBits(self):
    # Add '-n' to dry run.
    result = self._shell([GSCScriptPath.SN_BITS, '-n'])
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    logging.info('status: %d', result.status)
    logging.info('stdout: %s', stdout)
    logging.info('stderr: %s', stderr)

    if result.status != 0:
      # Fail reason, either:
      # - attested_device_id is not set
      # - SN bits has been set differently
      # cr50-set-sn-bits.sh prints errors on stdout instead of stderr.
      raise GSCUtilsError(stdout)

    if 'This device has been RMAed' in stdout:
      logging.warning('SN Bits cannot be set anymore.')
      return

    if 'SN Bits have not been set yet' in stdout:
      if 'BoardID is set' in stdout:
        logging.warning('SN Bits cannot be set anymore.')

  def Cr50ClearROHash(self):
    if self.IsGSCFieldLocked():
      logging.warning('GSC fields is locked. Skip clearing RO hash.')
      return
    if not self._gsctool.IsCr50ROHashSet():
      logging.info('AP-RO hash is already cleared, do nothing.')
      return

    self._gsctool.ClearROHash()
    logging.info('Successfully clear AP-RO hash on Cr50.')

  def Cr50SetROHashForShipping(self):
    """Calculate and set the hash as in release/shipping state.

    Since the hash range includes GBB flags, we need to calculate hash with
    the same GBB flags as in release/shipping state.
    We might not want to clear GBB flags in early phase, so we need to clear it
    explicitly in this function.
    """

    gbb_flags_in_factory = self._futility.GetGBBFlags()
    self._futility.SetGBBFlags(0)
    try:
      self.Cr50SetROHash()
    finally:
      self._futility.SetGBBFlags(gbb_flags_in_factory)

  def Cr50SetROHash(self):
    """Sets the AP-RO hash on the Cr50 chip.

    Cr50 after 0.5.5 and 0.6.5 supports RO verification, which needs the factory
    to write the RO hash to Cr50 before setting board ID.
    """
    # If board ID is set, we cannot set RO hash. This happens when a device
    # reflows in the factory and goes through finalization twice.
    # TODO(chenghan): Check if the RO hash range in cr50 is the same as what
    #                 we want to set, after this feature is implemented in cr50.
    #                 Maybe we can bind it with `GSCSetBoardId`.
    if self.IsGSCFieldLocked():
      logging.warning('GSC fields is locked. Skip setting RO hash.')
      return

    # We cannot set AP-RO hash if it's already set, so always try to clear it
    # before we set the AP-RO hash.
    self.Cr50ClearROHash()

    # ap_ro_hash.py takes offset:size in hex as range parameters.
    hash_intervals = self._CalculateHashInterval()
    self.ExecuteGSCSetScript(
        GSCScriptPath.AP_RO_HASH,
        ' '.join([(f'{i.start:x}:{i.size:x}') for i in hash_intervals]))

  def _CalculateHashInterval(self):
    firmware_image = flashrom.LoadMainFirmware().GetFirmwareImage()
    ro_offset, ro_size = firmware_image.get_section_area('RO_SECTION')
    ro_vpd_offset, ro_vpd_size = firmware_image.get_section_area('RO_VPD')
    gbb_offset, gbb_size = firmware_image.get_section_area('GBB')
    gbb_content = gbb.UnpackGBB(firmware_image.get_blob(), gbb_offset)
    hwid = gbb_content.hwid
    hwid_digest = gbb_content.hwid_digest

    # Calculate address intervals of
    # RO_SECTION + GBB - RO_VPD - HWID - HWID_DIGEST.
    include_intervals = [
        interval.Interval(ro_offset, ro_offset + ro_size),
        interval.Interval(gbb_offset, gbb_offset + gbb_size)
    ]
    exclude_intervals = [
        interval.Interval(ro_vpd_offset, ro_vpd_offset + ro_vpd_size),
        interval.Interval(hwid.offset, hwid.offset + hwid.size),
        interval.Interval(hwid_digest.offset,
                          hwid_digest.offset + hwid_digest.size)
    ]
    hash_intervals = interval.MergeAndExcludeIntervals(include_intervals,
                                                       exclude_intervals)

    # Cr50 cannot store hash intervals with size larger than 4MB.
    return sum([interval.SplitInterval(i, 0x400000) for i in hash_intervals],
               [])

  def GSCSetSnBits(self):
    """Sets the serial number bits on the GSC chip.

    Serial number bits along with the board id allow a device to attest to its
    identity and participate in Chrome OS Zero-Touch.

    A script located at /usr/share/cros/cr50-set-sn-bits.sh helps us
    to set the proper serial number bits in the GSC chip.
    """

    vpd_key = 'attested_device_id'
    has_vpd_key = self._vpd.GetValue(vpd_key) is not None

    # The script exists, Zero-Touch is enabled.
    if not has_vpd_key:
      # TODO(stimim): What if Zero-Touch is enabled on a program (e.g. hatch),
      # but not expected for a project (e.g. kohaku).
      raise GSCUtilsError(f'Zero-Touch is enabled, but {vpd_key!r} is not set')

    self.ExecuteGSCSetScript(GSCScriptPath.SN_BITS)

  def GSCSetFeatureManagementFlagsWithHwSecUtils(self, chassis_branded: bool,
                                                 hw_compliance_version: int):
    """Leverages HwSec utils to set feature management flags.

    According to https://crrev.com/c/4483473, the return codes of
    /usr/share/cros/hwsec-utils/cr50_set_factory_config are
      0: Success
      1: General Error
      2: Config Already Set Error

    Args:
      chassis_branded: chassis_branded set in device data.
      hw_compliance_version: hw_compliance_version set in device data.

    Raises:
      `cros.factory.utils.type_utils.Error` if fails.
    """

    args = [str(chassis_branded).lower(), str(hw_compliance_version)]
    self.ExecuteGSCSetScript(GSCScriptPath.FACTORY_CONFIG, args)

  def GSCSetFeatureManagementFlags(self):
    """ Sets the feature management flags to GSC.

    Please be noted that this is a write-once operation.
    For details, please refer to b/275356839.

    Raises:
      `cros.factory.utils.type_utils.Error` if cr50_set_factory_config fails.
      `GSCToolError` if GSC tool fails.
    """

    chassis_branded = device_data.GetDeviceData(
        device_data.KEY_FM_CHASSIS_BRANDED)
    hw_compliance_version = device_data.GetDeviceData(
        device_data.KEY_FM_HW_COMPLIANCE_VERSION)
    feature_flags = self._gsctool.GetFeatureManagementFlags()

    # In RMA scene, in cases where the feature flags unchanged,
    # we shouldn't try to set it, otherwise the finalize will fail.
    # By default the feature flags should be (False, 0) in raw bit form,
    # so it is also safe not setting it at all.
    if (feature_flags.is_chassis_branded == chassis_branded and
        feature_flags.hw_compliance_version == hw_compliance_version):
      return

    # If the DUT has HwSec utils, we should prioritize using it.
    try:
      self.GSCSetFeatureManagementFlagsWithHwSecUtils(chassis_branded,
                                                      hw_compliance_version)
    except IOError:
      self._gsctool.SetFeatureManagementFlags(chassis_branded,
                                              hw_compliance_version)

  def GSCSetBoardId(self, two_stages, is_flags_only=False):
    """Sets the board id and flags on the GSC chip.

    The GSC image need to be lock down for a certain subset of devices for
    security reason. To achieve this, we need to tell the GSC which board
    it is running on, and which phase is it, during the factory flow.

    A script located at /usr/share/cros/cr50-set-board-id.sh helps us
    to set the board id and phase to the GSC chip.

    To the detail design of the lock-down mechanism, please refer to
    go/cr50-boardid-lock for more details.

    Args:
      two_stages: The MLB part is sent to a different location for assembly,
          such as RMA or local OEM. And we need to set a different board ID
          flags in this case.
      is_flags_only: Set board ID flags only, this should only be true in the
          first stage in a two stages project. The board ID type still should be
          set in the second stage.
    """

    if phase.GetPhase() >= phase.PVT_DOGFOOD:
      arg_phase = 'pvt'
    else:
      arg_phase = 'dev'

    mode = arg_phase
    if two_stages:
      mode = 'two_stages_' + mode
      if is_flags_only:
        mode += '_flags'

    if not is_flags_only:
      self._VerifyBrandCode()
    self.ExecuteGSCSetScript(GSCScriptPath.BOARD_ID, mode)

  def _VerifyBrandCode(self):
    """Makes sure brand code is consistent between RO_GSCVD and cros_config.

    To prevent setting wrong Board ID type, which makes AP RO verification fail.
    """
    firmware_image = flashrom.LoadMainFirmware().GetFirmwareImage()
    gscvd = firmware_image.get_section('RO_GSCVD')

    # Need to reverse since the byte string should be read in little endian.
    # The brand code is stored at the 12~15 bytes.
    brand_code_in_gscvd = gscvd[12:16][::-1].decode('utf-8')
    brand_code_in_cros_config = cros_config.CrosConfig(
        dut=self._dut).GetBrandCode()

    if brand_code_in_gscvd != brand_code_in_cros_config:
      raise GSCUtilsError(f'The brand code in RO_GSCVD {brand_code_in_gscvd}'
                          ' is different from the brand code in cros_config '
                          f'{brand_code_in_cros_config}.')

  # TODO(jasonchuang) Add unit tests for better coverage
  def GSCDisableFactoryMode(self):
    """Disables GSC Factory mode.

    GSC factory mode might be enabled in the factory and RMA center in order to
    open ccd capabilities. Before finalizing the DUT, factory mode MUST be
    disabled.
    """

    def _IsCCDInfoMandatory():
      gsc_version = self._gsctool.GetGSCFirmwareVersion().rw_version
      # If second number is odd in version then it is prod version.
      is_prod = int(gsc_version.split('.')[1]) % 2

      res = True
      if is_prod and LooseVersion(gsc_version) < LooseVersion('0.3.9'):
        res = False
      elif not is_prod and LooseVersion(gsc_version) < LooseVersion('0.4.5'):
        res = False

      return res

    try:
      try:
        self._gsctool.SetFactoryMode(False)
        factory_mode_disabled = True
      except gsctool.GSCToolError:
        factory_mode_disabled = False

      if not _IsCCDInfoMandatory():
        logging.warning(
            'Command of disabling factory mode %s and can not get '
            'CCD info so there is no way to make sure factory mode '
            'status. GSC version RW %s',
            'succeeds' if factory_mode_disabled else 'fails',
            self._gsctool.GetGSCFirmwareVersion().rw_version)
        return

      is_factory_mode = self._gsctool.IsFactoryMode()

    except gsctool.GSCToolError as e:
      raise GSCUtilsError(f'gsctool command fail: {e!r}') from None

    except Exception as e:
      raise GSCUtilsError(f'Unknown exception from gsctool: {e!r}') from None

    if is_factory_mode:
      raise GSCUtilsError('Failed to disable GSC factory mode.')

  def Ti50ProvisionSPIData(self, no_write_protect):
    self.Ti50SetAddressingMode()
    self.Ti50SetSWWPRegister(no_write_protect)

  def Ti50SetAddressingMode(self):
    """Sets addressing mode for ap ro verification on Ti50."""

    self._gsctool.SetAddressingMode(self._futility.GetFlashSize())

  def Ti50SetSWWPRegister(self, no_write_protect):
    """Sets wpsr for ap ro verification on Ti50.

    If write protect is enabled, the wpsr should be derived from ap_wpsr.
    Otherwise, set zero to ask Ti50 to ignore the write protect status.
    """
    if no_write_protect:
      wpsr = '0 0'
    else:
      wp_conf = self._futility.GetWriteProtectInfo()
      flash_name = self.GetFlashName()
      cmd = [
          'ap_wpsr', f'--name={flash_name}', f'--start={wp_conf["start"]}',
          f'--length={wp_conf["length"]}'
      ]
      res = self._shell(cmd).stdout
      logging.info('WPSR: %s', res)
      match = re.search(r'SR Value\/Mask = (.+)', res)
      if match:
        wpsr = match[1]
      else:
        raise GSCUtilsError(f'Fail to parse the wpsr from ap_wpsr tool {res}')
    self._gsctool.SetWpsr(wpsr)

  def GetFlashName(self):
    """Probes the flash chip for ap_wpsr tool to derive wpsr.

    If there's any ambiguity, we need to config a mapping in
    spi_flash_transform manually.
    """
    probe_result = flash_chip.FlashChipFunction.ProbeDevices('internal')
    flash_name = probe_result.get('name') or probe_result.get('partname')

    # Reads `.../factory/py/test/pytests/model_sku.json`
    # for 'spi_flash_transform' information.
    model_sku_config_path = os.path.join(paths.FACTORY_DIR, 'py', 'test',
                                         'pytests')
    sku_config = model_sku_utils.GetDesignConfig(
        self._dut, default_config_dirs=model_sku_config_path,
        config_name='model_sku')
    if 'spi_flash_transform' in sku_config and flash_name in sku_config[
        'spi_flash_transform']:
      new_flash_name = sku_config['spi_flash_transform'][flash_name]
      logging.info('Transform flash name from "%s" to "%s".', flash_name,
                   new_flash_name)
      flash_name = new_flash_name

    logging.info('Flash name: %s', flash_name)
    return flash_name

  def ExecuteGSCSetScript(self, path: GSCScriptPath, args=''):
    name = path.name
    file_utils.CheckPath(path)
    if isinstance(args, str):
      cmd = [path, args]
    elif isinstance(args, list):
      cmd = [path] + args

    p = phase.GetPhase()
    result = self._shell(cmd)
    if result.status == 0:
      logging.info('Successfully set %s on GSC with `%s`.', name, ' '.join(cmd))
    elif result.status == 2:
      logging.error('%s has already been set on GSC!', name)
    elif result.status == 3:
      error_msg = f'{name} has been set DIFFERENTLY on GSC!'
      if p <= phase.DVT:
        logging.error(error_msg)
      else:
        raise GSCUtilsError(error_msg)
    else:  # General errors.
      raise GSCUtilsError(
          f"Failed to set {name} on GSC. (cmd=`{' '.join(cmd)}`)")
