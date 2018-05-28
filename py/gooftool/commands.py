#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Google Factory Tool.

This tool is intended to be used on factory assembly lines.  It
provides all of the Google required test functionality and must be run
on each device as part of the assembly process.
"""

import logging
import os
import pipes
import re
import sys
from tempfile import gettempdir
import threading
import time
import xmlrpclib

import yaml

import factory_common  # pylint: disable=unused-import
from cros.factory.gooftool.common import ExecFactoryPar
from cros.factory.gooftool.common import Shell
from cros.factory.gooftool.core import Gooftool
from cros.factory.gooftool import crosfw
from cros.factory.gooftool.probe import CalculateFirmwareHashes
from cros.factory.gooftool.probe import Probe
from cros.factory.gooftool.probe import ReadRoVpd
from cros.factory.gooftool import report_upload
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test.env import paths
from cros.factory.test import event_log
from cros.factory.test.rules import phase
from cros.factory.test.rules.privacy import FilterDict
from cros.factory.utils import argparse_utils
from cros.factory.utils.argparse_utils import CmdArg
from cros.factory.utils.argparse_utils import ParseCmdline
from cros.factory.utils.argparse_utils import verbosity_cmd_arg
from cros.factory.utils.debug_utils import SetupLogging
from cros.factory.utils import file_utils
from cros.factory.utils import sys_utils
from cros.factory.utils import time_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils.type_utils import Error


# TODO(tammo): Replace calls to sys.exit with raise Exit, and maybe
# treat that specially (as a smoot exit, as opposed to the more
# verbose output for generic Error).

_global_gooftool = None
_gooftool_lock = threading.Lock()


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


def Command(cmd_name, *args, **kwargs):
  """ Decorator for commands in gooftool.

  This is similar to argparse_utils.Command, but all gooftool commands
  can be waived during `gooftool finalize` or `gooftool verify` using
  --waive_list or --skip_list option.
  """
  def Decorate(fun):
    def CommandWithWaiveSkipCheck(options):
      waive_list = vars(options).get('waive_list', [])
      skip_list = vars(options).get('skip_list', [])
      if phase.GetPhase() >= phase.PVT_DOGFOOD and (
          waive_list != [] or skip_list != []):
        raise Error(
            'waive_list and skip_list should be empty for phase %s' %
            phase.GetPhase())

      if cmd_name not in skip_list:
        try:
          fun(options)
        except Exception as e:
          if cmd_name in waive_list:
            logging.exception(e)
          else:
            raise

    return argparse_utils.Command(cmd_name, *args, **kwargs)(
        CommandWithWaiveSkipCheck)
  return Decorate


@Command('write_hwid',
         CmdArg('hwid', metavar='HWID', help='HWID string'))
def WriteHWID(options):
  """Write specified HWID value into the system BB."""

  logging.info('writing hwid string %r', options.hwid)
  GetGooftool(options).WriteHWID(options.hwid)
  event_log.Log('write_hwid', hwid=options.hwid)
  print 'Wrote HWID: %r' % options.hwid


_project_cmd_arg = CmdArg(
    '--project', metavar='PROJECT',
    default=None, help='Project name to test.')

_hwdb_path_cmd_arg = CmdArg(
    '--hwdb_path', metavar='PATH',
    default=common.DEFAULT_HWID_DATA_PATH,
    help='Path to the HWID database.')

_hwid_status_list_cmd_arg = CmdArg(
    '--status', nargs='*', default=['supported'],
    help='allow only HWIDs with these status values')

_probe_results_cmd_arg = CmdArg(
    '--probe_results', metavar='RESULTS.yaml',
    help=('Output from "gooftool probe --include_vpd" (used instead of '
          'probing this system).'))

_device_info_cmd_arg = CmdArg(
    '--device_info', metavar='DEVICE_INFO.yaml', default=None,
    help='A dict of device info to use instead of fetching from shopfllor '
    'server.')

_hwid_cmd_arg = CmdArg(
    '--hwid', metavar='HWID',
    help='HWID to verify (instead of the currently set HWID of this system).')

_rma_mode_cmd_arg = CmdArg(
    '--rma_mode', action='store_true',
    help='Enable RMA mode, do not check for deprecated components.')

_cros_core_cmd_arg = CmdArg(
    '--cros_core', action='store_true',
    help='Finalize for ChromeOS Core devices (may add or remove few test '
         'items. For example, registration codes or firmware bitmap '
         'locale settings).')

_enforced_release_channels_cmd_arg = CmdArg(
    '--enforced_release_channels', nargs='*', default=None,
    help='Enforced release image channels.')

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

_waive_list_cmd_arg = CmdArg(
    '--waive_list', nargs='*', default=[], metavar='SUBCMD',
    help='A list of waived checks, separated by whitespace.'
         'Each item should be a sub-command of gooftool.'
         'e.g. "gooftool verify --waive_list verify_tpm clear_gbb_flags".')

_skip_list_cmd_arg = CmdArg(
    '--skip_list', nargs='*', default=[], metavar='SUBCMD',
    help='A list of skipped checks, separated by whitespace.'
         'Each item should be a sub-command of gooftool.'
         'e.g. "gooftool verify --skip_list verify_tpm clear_gbb_flags".')


@Command('probe',
         CmdArg('--comps', nargs='*',
                help='List of keys from the component_db registry.'),
         CmdArg('--fast_fw_probe', action='store_true',
                help='Do a fast probe for EC and main firmware versions only. '
                'This implies --no_vol and --no_ic.'),
         CmdArg('--no_vol', action='store_true',
                help='Do not probe volatile data.'),
         CmdArg('--no_ic', action='store_true',
                help='Do not probe initial_config data.'),
         CmdArg('--include_vpd', action='store_true',
                help='Include VPD data in volatiles.'))
def RunProbe(options):
  """Print yaml-formatted breakdown of probed device properties."""
  print GetGooftool(options).Probe(
      target_comp_classes=options.comps,
      fast_fw_probe=options.fast_fw_probe,
      probe_volatile=not options.no_vol,
      probe_initial_config=not options.no_ic,
      probe_vpd=options.include_vpd).Encode()


@Command('verify_components',
         _hwdb_path_cmd_arg,
         CmdArg('target_comps', nargs='*'))
def VerifyComponents(options):
  """Verify that probeable components all match entries in the component_db.

  Probe for each component class in the target_comps and verify
  that a corresponding match exists in the component_db -- make sure
  that these components are present, that they have been approved, but
  do not check against any specific BOM/HWID configurations.
  """

  try:
    result = GetGooftool(options).VerifyComponents(
        options.target_comps)
  except ValueError, e:
    sys.exit(e)

  PrintVerifyComponentsResults(result)


def PrintVerifyComponentsResults(result):
  """Prints out the results of VerifyComponents method call.

  Groups the results into two groups: 'matches' and 'errors', and prints out
  their values.
  """
  # group by matches and errors
  matches = []
  errors = []
  for result_list in result.values():
    for component_name, _, error in result_list:
      if component_name:
        matches.append(component_name)
      else:
        errors.append(error)

  if matches:
    print 'found probeable components:\n  %s' % '\n  '.join(matches)
  if errors:
    print '\nerrors:\n  %s' % '\n  '.join(errors)
    sys.exit('\ncomponent verification FAILURE')
  else:
    print '\ncomponent verification SUCCESS'


@Command('verify_keys',
         _release_rootfs_cmd_arg,
         _firmware_path_cmd_arg)
def VerifyKeys(options):
  """Verify keys in firmware and SSD match."""
  return GetGooftool(options).VerifyKeys(
      options.release_rootfs, options.firmware_path)


@Command('set_fw_bitmap_locale')
def SetFirmwareBitmapLocale(options):
  """Use VPD locale value to set firmware bitmap default language."""

  (index, locale) = GetGooftool(options).SetFirmwareBitmapLocale()
  logging.info('Firmware bitmap initial locale set to %d (%s).',
               index, locale)


@Command('verify_system_time',
         _release_rootfs_cmd_arg)
def VerifySystemTime(options):
  """Verify system time is later than release filesystem creation time."""

  return GetGooftool(options).VerifySystemTime(options.release_rootfs)


@Command('verify_rootfs',
         _release_rootfs_cmd_arg)
def VerifyRootFs(options):
  """Verify rootfs on SSD is valid by checking hash."""

  return GetGooftool(options).VerifyRootFs(options.release_rootfs)


@Command('verify_tpm')
def VerifyTPM(options):
  """Verify TPM is cleared."""

  return GetGooftool(options).VerifyTPM()


@Command('verify_me_locked')
def VerifyManagementEngineLocked(options):
  """Verify Management Engine is locked."""

  return GetGooftool(options).VerifyManagementEngineLocked()


@Command('verify_switch_wp')
def VerifyWPSwitch(options):
  """Verify hardware write protection switch is enabled."""

  GetGooftool(options).VerifyWPSwitch()


@Command('verify_switch_dev')
def VerifyDevSwitch(options):
  """Verify developer switch is disabled."""

  if GetGooftool(options).CheckDevSwitchForDisabling():
    logging.warn('VerifyDevSwitch: No physical switch.')
    event_log.Log('switch_dev', type='virtual switch')


@Command('verify_vpd')
def VerifyVPD(options):
  """Verify that VPD values are properly set.

  Check if mandatory fields are set, and deprecated fields don't exist.
  """
  return GetGooftool(options).VerifyVPD()


@Command('verify_release_channel',
         _enforced_release_channels_cmd_arg)
def VerifyReleaseChannel(options):
  """Verify that release image channel is correct.

  ChromeOS has four channels: canary, dev, beta and stable.
  The last three channels support image auto-updates, checks
  that release image channel is one of them.
  """
  return GetGooftool(options).VerifyReleaseChannel(
      options.enforced_release_channels)


@Command('write_protect')
def EnableFwWp(options):
  """Enable then verify firmware write protection."""
  del options  # Unused.

  def WriteProtect(fw):
    """Calculate protection size, then invoke flashrom.

    The region (offset and size) to write protect may be different per chipset
    and firmware layout, so we have to read the WP_RO section from FMAP to
    decide that.
    """
    wp_section = 'WP_RO'

    fmap_image = fw.GetFirmwareImage(
        sections=(['FMAP'] if fw.target == crosfw.TARGET_MAIN else None))
    if not fmap_image.has_section(wp_section):
      raise Error('Could not find %s firmware section: %s' %
                  (fw.target.upper(), wp_section))

    section_data = fw.GetFirmwareImage(
        sections=[wp_section]).get_section_area(wp_section)
    ro_offset, ro_size = section_data[0 : 2]

    logging.debug('write protecting %s [off=%x size=%x]', fw.target.upper(),
                  ro_offset, ro_size)
    crosfw.Flashrom(fw.target).EnableWriteProtection(ro_offset, ro_size)

  WriteProtect(crosfw.LoadMainFirmware())
  event_log.Log('wp', fw='main')

  # Some EC (mostly PD) does not support "RO NOW". Instead they will only set
  # "RO_AT_BOOT" when you request to enable RO (These platforms consider
  # --wp-range with right range identical to --wp-enable), and requires a
  # 'ectool reboot_ec RO at-shutdown; reboot' to let the RO take effect.
  # After reboot, "flashrom -p host --wp-status" will return protected range.
  # If you don't reboot, returned range will be (0, 0), and running command
  # "ectool flashprotect" will not have RO_NOW.

  for fw in [crosfw.LoadEcFirmware(), crosfw.LoadPDFirmware()]:
    if fw.GetChipId() is None:
      logging.warning('%s not write protected (seems there is no %s flash).',
                      fw.target.upper(), fw.target.upper())
      continue
    WriteProtect(fw)
    event_log.Log('wp', fw=fw.target)


@Command('clear_gbb_flags')
def ClearGBBFlags(options):
  """Zero out the GBB flags, in preparation for transition to release state.

  No GBB flags are set in release/shipping state, but they are useful
  for factory/development.  See "futility gbb --flags" for details.
  """

  GetGooftool(options).ClearGBBFlags()
  event_log.Log('clear_gbb_flags')


@Command('clear_factory_vpd_entries')
def ClearFactoryVPDEntries(options):
  """Clears factory.* items in the RW VPD."""
  entries = GetGooftool(options).ClearFactoryVPDEntries()
  event_log.Log('clear_factory_vpd_entries', entries=FilterDict(entries))


@Command('generate_stable_device_secret')
def GenerateStableDeviceSecret(options):
  """Generates a fresh stable device secret and stores it in the RO VPD."""
  GetGooftool(options).GenerateStableDeviceSecret()
  event_log.Log('generate_stable_device_secret')


@Command('cr50_set_board_id')
def Cr50SetBoardId(options):
  """Set the board id and flag in the Cr50 chip."""
  GetGooftool(options).Cr50SetBoardId()
  event_log.Log('cr50_set_board_id')


@Command('cr50_disable_rma_mode')
def Cr50DisableRmaMode(options):
  """Reset Cr50 state back to default state after RMA."""
  return GetGooftool(options).Cr50DisableRmaMode()


@Command('enable_release_partition',
         CmdArg('--release_rootfs',
                help=('path to the release rootfs device. If not specified, '
                      'the default (5th) partition will be used.')))
def EnableReleasePartition(options):
  """Enables a release image partition on the disk."""
  GetGooftool(options).EnableReleasePartition(options.release_rootfs)


@Command('wipe_in_place',
         CmdArg('--fast', action='store_true',
                help='use non-secure but faster wipe method.'),
         _shopfloor_url_args_cmd_arg,
         _station_ip_cmd_arg,
         _station_port_cmd_arg,
         _wipe_finish_token_cmd_arg)
def WipeInPlace(options):
  """Start factory wipe directly without reboot."""

  GetGooftool(options).WipeInPlace(options.fast,
                                   options.shopfloor_url,
                                   options.station_ip,
                                   options.station_port,
                                   options.wipe_finish_token)

@Command('wipe_init',
         CmdArg('--wipe_args', help='arguments for clobber-state'),
         CmdArg('--state_dev', help='path to stateful partition device'),
         CmdArg('--root_disk', help='path to primary device'),
         CmdArg('--old_root', help='path to old root'),
         _shopfloor_url_args_cmd_arg,
         _release_rootfs_cmd_arg,
         _station_ip_cmd_arg,
         _station_port_cmd_arg,
         _wipe_finish_token_cmd_arg)
def WipeInit(options):
  GetGooftool(options).WipeInit(options.wipe_args,
                                options.shopfloor_url,
                                options.state_dev,
                                options.release_rootfs,
                                options.root_disk,
                                options.old_root,
                                options.station_ip,
                                options.station_port,
                                options.wipe_finish_token)

@Command('verify',
         CmdArg('--no_write_protect', action='store_true',
                help='Do not check write protection switch state.'),
         _hwid_status_list_cmd_arg,
         _hwdb_path_cmd_arg,
         _project_cmd_arg,
         _probe_results_cmd_arg,
         _hwid_cmd_arg,
         _rma_mode_cmd_arg,
         _cros_core_cmd_arg,
         _release_rootfs_cmd_arg,
         _firmware_path_cmd_arg,
         _enforced_release_channels_cmd_arg,
         _waive_list_cmd_arg,
         _skip_list_cmd_arg)
def Verify(options):
  """Verifies if whole factory process is ready for finalization.

  This routine performs all the necessary checks to make sure the
  device is ready to be finalized, but does not modify state.  These
  checks include dev switch, firmware write protection switch, hwid,
  system time, keys, and root file system.
  """

  if not options.no_write_protect:
    VerifyWPSwitch(options)
    VerifyManagementEngineLocked(options)
  VerifyDevSwitch(options)
  VerifyHWID(options)
  VerifySystemTime(options)
  VerifyKeys(options)
  VerifyRootFs(options)
  VerifyTPM(options)
  VerifyVPD(options)
  VerifyReleaseChannel(options)


@Command('untar_stateful_files')
def UntarStatefulFiles(unused_options):
  """Untars stateful files from stateful_files.tar.xz on stateful partition.

  If that file does not exist (which should only be R30 and earlier),
  this is a no-op.
  """
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


@Command('log_system_details')
def LogSystemDetails(options):
  """Write miscellaneous system details to the event log."""

  event_log.Log('system_details', **GetGooftool(options).GetSystemDetails())


def CreateReportArchiveBlob(*args, **kwargs):
  """Creates a report archive and returns it as a blob.

  Args:
    See CreateReportArchive.

  Returns:
    An xmlrpclib.Binary object containing a .tar.xz file.
  """
  report_archive = CreateReportArchive(*args, **kwargs)
  try:
    with open(report_archive) as f:
      return xmlrpclib.Binary(f.read())
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
  def NormalizeAsFileName(token):
    return re.sub(r'\W+', '', token).strip()

  target_name = '%s%s.tar.xz' % (
      time.strftime('%Y%m%dT%H%M%SZ',
                    time.gmtime()),
      ('' if device_sn is None else
       '_' + NormalizeAsFileName(device_sn)))
  target_path = os.path.join(gettempdir(), target_name)

  # Intentionally ignoring dotfiles in EVENT_LOG_DIR.
  tar_cmd = 'cd %s ; tar cJf %s *' % (event_log.EVENT_LOG_DIR, target_path)
  tar_cmd += ' %s' % paths.FACTORY_LOG_PATH
  if add_file:
    for f in add_file:
      # Require absolute paths since the tar command may change the
      # directory.
      if not f.startswith('/'):
        raise Error('Not an absolute path: %s' % f)
      if not os.path.exists(f):
        raise Error('File does not exist: %s' % f)
      tar_cmd += ' %s' % pipes.quote(f)
  cmd_result = Shell(tar_cmd)

  if ((cmd_result.status == 1) and
      all((x == '' or
           'file changed as we read it' in x or
           "Removing leading `/' from member names" in x)
          for x in cmd_result.stderr.split('\n'))):
    # That's OK.  Make sure it's valid though.
    Spawn(['tar', 'tfJ', target_path], check_call=True, log=True,
          ignore_stdout=True)
  elif not cmd_result.success:
    raise Error('unable to tar event logs, cmd %r failed, stderr: %r' %
                (tar_cmd, cmd_result.stderr))

  return target_path

_upload_method_cmd_arg = CmdArg(
    '--upload_method', metavar='METHOD:PARAM',
    help=('How to perform the upload.  METHOD should be one of '
          '{ftp, shopfloor, ftps, cpfe}.'))
_add_file_cmd_arg = CmdArg(
    '--add_file', metavar='FILE', action='append',
    help='Extra file to include in report (must be an absolute path)')


@Command('upload_report',
         _upload_method_cmd_arg,
         _add_file_cmd_arg)
def UploadReport(options):
  """Create a report containing key device details."""
  ro_vpd = ReadRoVpd()
  device_sn = ro_vpd.get('serial_number', None)
  if device_sn is None:
    logging.warning('RO_VPD missing device serial number')
    device_sn = 'MISSING_SN_' + time_utils.TimedUUID()
  target_path = CreateReportArchive(device_sn)

  if options.upload_method is None or options.upload_method == 'none':
    logging.warning('REPORT UPLOAD SKIPPED (report left at %s)', target_path)
    return
  method, param = options.upload_method.split(':', 1)
  if method == 'shopfloor':
    report_upload.ShopFloorUpload(target_path, param)
  elif method == 'ftp':
    report_upload.FtpUpload(target_path, 'ftp:' + param)
  elif method == 'ftps':
    report_upload.CurlUrlUpload(target_path, '--ftp-ssl-reqd ftp:%s' % param)
  elif method == 'cpfe':
    report_upload.CpfeUpload(target_path, pipes.quote(param))
  else:
    raise Error('unknown report upload method %r', method)


@Command('finalize',
         CmdArg('--no_write_protect', action='store_true',
                help='Do not enable firmware write protection.'),
         CmdArg('--fast', action='store_true',
                help='use non-secure but faster wipe method.'),
         _shopfloor_url_args_cmd_arg,
         _hwdb_path_cmd_arg,
         _hwid_status_list_cmd_arg,
         _upload_method_cmd_arg,
         _add_file_cmd_arg,
         _probe_results_cmd_arg,
         _hwid_cmd_arg,
         _rma_mode_cmd_arg,
         _cros_core_cmd_arg,
         _release_rootfs_cmd_arg,
         _firmware_path_cmd_arg,
         _enforced_release_channels_cmd_arg,
         _station_ip_cmd_arg,
         _station_port_cmd_arg,
         _wipe_finish_token_cmd_arg,
         _waive_list_cmd_arg,
         _skip_list_cmd_arg)
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
  - Uploads system logs & reports
  - Wipes the testing kernel, rootfs, and stateful partition
  """
  Cr50SetBoardId(options)
  Verify(options)
  Cr50DisableRmaMode(options)
  LogSourceHashes(options)
  UntarStatefulFiles(options)
  if options.cros_core:
    logging.info('SetFirmwareBitmapLocale is skipped for ChromeOS Core device.')
  else:
    SetFirmwareBitmapLocale(options)
  ClearFactoryVPDEntries(options)
  GenerateStableDeviceSecret(options)
  ClearGBBFlags(options)
  if options.no_write_protect:
    logging.warn('WARNING: Firmware Write Protection is SKIPPED.')
    event_log.Log('wp', fw='both', status='skipped')
  else:
    EnableFwWp(options)
  LogSystemDetails(options)
  UploadReport(options)

  event_log.Log('wipe_in_place')
  wipe_args = []
  if options.shopfloor_url:
    wipe_args += ['--shopfloor_url', options.shopfloor_url]
  if options.fast:
    wipe_args += ['--fast']
  if options.station_ip:
    wipe_args += ['--station_ip', options.station_ip]
  if options.station_port:
    wipe_args += ['--station_port', options.station_port]
  if options.wipe_finish_token:
    wipe_args += ['--wipe_finish_token', options.wipe_finish_token]
  ExecFactoryPar('gooftool', 'wipe_in_place', *wipe_args)


@Command('verify_hwid',
         _probe_results_cmd_arg,
         _hwdb_path_cmd_arg,
         _hwid_cmd_arg,
         _rma_mode_cmd_arg)
def VerifyHWID(options):
  """A simple wrapper that calls out to HWID utils to verify version 3 HWID.

  This is mainly for Gooftool to verify v3 HWID during finalize.  For testing
  and development purposes, please use `hwid` command.
  """
  db = GetGooftool(options).db
  encoded_string = options.hwid or hwid_utils.GetHWIDString()
  if options.probe_results:
    probed_results = yaml.load(open(options.probe_results).read())
  else:
    probed_results = yaml.load(Probe(probe_vpd=True).Encode())
  vpd = hwid_utils.GetVPD(probed_results)

  event_log.Log('probed_results', probed_results=FilterDict(probed_results))
  event_log.Log('vpd', vpd=FilterDict(vpd))

  hwid_utils.VerifyHWID(db, encoded_string, probed_results, vpd,
                        rma_mode=options.rma_mode)

  event_log.Log('verified_hwid', hwid=encoded_string)


@Command('get_firmware_hash',
         CmdArg('--file', metavar='FILE', help='Firmware File.'))
def GetFirmwareHash(options):
  """Get firmware hash from a file"""
  if os.path.exists(options.file):
    hashes = CalculateFirmwareHashes(options.file)
    for section, value_dict in hashes.iteritems():
      print '%s:' % section
      for key, value in value_dict.iteritems():
        print '  %s: %s' % (key, value)
  else:
    raise Error('File does not exist: %s' % options.file)


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
      verbosity_cmd_arg)
  SetupLogging(options.verbosity, options.log)
  event_log.SetGlobalLoggerDefaultPrefix('gooftool')
  event_log.GetGlobalLogger().suppress = options.suppress_event_logs
  logging.debug('gooftool options: %s', repr(options))

  phase.OverridePhase(options.phase)
  try:
    logging.debug('GOOFTOOL command %r', options.command_name)
    options.command(options)
    logging.info('GOOFTOOL command %r SUCCESS', options.command_name)
  except Error, e:
    logging.exception(e)
    sys.exit('GOOFTOOL command %r ERROR: %s' % (options.command_name, e))
  except Exception, e:
    logging.exception(e)
    sys.exit('UNCAUGHT RUNTIME EXCEPTION %s' % e)


if __name__ == '__main__':
  main()
