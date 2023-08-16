#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Google Factory Tool.

This tool is intended to be used on factory assembly lines.  It
provides all of the Google required test functionality and must be run
on each device as part of the assembly process.
"""

import datetime
import functools
import json
import logging
import os
import pipes
import re
import sys
from tempfile import gettempdir
import threading
import xmlrpc.client

from cros.factory.gooftool.common import ExecFactoryPar
from cros.factory.gooftool.common import Shell
from cros.factory.gooftool import core
from cros.factory.gooftool.core import FactoryProcessEnum
from cros.factory.gooftool.core import Gooftool
from cros.factory.gooftool import report_upload
from cros.factory.gooftool.write_protect_target import CreateWriteProtectTarget
from cros.factory.gooftool.write_protect_target import UnsupportedOperationError
from cros.factory.gooftool.write_protect_target import WriteProtectTargetType
from cros.factory.hwid.v3 import feature_compliance
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.probe.functions import chromeos_firmware
from cros.factory.test import device_data
from cros.factory.test.env import paths
from cros.factory.test import event_log
from cros.factory.test.rules import phase
from cros.factory.test.rules.privacy import FilterDict
from cros.factory.test import state
from cros.factory.test.utils.cbi_utils import CbiEepromWpStatus
from cros.factory.test.utils import gsc_utils
from cros.factory.test.utils import hps_utils
from cros.factory.utils import argparse_utils
from cros.factory.utils.argparse_utils import CmdArg
from cros.factory.utils.argparse_utils import ParseCmdline
from cros.factory.utils.argparse_utils import VERBOSITY_CMD_ARG
from cros.factory.utils.debug_utils import SetupLogging
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils import sys_interface
from cros.factory.utils import sys_utils
from cros.factory.utils import time_utils
from cros.factory.utils.type_utils import Error

from cros.factory.external.chromeos_cli import gsctool
from cros.factory.external.chromeos_cli import vpd


# TODO(tammo): Replace calls to sys.exit with raise Exit, and maybe
# treat that specially (as a smoot exit, as opposed to the more
# verbose output for generic Error).

_global_gooftool = None
_gooftool_lock = threading.Lock()
_has_fpmcu = None
WIPE_IN_PLACE = 'wipe_in_place'


_project_cmd_arg = CmdArg('--project', metavar='PROJECT', default=None,
                          help='Project name to test.')

_hwdb_path_cmd_arg = CmdArg('--hwdb_path', metavar='PATH',
                            default=hwid_utils.GetDefaultDataPath(),
                            help='Path to the HWID database.')

_waive_list_cmd_arg = CmdArg(
    '--waive_list', nargs='*', default=[], metavar='SUBCMD',
    help=('A list of waived checks, separated by whitespace. '
          'Each item should be a sub-command of gooftool. '
          'e.g. "gooftool verify --waive_list verify_tpm clear_gbb_flags".'))

_skip_list_cmd_arg = CmdArg(
    '--skip_list', nargs='*', default=[], metavar='SUBCMD',
    help=('A list of skipped checks, separated by whitespace. '
          'Each item should be a sub-command of gooftool. '
          'e.g. "gooftool verify --skip_list verify_tpm clear_gbb_flags".'))

# TODO(yhong): Replace this argument with `--hwid-material-file` when
# `cros.factory.hwid.v3.hwid_utils` provides methods to parse such file.
_probe_results_cmd_arg = CmdArg(
    '--probe_results', metavar='RESULTS.json',
    help=('Output from "hwid probe" (used instead of probing this system).'))

_hwid_cmd_arg = CmdArg(
    '--hwid', metavar='HWID',
    help='HWID to verify (instead of the currently set HWID of this system).')

_hwid_run_vpd_cmd_arg = CmdArg(
    '--hwid-run-vpd', action='store_true',
    help=('Specify the hwid utility to obtain the vpd data by running the '
          '`vpd` commandline tool.'))

_hwid_vpd_data_file_cmd_arg = CmdArg(
    '--hwid-vpd-data-file', metavar='FILE.json', type=str, default=None,
    help=('Specify the hwid utility to obtain the vpd data from the specified '
          'file.'))

_no_write_protect_cmd_arg = CmdArg(
    '--no_write_protect', action='store_true',
    help='Do not enable firmware write protection.')

_factory_process_cmd_arg = CmdArg(
    '--factory_process', type=str, default=FactoryProcessEnum.FULL,
    help='Set "FULL" if running a full factory process. '
    'Set "TWOSTAGES" for local OEM project or MLB for RMA. '
    'Set "RMA" if in a RMA center.')

_cros_core_cmd_arg = CmdArg(
    '--cros_core', action='store_true',
    help='Finalize for ChromeOS Core devices (may add or remove few test '
         'items. For example, registration codes or firmware bitmap '
         'locale settings).')

_has_ec_pubkey_cmd_arg = CmdArg(
    '--has_ec_pubkey', action='store_true', default=None,
    help='The device has EC public key for EFS and need to run VerifyECKey.')

_enforced_release_channels_cmd_arg = CmdArg(
    '--enforced_release_channels', nargs='*', default=None,
    help='Enforced release image channels.')

_ec_pubkey_path_cmd_arg = CmdArg(
    '--ec_pubkey_path',
    default=None,
    help='Path to public key in vb2 format. Verify EC key with pubkey file.')

_ec_pubkey_hash_cmd_arg = CmdArg(
    '--ec_pubkey_hash',
    default=None,
    help='A string for public key hash. Verify EC key with the given hash.')

_release_rootfs_cmd_arg = CmdArg(
    '--release_rootfs', help='Location of release image rootfs partition.')

_firmware_path_cmd_arg = CmdArg(
    '--firmware_path', help='Location of firmware image partition.')

_shopfloor_url_args_cmd_arg = CmdArg(
    '--shopfloor_url',
    help='Shopfloor server url to be informed when wiping is done. '
         'After wiping, a XML-RPC request will be sent to the '
         'given url to indicate the completion of wiping.')

_station_ip_cmd_arg = CmdArg(
    '--station_ip',
    help='IP of remote station')

_station_port_cmd_arg = CmdArg(
    '--station_port',
    help='Port on remote station')

_wipe_finish_token_cmd_arg = CmdArg(
    '--wipe_finish_token',
    help='Required token when notifying station after wipe finished')

_keep_developer_mode_flag_after_clobber_state_cmd_arg = CmdArg(
    # The argument name is super long because you should never use it by
    # yourself when using command line tools.
    '--keep_developer_mode_flag_after_clobber_state',
    action='store_true', default=None,
    help='After clobber-state, do not delete .developer_mode')

_test_umount_cmd_arg = CmdArg(
    '--test_umount', action='store_true',
    help='(For testing only) Only umount rootfs and stateful partition '
         'instead of running full wiping and cutoff process.')

_rlz_embargo_end_date_offset_cmd_arg = CmdArg(
    '--embargo_offset', type=int, default=7, choices=list(range(7, 15)),
    help='Change the offset of embargo end date, cannot less than 7 days or '
         'more than 14 days.')

_no_ectool_cmd_arg = CmdArg(
    '--no_ectool', action='store_false', dest='has_ectool',
    help='There is no ectool utility so tests rely on ectool should be '
         'skipped.')

_no_generate_mfg_date_cmd_arg = CmdArg(
    '--no_generate_mfg_date', action='store_false', dest='generate_mfg_date',
    help='Do not generate manufacturing date nor write mfg_date into VPD.')

_enable_zero_touch_cmd_arg = CmdArg(
    '--enable_zero_touch', action='store_true',
    help='Set attested_device_id for zero-touch feature.')

_cbi_eeprom_wp_status_cmd_arg = CmdArg(
    '--cbi_eeprom_wp_status', type=str, default=CbiEepromWpStatus.Locked,
    choices=list(CbiEepromWpStatus.__members__),
    help='The expected status of CBI EEPROM after factory mode disabled.')

_is_reference_board_cmd_arg = CmdArg(
    '--is_reference_board', action='store_true', default=False,
    help='Indicating this project is reference board.')

_fast_cmd_arg = CmdArg('--fast', action='store_true',
                       help='use non-secure but faster wipe method.')

_skip_feature_tiering_steps_cmd_arg = CmdArg(
    '--skip_feature_tiering_steps', action='store_true', default=False,
    help='Skip feature flag provisions for legacy project on features.')

_upload_method_cmd_arg = CmdArg(
    '--upload_method',
    metavar='METHOD:PARAM',
    help=(
        'How to perform the upload.  METHOD should be one of {'
        'ftp, factory_server, '
        # The method `shopfloor` actually uploads the report to the umpire
        # server, and this method name made some partners confused. Therefore
        # rename this method to `factory_server`. See b/281573026 and
        # b/281773658.
        'shopfloor (deprecated, use factory_server instead; '
        'see b/281573026 and b/281773658), '
        'ftps, cpfe, smb}.'))

_upload_max_retry_times_arg = CmdArg(
    '--upload_max_retry_times', type=int, default=0,
    help='Number of tries to upload. 0 to retry infinitely.')

_upload_retry_interval_arg = CmdArg('--upload_retry_interval', type=int,
                                    default=None,
                                    help='Retry interval in seconds.')

_upload_allow_fail_arg = CmdArg(
    '--upload_allow_fail', action='store_true',
    help='Continue finalize if report upload fails.')

_add_file_cmd_arg = CmdArg(
    '--add_file', metavar='FILE', action='append',
    help='Extra file to include in report (must be an absolute path)')

_boot_to_shimless_cmd_arg = CmdArg(
    '--boot_to_shimless', action='store_true', default=False,
    help='Initiate the Shimless RMA after performing wiping.')


def GetGooftool(options):
  global _global_gooftool  # pylint: disable=global-statement

  if _global_gooftool is None:
    with _gooftool_lock:
      if _global_gooftool is None:
        project = getattr(options, 'project', None)
        hwdb_path = getattr(options, 'hwdb_path', None)
        _global_gooftool = Gooftool(hwid_version=3, project=project,
                                    hwdb_path=hwdb_path)
  return _global_gooftool


# Define __args__ to make it easier to propagate the arguments
GetGooftool.__args__ = (
    _hwdb_path_cmd_arg,
    _project_cmd_arg,
)


def PrepareWipeArgs(options):
  wipe_args = []

  if options.fast:
    wipe_args += ['--fast']
  if options.shopfloor_url:
    wipe_args += ['--shopfloor_url', options.shopfloor_url]
  if options.station_ip:
    wipe_args += ['--station_ip', options.station_ip]
  if options.station_port:
    wipe_args += ['--station_port', options.station_port]
  if options.wipe_finish_token:
    wipe_args += ['--wipe_finish_token', options.wipe_finish_token]
  if options.boot_to_shimless:
    wipe_args += ['--boot_to_shimless']
  if options.skip_list:
    wipe_args += ['--skip_list'] + options.skip_list
  if options.waive_list:
    wipe_args += ['--waive_list'] + options.waive_list
  wipe_args += ['--phase', str(phase.GetPhase())]

  return wipe_args


PrepareWipeArgs.__args__ = (
    _fast_cmd_arg,
    _shopfloor_url_args_cmd_arg,
    _station_ip_cmd_arg,
    _station_port_cmd_arg,
    _wipe_finish_token_cmd_arg,
    _test_umount_cmd_arg,
    _boot_to_shimless_cmd_arg,
)


def HasFpmcu():
  global _has_fpmcu  # pylint: disable=global-statement

  if _has_fpmcu is None:
    FPMCU_PATH = '/dev/cros_fp'
    has_cros_config_fpmcu = False
    cros_config_fp_board = Shell(['cros_config', '/fingerprint', 'board'])
    cros_config_fp_location = Shell(
        ['cros_config', '/fingerprint', 'sensor-location'])
    if (cros_config_fp_board.success and cros_config_fp_board.stdout and
        cros_config_fp_location.success and
        cros_config_fp_location.stdout != 'none'):
      has_cros_config_fpmcu = True

    if not os.path.exists(FPMCU_PATH) and has_cros_config_fpmcu:
      raise Error(f'FPMCU found in cros_config but missing in {FPMCU_PATH}.')

    _has_fpmcu = has_cros_config_fpmcu

  return _has_fpmcu


def CreateReportArchiveBlob(*args, **kwargs):
  """Creates a report archive and returns it as a blob.

  Args:
    See CreateReportArchive.

  Returns:
    An xmlrpc.client.Binary object containing a .tar.xz file.
  """
  report_archive = CreateReportArchive(*args, **kwargs)
  try:
    return xmlrpc.client.Binary(
        file_utils.ReadFile(report_archive, encoding=None))
  finally:
    os.unlink(report_archive)


def CreateReportArchive(device_sn=None, add_file=None):
  """Creates a report archive in a temporary directory.

  Args:
    device_sn: The device serial number (optional).
    add_file: A list of files to add (optional).

  Returns:
    Path to the archive.
  """
  # Flush Testlog data to DATA_TESTLOG_DIR before creating a report archive.
  result, reason = state.GetInstance().FlushTestlog(uplink=False, local=True,
                                                    timeout=10)
  if not result:
    logging.warning('Failed to flush testlog data: %s', reason)

  def NormalizeAsFileName(token):
    return re.sub(r'\W+', '', token).strip()

  target_name = (
      f"{datetime.datetime.utcnow():%Y%m%dT%H%M%SZ}"
      f"{'' if device_sn is None else '_' + NormalizeAsFileName(device_sn)}"
      ".tar.xz")
  target_path = os.path.join(gettempdir(), target_name)

  # Intentionally ignoring dotfiles in EVENT_LOG_DIR.
  tar_cmd = f'cd {event_log.EVENT_LOG_DIR} ; tar cJf {target_path} * -C /'
  tar_files = [paths.FACTORY_LOG_PATH, paths.DATA_TESTLOG_DIR]
  if add_file:
    tar_files = tar_files + add_file
  for f in tar_files:
    # Require absolute paths since we use -C / to change current directory to
    # root.
    if not f.startswith('/'):
      raise Error(f'Not an absolute path: {f}')
    if not os.path.exists(f):
      raise Error(f'File does not exist: {f}')
    tar_cmd += f' {pipes.quote(f[1:])}'
  cmd_result = Shell(tar_cmd)

  if cmd_result.status == 1:
    # tar returns 1 when some files were changed during archiving,
    # but that is expected for log files so should ignore such failure
    # if the archive looks good.
    Spawn(['tar', 'tJf', target_path], check_call=True, log=True,
          ignore_stdout=True)
  elif not cmd_result.success:
    raise Error(f'unable to tar event logs, cmd {tar_cmd!r} failed, stderr: '
                f'{cmd_result.stderr!r}')

  return target_path


def Command(cmd_name, *args, **kwargs):
  """Decorator for commands in gooftool.

  This is similar to argparse_utils.Command, but all gooftool commands
  can be waived during `gooftool finalize` or `gooftool verify` using
  --waive_list or --skip_list option.
  """
  args = args + (_skip_list_cmd_arg, _waive_list_cmd_arg)

  def Decorate(fun):

    @functools.wraps(fun)
    def CommandWithWaiveSkipCheck(options):
      waive_list = vars(options).get('waive_list', [])
      skip_list = vars(options).get('skip_list', [])
      if phase.GetPhase() >= phase.PVT_DOGFOOD and (waive_list != [] or
                                                    skip_list != []):
        raise Error('waive_list and skip_list should be empty for phase '
                    f'{phase.GetPhase()}')

      if cmd_name not in skip_list:
        try:
          fun(options)
        except Exception as e:
          if cmd_name in waive_list:
            logging.exception(e)
          else:
            raise

    wrapped = argparse_utils.Command(cmd_name, *args, **kwargs)(
        CommandWithWaiveSkipCheck)
    wrapped.__args__ = args
    return wrapped

  return Decorate


@Command('get_release_fs_type', *GetGooftool.__args__)
def GetReleaseFSType(options):
  """Get the FS type of the stateful partition of the release image."""

  if GetGooftool(options).IsReleaseLVM():
    print('Release image has LVM stateful partition.')
  else:
    print('Release image has EXT4 stateful partition.')


@Command(
    'write_hwid',
    CmdArg('hwid', metavar='HWID', help='HWID string'),  # this
    *GetGooftool.__args__)
def WriteHWID(options):
  """Write specified HWID value into the system BB."""

  logging.info('writing hwid string %r', options.hwid)
  GetGooftool(options).WriteHWID(options.hwid)
  event_log.Log('write_hwid', hwid=options.hwid)
  print(f'Wrote HWID: {options.hwid!r}')


@Command('read_hwid', *GetGooftool.__args__)
def ReadHWID(options):
  """Read the HWID string from GBB."""

  logging.info('reading the hwid string')
  print(GetGooftool(options).ReadHWID())


@Command('verify_dlc_images', *GetGooftool.__args__)
def VerifyDLCImages(options):
  """Verify the hash of the factory installed DLC."""
  return GetGooftool(options).VerifyDLCImages()


@Command(
    'verify_ec_key',
    _ec_pubkey_path_cmd_arg,  # this
    _ec_pubkey_hash_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyECKey(options):
  """Verify EC key."""
  return GetGooftool(options).VerifyECKey(
      options.ec_pubkey_path, options.ec_pubkey_hash)


@Command('verify_fp_key', *GetGooftool.__args__)
def VerifyFpKey(options):
  """Verify fingerprint firmware key."""
  return GetGooftool(options).VerifyFpKey()


@Command(
    'verify_keys',
    _release_rootfs_cmd_arg,  # this
    _firmware_path_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyKeys(options):
  """Verify keys in firmware and SSD match."""
  return GetGooftool(options).VerifyKeys(
      options.release_rootfs, options.firmware_path)


@Command('set_fw_bitmap_locale', *GetGooftool.__args__)
def SetFirmwareBitmapLocale(options):
  """Use VPD locale value to set firmware bitmap default language."""

  (index, locale) = GetGooftool(options).SetFirmwareBitmapLocale()
  logging.info('Firmware bitmap initial locale set to %d (%s).',
               index, locale)


@Command(
    'verify_system_time',
    _release_rootfs_cmd_arg,  # this
    _factory_process_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifySystemTime(options):
  """Verify system time is later than release filesystem creation time."""

  return GetGooftool(options).VerifySystemTime(
      options.release_rootfs, factory_process=options.factory_process)


@Command(
    'verify_rootfs',
    _release_rootfs_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyRootFs(options):
  """Verify rootfs on SSD is valid by checking hash."""

  return GetGooftool(options).VerifyRootFs(options.release_rootfs)


@Command('verify_tpm', *GetGooftool.__args__)
def VerifyTPM(options):
  """Verify TPM is cleared."""

  return GetGooftool(options).VerifyTPM()


@Command('verify_me_locked', *GetGooftool.__args__)
def VerifyManagementEngineLocked(options):
  """Verify Management Engine is locked."""

  return GetGooftool(options).VerifyManagementEngineLocked()


@Command(
    'verify_switch_wp',
    _no_ectool_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyWPSwitch(options):
  """Verify hardware write protection switch is enabled."""

  GetGooftool(options).VerifyWPSwitch(options.has_ectool)


@Command('verify_vpd', *GetGooftool.__args__)
def VerifyVPD(options):
  """Verify that VPD values are properly set.

  Check if mandatory fields are set, and deprecated fields don't exist.
  """
  ro_vpd = vpd.VPDTool().GetAllData(partition=vpd.VPD_READONLY_PARTITION_NAME)
  rw_vpd = vpd.VPDTool().GetAllData(partition=vpd.VPD_READWRITE_PARTITION_NAME)
  event_log.Log('vpd', ro=FilterDict(ro_vpd), rw=FilterDict(rw_vpd))
  return GetGooftool(options).VerifyVPD()


@Command(
    'verify_release_channel',
    _enforced_release_channels_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyReleaseChannel(options):
  """Verify that release image channel is correct.

  ChromeOS has four channels: canary, dev, beta and stable.
  The last three channels support image auto-updates, checks
  that release image channel is one of them.
  """
  return GetGooftool(options).VerifyReleaseChannel(
      options.enforced_release_channels)


@Command('verify_rlz_code', *GetGooftool.__args__)
def VerifyRLZCode(options):
  """Verify RLZ code is not 'ZZCR' in/after EVT."""
  return GetGooftool(options).VerifyRLZCode()


@Command('verify_cros_config', *GetGooftool.__args__)
def VerifyCrosConfig(options):
  """Verify entries in cros config make sense."""
  return GetGooftool(options).VerifyCrosConfig()


@Command(
    'verify_sn_bits',
    _enable_zero_touch_cmd_arg,  # this
    _factory_process_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifySnBits(options):
  rma_mode = options.factory_process == FactoryProcessEnum.RMA
  if options.enable_zero_touch and not rma_mode:
    GetGooftool(options).VerifySnBits()


@Command(
    'verify_cbi_eeprom_wp_status',
    _cbi_eeprom_wp_status_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyCBIEEPROMWPStatus(options):
  """Verify CBI EEPROM status.

  If cbi_eeprom_wp_status is Absent, CBI EEPROM must be absent. If
  cbi_eeprom_wp_status is Locked, write protection must be on. Otherwise, write
  protection must be off.
  """

  return GetGooftool(options).VerifyCBIEEPROMWPStatus(
      options.cbi_eeprom_wp_status)


@Command('verify_alt_setting', *GetGooftool.__args__)
def VerifyAltSetting(options):
  """Verify the usb alt setting for RTL8852CE."""
  return GetGooftool(options).VerifyAltSetting()


@Command(
    'write_protect',
    CmdArg('--operation', default='enable',
           choices=['enable', 'disable', 'show'], help='operation to perform'),
    CmdArg('--targets', nargs='+', default=['all'],
           choices=['all'] + [member.name for member in WriteProtectTargetType],
           help='targets to perform on'),
    CmdArg(
        '--skip_enable_check', action='store_true',
        help='skip the expected failure check of disabling software write '
        'protect after enabling the write protect'),
)
def WriteProtect(options):
  """Enable/Disable/Show the firmware software write protection."""
  options.targets = set(options.targets)
  if 'all' in options.targets:
    options.targets = set(WriteProtectTargetType)
  else:
    options.targets = set(
        WriteProtectTargetType[name] for name in options.targets)

  target_order = []
  if HasFpmcu():
    target_order += [WriteProtectTargetType.FPMCU]
  target_order += [
      WriteProtectTargetType.AP,
      WriteProtectTargetType.EC,
  ]

  targets = [target for target in target_order if target in options.targets]

  if options.operation == 'show':
    status = {}
    for target in targets:
      wp_target = CreateWriteProtectTarget(target)
      try:
        status[target.name] = wp_target.GetStatus()
      except UnsupportedOperationError:
        logging.warning('Cannot get write protection status for %s.',
                        target.name)
    print(json.dumps(status, indent=2))
  else:
    for target in targets:
      wp_target = CreateWriteProtectTarget(target)
      try:
        wp_target.SetProtectionStatus(options.operation == 'enable',
                                      options.skip_enable_check)
      except UnsupportedOperationError:
        logging.warning('Cannot %s write protection on %s.', options.operation,
                        target.name)
      else:
        if options.operation == 'enable':
          event_log.Log('wp', fw=target.value)


@Command('lock_hps')
def LockHPS(options):
  """Enable permanent write-protection of the HPS.

  Once this is done, it can never be undone short of removing the MCU and
  soldering on a new one.
  """
  del options
  logging.warning(
      'Enable permanent write-protection of the HPS. Once this is done, it '
      'can never be undone short of removing the MCU and soldering on a new '
      'one.')
  hps = hps_utils.HPSDevice(dut=sys_interface.SystemInterface())
  hps.EnableWriteProtection()


@Command('clear_gbb_flags', *GetGooftool.__args__)
def ClearGBBFlags(options):
  """Zero out the GBB flags, in preparation for transition to release state.

  No GBB flags are set in release/shipping state, but they are useful
  for factory/development.  See "futility gbb --flags" for details.
  """
  gbb_flags_in_factory = GetGooftool(options).GetGBBFlags()
  GetGooftool(options).ClearGBBFlags()
  event_log.Log('clear_gbb_flags', old_value=gbb_flags_in_factory)


@Command('clear_factory_vpd_entries', *GetGooftool.__args__)
def ClearFactoryVPDEntries(options):
  """Clears factory.* items in the RW VPD."""
  entries = GetGooftool(options).ClearFactoryVPDEntries()
  event_log.Log('clear_factory_vpd_entries', entries=FilterDict(entries))


@Command('clear_unknown_vpd_entries', *GetGooftool.__args__)
def ClearUnknownVPDEntries(options):
  """Clears unknown RW VPDs, which are VPDs not in py/gooftool/vpd_data.py."""
  entries = GetGooftool(options).ClearUnknownVPDEntries()
  event_log.Log('clear_unknown_vpd_entries', entries=FilterDict(entries))


@Command('generate_stable_device_secret', *GetGooftool.__args__)
def GenerateStableDeviceSecret(options):
  """Generates a fresh stable device secret and stores it in the RO VPD."""
  GetGooftool(options).GenerateStableDeviceSecret()
  event_log.Log('generate_stable_device_secret')


@Command(
    'gsc_write_flash_info',
    _enable_zero_touch_cmd_arg,  # this
    _no_write_protect_cmd_arg,  # this
    _factory_process_cmd_arg,  # this
    _skip_feature_tiering_steps_cmd_arg,  # this
    *GetGooftool.__args__)
def GSCWriteFlashInfo(options):
  """Set the serial number bits, board id and flags on the GSC chip."""
  GetGooftool(options).GSCWriteFlashInfo(
      enable_zero_touch=options.enable_zero_touch,
      factory_process=options.factory_process,
      skip_feature_tiering_steps=options.skip_feature_tiering_steps,
      no_write_protect=options.no_write_protect)
  event_log.Log('gsc_write_flash_info')


@Command('cr50_write_flash_info', *GSCWriteFlashInfo.__args__)
def Cr50WriteFlashInfo(options):
  """Deprecated: Use |GSCWriteFlashInfo| instead."""
  GSCWriteFlashInfo(options)


@Command('gsc_disable_factory_mode', *GetGooftool.__args__)
def GSCDisableFactoryMode(options):
  """Reset GSC state back to default state after RMA."""
  return GetGooftool(options).GSCDisableFactoryMode()


@Command('cr50_disable_factory_mode', *GSCDisableFactoryMode.__args__)
def Cr50DisableFactoryMode(options):
  """Deprecated: Use |GSCDisableFactoryMode| instead."""
  return GSCDisableFactoryMode(options)


@Command(
    'gsc_finalize',
    *GSCDisableFactoryMode.__args__,
    *GSCWriteFlashInfo.__args__,
    *GetGooftool.__args__,
)
def GSCFinalize(options):
  """Finalize steps for GSC."""

  GSCWriteFlashInfo(options)
  GSCDisableFactoryMode(options)


@Command(
    'cr50_finalize',
    *GSCFinalize.__args__,
)
def Cr50Finalize(options):
  """Deprecated: Use |GSCFinalize| instead."""
  GSCFinalize(options)


@Command(
    'enable_release_partition',
    _release_rootfs_cmd_arg,  # this
    *GetGooftool.__args__)
def EnableReleasePartition(options):
  """Enables a release image partition on the disk."""
  GetGooftool(options).EnableReleasePartition(options.release_rootfs)


@Command(
    WIPE_IN_PLACE,
    _fast_cmd_arg,  # this
    _shopfloor_url_args_cmd_arg,  # this
    _station_ip_cmd_arg,  # this
    _station_port_cmd_arg,  # this
    _wipe_finish_token_cmd_arg,  # this
    _boot_to_shimless_cmd_arg,  # this
    _test_umount_cmd_arg,  # this
    *GetGooftool.__args__,
)
def WipeInPlace(options):
  """Start factory wipe directly without reboot."""

  GetGooftool(options).WipeInPlace(
      options.fast, options.shopfloor_url, options.station_ip,
      options.station_port, options.wipe_finish_token, options.boot_to_shimless,
      options.test_umount)


@Command(
    'wipe_init',
    CmdArg('--wipe_args', help='arguments for clobber-state'),  # this
    CmdArg('--state_dev', help='path to stateful partition device'),  # this
    CmdArg('--root_disk', help='path to primary device'),  # this
    CmdArg('--old_root', help='path to old root'),  # this
    _shopfloor_url_args_cmd_arg,  # this
    _release_rootfs_cmd_arg,  # this
    _station_ip_cmd_arg,  # this
    _station_port_cmd_arg,  # this
    _wipe_finish_token_cmd_arg,  # this
    _keep_developer_mode_flag_after_clobber_state_cmd_arg,  # this
    _boot_to_shimless_cmd_arg,  # this
    _test_umount_cmd_arg,  # this
    *GetGooftool.__args__)
def WipeInit(options):
  GetGooftool(options).WipeInit(
      options.wipe_args, options.shopfloor_url, options.state_dev,
      options.release_rootfs, options.root_disk, options.old_root,
      options.station_ip, options.station_port, options.wipe_finish_token,
      options.keep_developer_mode_flag_after_clobber_state,
      options.boot_to_shimless, options.test_umount)


@Command(
    'verify_feature_management_flags',
    _factory_process_cmd_arg,  # this
    _skip_feature_tiering_steps_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyFeatureManagementFlags(options):
  """Verify the flags for feature managements.

  This command verifies:
  1. (is_chassis_branded, hw_compliance_version) stored correctly in device
     data, indicating the pytest branded_chassis and feature_compliance_version
     passed.
  2. hw_compliance_version computed from HWID string matches
     hw_compliance_version stored in device data.
  """

  if options.skip_feature_tiering_steps:
    logging.info('Legacy device, skip GRT.VerifyFeatureManagementFlags.')
    return

  chassis_branded_device_data = device_data.GetDeviceData(
      device_data.KEY_FM_CHASSIS_BRANDED)
  hw_compliance_version_device_data = device_data.GetDeviceData(
      device_data.KEY_FM_HW_COMPLIANCE_VERSION)

  incorrect_pytest_error_msg = []
  if chassis_branded_device_data is None:
    msg = (f'{device_data.KEY_FM_CHASSIS_BRANDED} is not in device data.'
           'Run `branded_chassis` pytest to set it.')
    incorrect_pytest_error_msg.append(msg)

  if hw_compliance_version_device_data is None:
    msg = (f'{device_data.KEY_FM_HW_COMPLIANCE_VERSION} is not in device data.'
           'Run `feature_compliance_version` pytest to set it.')
    incorrect_pytest_error_msg.append(msg)

  if incorrect_pytest_error_msg:
    incorrect_pytest_str = '\n'.join(incorrect_pytest_error_msg)
    raise Error(incorrect_pytest_str)

  hwid_string = GetGooftool(options).ReadHWID()
  database = GetGooftool(options).db
  hwid_dir = hwid_utils.GetDefaultDataPath()

  identity, unused_bom, unused_configless = hwid_utils.DecodeHWID(
      database, hwid_string)

  checker = feature_compliance.LoadChecker(hwid_dir,
                                           hwid_utils.ProbeProject().upper())
  hw_compliance_version_checker = checker.CheckFeatureComplianceVersion(
      identity)

  # TODO(stevesu) We should refactor this function to a Verifier class to
  # have better flow control and cleaner code.
  rma_mode = options.factory_process == FactoryProcessEnum.RMA
  if (rma_mode and gsc_utils.GSCUtils().IsGSCFeatureManagementFlagsLocked()):
    feature_flags = gsctool.GSCTool().GetFeatureManagementFlags()
    # In RMA scene, when GSC feature flags already set, we let (False, 0)
    # bypass compliance version verification for the checker part, as no
    # matter it is actually (False, 0) or (False, n), we can always enable
    # feature by soft-branding. Overwrite it with the one in GSC.
    if feature_flags == gsctool.FeatureManagementFlags(False, 0):
      hw_compliance_version_checker = feature_flags.hw_compliance_version

  if hw_compliance_version_device_data != hw_compliance_version_checker:
    raise Error(
        'HW compliance version set for device '
        f'({hw_compliance_version_device_data}) differs the one calculated '
        f'with the compliance checker ({hw_compliance_version_checker}) '
        'from HWID data.')

  if chassis_branded_device_data:
    if (hw_compliance_version_checker ==
        feature_compliance.FEATURE_INCOMPLIANT_VERSION):
      raise Error(f'Chassis branded HW compliance version '
                  f'({hw_compliance_version_checker}) incorrect, should not '
                  'be incompliant version: '
                  f'({feature_compliance.FEATURE_INCOMPLIANT_VERSION}).')


@Command(
    'verify_hwid',
    _probe_results_cmd_arg,  # this
    _hwid_cmd_arg,  # this
    _hwid_run_vpd_cmd_arg,  # this
    _hwid_vpd_data_file_cmd_arg,  # this
    _factory_process_cmd_arg,  # this
    *GetGooftool.__args__)
def VerifyHWID(options):
  """A simple wrapper that calls out to HWID utils to verify version 3 HWID.

  This is mainly for Gooftool to verify v3 HWID during finalize.  For testing
  and development purposes, please use `hwid` command.
  """
  ignore_errors = False
  if hps_utils.HasHPS():
    # We cannot probe HPS after HWWP is enabled.
    try:
      # If has_ectool is set, the VerifyWPSwitch will test SWWP (firmware
      # software write protection). Skip testing SWWP with has_ectool=False.
      GetGooftool(options).VerifyWPSwitch(has_ectool=False)
    except core.HWWPError:
      logging.info('HWWP is disabled as expected.')
    else:
      logging.info(
          'Ignore HWID verification failure, because HPS cannot be probed when'
          ' HWWP is enabled.')
      ignore_errors = True

  database = GetGooftool(options).db

  encoded_string = options.hwid or GetGooftool(options).ReadHWID()

  probed_results = hwid_utils.GetProbedResults(infile=options.probe_results)
  device_info = hwid_utils.GetDeviceInfo()
  vpd_data = hwid_utils.GetVPDData(run_vpd=options.hwid_run_vpd,
                                   infile=options.hwid_vpd_data_file)

  event_log.Log('probed_results', probed_results=FilterDict(probed_results))

  try:
    hwid_utils.VerifyHWID(database, encoded_string, probed_results, device_info,
                          vpd_data,
                          options.factory_process == FactoryProcessEnum.RMA)
  except Exception:
    # TODO(cyueh) Make this only accept HPS HWID validation error.
    if not ignore_errors:
      raise
    logging.exception(
        'Failed to verify HWID but it is fine since we believe that the device '
        'passed VerifyHWID once before GSCFinalize.')

  event_log.Log('verified_hwid', hwid=encoded_string)


@Command(
    'verify_before_gsc_finalize',
    _no_write_protect_cmd_arg,  # this
    _has_ec_pubkey_cmd_arg,  # this
    _is_reference_board_cmd_arg,  # this
    *GetGooftool.__args__,
    *VerifyAltSetting.__args__,
    *VerifyCrosConfig.__args__,
    *VerifyDLCImages.__args__,
    *VerifyECKey.__args__,
    *VerifyFpKey.__args__,
    *VerifyHWID.__args__,
    *VerifyKeys.__args__,
    *VerifyManagementEngineLocked.__args__,
    *VerifyRLZCode.__args__,
    *VerifyReleaseChannel.__args__,
    *VerifyRootFs.__args__,
    *VerifySystemTime.__args__,
    *VerifyTPM.__args__,
    *VerifyVPD.__args__,
    *VerifyFeatureManagementFlags.__args__,
)
def VerifyBeforeGSCFinalize(options):
  """Verifies if the device is ready for finalization before GSCFinalize.

  This routine performs all the necessary checks to make sure the device is
  ready to be finalized before GSCFinalize, but does not modify state.
  """
  VerifyAltSetting(options)
  if not options.no_write_protect:
    VerifyManagementEngineLocked(options)
  VerifyHWID(options)
  VerifyFeatureManagementFlags(options)
  VerifySystemTime(options)
  if options.has_ec_pubkey:
    VerifyECKey(options)
  if HasFpmcu():
    VerifyFpKey(options)
  VerifyKeys(options)
  VerifyRootFs(options)
  VerifyDLCImages(options)
  VerifyTPM(options)
  VerifyVPD(options)
  VerifyReleaseChannel(options)
  if not options.is_reference_board:
    VerifyRLZCode(options)
  VerifyCrosConfig(options)


@Command(
    'verify_before_cr50_finalize',
    *VerifyBeforeGSCFinalize.__args__,
)
def VerifyBeforeCr50Finalize(options):
  """Deprecated: Use |VerifyBeforeGSCFinalize| instead."""
  VerifyBeforeGSCFinalize(options)


@Command(
    'verify_after_gsc_finalize',
    _no_write_protect_cmd_arg,  # this
    *GetGooftool.__args__,
    *VerifySnBits.__args__,
    *VerifyWPSwitch.__args__,
)
def VerifyAfterGSCFinalize(options):
  """Verifies if the device is ready for finalization after GSCFinalize.

  This routine performs all the necessary checks to make sure the device is
  ready to be finalized after GSCFinalize, but does not modify state.
  """
  if not options.no_write_protect:
    VerifyWPSwitch(options)
  VerifySnBits(options)


@Command(
    'verify_after_cr50_finalize',
    *VerifyAfterGSCFinalize.__args__,
)
def VerifyAfterCr50Finalize(options):
  """Deprecated: Use |VerifyAfterGSCFinalize| instead."""
  VerifyAfterGSCFinalize(options)


@Command('untar_stateful_files')
def UntarStatefulFiles(options):
  """Untars stateful files from stateful_files.tar.xz on stateful partition.

  If that file does not exist (which should only be R30 and earlier),
  this is a no-op.
  """
  del options
  # Path to stateful partition on device.
  device_stateful_path = '/mnt/stateful_partition'
  tar_file = os.path.join(device_stateful_path, 'stateful_files.tar.xz')
  if os.path.exists(tar_file):
    Spawn(['tar', 'xf', tar_file], cwd=device_stateful_path,
          log=True, check_call=True)
  else:
    logging.warning('No stateful files at %s', tar_file)


@Command('log_source_hashes')
def LogSourceHashes(options):
  """Logs hashes of source files in the factory toolkit."""
  del options  # Unused.
  # WARNING: The following line is necessary to validate the integrity
  # of the factory software.  Do not remove or modify it.
  #
  # 警告：此行会验证工厂软件的完整性，禁止删除或修改。
  factory_par = sys_utils.GetRunningFactoryPythonArchivePath()
  if factory_par:
    event_log.Log(
        'source_hashes',
        **file_utils.HashPythonArchive(factory_par))
  else:
    event_log.Log(
        'source_hashes',
        **file_utils.HashSourceTree(os.path.join(paths.FACTORY_DIR, 'py')))


@Command('log_system_details', *GetGooftool.__args__)
def LogSystemDetails(options):
  """Write miscellaneous system details to the event log."""

  event_log.Log('system_details', **GetGooftool(options).GetSystemDetails())


@Command('upload_report',
         _upload_method_cmd_arg,
         _upload_max_retry_times_arg,
         _upload_retry_interval_arg,
         _upload_allow_fail_arg,
         _add_file_cmd_arg)
def UploadReport(options):
  """Create a report containing key device details."""
  ro_vpd = vpd.VPDTool().GetAllData(partition=vpd.VPD_READONLY_PARTITION_NAME)
  device_sn = ro_vpd.get('serial_number', None)
  if device_sn is None:
    logging.warning('RO_VPD missing device serial number')
    device_sn = 'MISSING_SN_' + time_utils.TimedUUID()
  target_path = CreateReportArchive(device_sn, options.add_file)

  if options.upload_method is None or options.upload_method == 'none':
    logging.warning('REPORT UPLOAD SKIPPED (report left at %s)', target_path)
    return
  method, param = options.upload_method.split(':', 1)

  if options.upload_retry_interval is not None:
    retry_interval = options.upload_retry_interval
  else:
    retry_interval = report_upload.DEFAULT_RETRY_INTERVAL

  if method == 'shopfloor':
    logging.warning(
        'The method "shopfloor" has been deprecated and is renamed to '
        '"factory_server". Now continuing with the method "factory_server". '
        'See b/281573026 and b/281773658 for more information.')
    method = 'factory_server'

  if method == 'factory_server':
    report_upload.FactoryServerUpload(
        target_path, param,
        'GRT' if options.command_name == 'finalize' else None,
        max_retry_times=options.upload_max_retry_times,
        retry_interval=retry_interval, allow_fail=options.upload_allow_fail)
  elif method == 'ftp':
    report_upload.FtpUpload(target_path, 'ftp:' + param,
                            max_retry_times=options.upload_max_retry_times,
                            retry_interval=retry_interval,
                            allow_fail=options.upload_allow_fail)
  elif method == 'ftps':
    report_upload.CurlUrlUpload(target_path, f'--ftp-ssl-reqd ftp:{param}',
                                max_retry_times=options.upload_max_retry_times,
                                retry_interval=retry_interval,
                                allow_fail=options.upload_allow_fail)
  elif method == 'cpfe':
    report_upload.CpfeUpload(target_path, pipes.quote(param),
                             max_retry_times=options.upload_max_retry_times,
                             retry_interval=retry_interval,
                             allow_fail=options.upload_allow_fail)
  elif method == 'smb':
    # param should be in form: <dest_path>.
    report_upload.SmbUpload(target_path, 'smb:' + param,
                            max_retry_times=options.upload_max_retry_times,
                            retry_interval=retry_interval,
                            allow_fail=options.upload_allow_fail)
  else:
    raise Error(f'unknown report upload method {method!r}')


@Command('fpmcu_initialize_entropy', *GetGooftool.__args__)
def FpmcuInitializeEntropy(options):
  """Initialize entropy of FPMCU."""

  if HasFpmcu():
    GetGooftool(options).FpmcuInitializeEntropy()
  else:
    logging.info('No FPS on this board.')


@Command(
    'smt_finalize',
    *GetGooftool.__args__,
    *LogSourceHashes.__args__,
    *LogSystemDetails.__args__,
    *UploadReport.__args__,
    *PrepareWipeArgs.__args__,
)
def SMTFinalize(options):
  """Call this function to finalize MLB in SMT stage.

  This is required if the MLB will leave factory after SMT stage, such as RMA
  spare boards, local OEM projects.
  """

  GetGooftool(options).GSCSMTWriteFlashInfo()
  event_log.Log('gsc_smt_write_flash_info')
  LogSourceHashes(options)
  LogSystemDetails(options)
  UploadReport(options)

  if options.boot_to_shimless:
    event_log.Log(WIPE_IN_PLACE)
    wipe_args = PrepareWipeArgs(options)

    ExecFactoryPar('gooftool', WIPE_IN_PLACE, *wipe_args)


@Command(
    'finalize',
    _factory_process_cmd_arg,  # this
    _rlz_embargo_end_date_offset_cmd_arg,  # this
    _no_generate_mfg_date_cmd_arg,  # this
    _cros_core_cmd_arg,  # this
    _no_write_protect_cmd_arg,  # this
    _skip_list_cmd_arg,  # this
    *PrepareWipeArgs.__args__,
    *ClearFactoryVPDEntries.__args__,
    *ClearGBBFlags.__args__,
    *GSCFinalize.__args__,
    *WriteProtect.__args__,
    *FpmcuInitializeEntropy.__args__,
    *GenerateStableDeviceSecret.__args__,
    *GetGooftool.__args__,
    *LockHPS.__args__,
    *LogSourceHashes.__args__,
    *LogSystemDetails.__args__,
    *SetFirmwareBitmapLocale.__args__,
    *UntarStatefulFiles.__args__,
    *UploadReport.__args__,
    *VerifyAfterGSCFinalize.__args__,
    *VerifyBeforeGSCFinalize.__args__,
    *VerifyCBIEEPROMWPStatus.__args__,
)
def Finalize(options):
  """Verify system readiness and trigger transition into release state.

  This routine does the following:
  - Verifies system state (see verify command)
  - Untars stateful_files.tar.xz, if it exists, in the stateful partition, to
    initialize files such as the CRX cache
  - Modifies firmware bitmaps to match locale
  - Clears all factory-friendly flags from the GBB
  - Removes factory-specific entries from RW_VPD (factory.*)
  - Enables firmware write protection (cannot rollback after this)
  - Initialize Fpmcu entropy
  - Uploads system logs & reports
  - Wipes the testing kernel, rootfs, and stateful partition
  """

  if options.factory_process != FactoryProcessEnum.RMA:
    # Write VPD values related to RLZ ping into VPD.
    GetGooftool(options).WriteVPDForRLZPing(options.embargo_offset)
    if options.generate_mfg_date:
      GetGooftool(options).WriteVPDForMFGDate()

  if hps_utils.HasHPS():
    if not options.no_write_protect:
      # We cannot lock HPS after HWWP is enabled.
      LockHPS(options)

  ClearGBBFlags(options)
  VerifyBeforeGSCFinalize(options)
  GSCFinalize(options)
  VerifyAfterGSCFinalize(options)
  LogSourceHashes(options)
  UntarStatefulFiles(options)
  if options.cros_core:
    logging.info('SetFirmwareBitmapLocale is skipped for ChromeOS Core device.')
  else:
    SetFirmwareBitmapLocale(options)
  ClearFactoryVPDEntries(options)
  GenerateStableDeviceSecret(options)
  if options.no_write_protect:
    logging.warning('WARNING: Firmware Software Write Protection is SKIPPED.')
    event_log.Log('wp', fw='both', status='skipped')
  else:
    WriteProtect(options)
  VerifyCBIEEPROMWPStatus(options)
  FpmcuInitializeEntropy(options)
  LogSystemDetails(options)
  UploadReport(options)

  event_log.Log(WIPE_IN_PLACE)
  wipe_args = PrepareWipeArgs(options)

  ExecFactoryPar('gooftool', WIPE_IN_PLACE, *wipe_args)


@Command('get_firmware_hash',
         CmdArg('--file', required=True, metavar='FILE', help='Firmware File.'))
def GetFirmwareHash(options):
  """Get firmware hash from a file"""
  if os.path.exists(options.file):
    value_dict = chromeos_firmware.CalculateFirmwareHashes(options.file)
    for key, value in value_dict.items():
      print(f'  {key}: {value}')
  else:
    raise Error(f'File does not exist: {options.file}')


@Command('get_smart_amp_info', *GetGooftool.__args__)
def GetSmartAmpInfo(options):
  """Get the information about the smart amplifier."""
  speaker_amp, sound_card_init_path, channels = \
    GetGooftool(options).GetSmartAmpInfo()
  if speaker_amp:
    print('Amplifier name:', speaker_amp)
  if sound_card_init_path:
    print('Sound card init conf path:', sound_card_init_path)
    print('Channels:', channels)
    print('The DUT has a smart amplifier.')
  else:
    print('The DUT doesn\'t have a smart amplifier.')


@Command('get_logical_block_size', *GetGooftool.__args__)
def GetLogicalBlockSize(options):
  """Get the logical block size of the primary device on DUT."""
  print('Logical block size:', GetGooftool(options).GetLogicalBlockSize())


@Command(
    'ti50_set_spi_data',
    _no_write_protect_cmd_arg,  # this
    *GetGooftool.__args__)
def Ti50SetSPIData(options):
  """Sets the ti50 addressing mode and wpsr."""
  gsc_utils.GSCUtils().Ti50ProvisionSPIData(options.no_write_protect)


def main():
  """Run sub-command specified by the command line args."""

  options = ParseCmdline(
      'Perform Google required factory tests.',
      CmdArg('-l', '--log', metavar='PATH',
             help='Write logs to this file.'),
      CmdArg('--suppress-event-logs', action='store_true',
             help='Suppress event logging.'),
      CmdArg('--phase', default=None,
             help=('override phase for phase checking (defaults to the current '
                   'as returned by the "factory phase" command)')),
      VERBOSITY_CMD_ARG)
  SetupLogging(options.verbosity, options.log)
  event_log.SetGlobalLoggerDefaultPrefix('gooftool')
  event_log.GetGlobalLogger().suppress = options.suppress_event_logs
  logging.debug('gooftool options: %s', repr(options))

  phase.OverridePhase(options.phase)
  try:
    logging.debug('GOOFTOOL command %r', options.command_name)
    options.command(options)
    logging.info('GOOFTOOL command %r SUCCESS', options.command_name)
  except Error as e:
    logging.exception(e)
    sys.exit(f'GOOFTOOL command {options.command_name!r} ERROR: {e}')
  except Exception as e:
    logging.exception(e)
    sys.exit(f'UNCAUGHT RUNTIME EXCEPTION {e}')


if __name__ == '__main__':
  main()
