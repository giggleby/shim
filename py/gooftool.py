#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Google Factory Tool.

This tool is indended to be used on factory assembly lines.  It
provides all of the Google required test functionality and must be run
on each device as part of the assembly process.
"""


import logging
import os
import re
import sys

from tempfile import gettempdir, NamedTemporaryFile

import bmpblk
import crosfw
import hwid_tool
import probe
import report_upload
import vpd_data

from common import Error, ParseKeyValueData, SetupLogging, Shell
from common import YamlRead, YamlWrite
from hacked_argparse import CmdArg, Command, ParseCmdline, verbosity_cmd_arg

# TODO(tammo): Remove imp logic once the cros/factory code moves into this repo.
# NOTE: These imports also corrupt the python logging module...
import imp
at_common = imp.find_module('common', ['/usr/local/autotest/client/bin'])
imp.load_module('at_common', *at_common)
from autotest_lib.client.cros.factory.event_log import EventLog, EVENT_LOG_DIR
from autotest_lib.client.cros.factory.event_log import TimeString, TimedUuid
from autotest_lib.client.cros.factory import FACTORY_LOG_PATH


# Use a global event log, so that only a single log is created when
# gooftool is called programmatically.
_event_log = EventLog('gooftool')


def GetPrimaryDevicePath(partition=None):
  def IsFixed(dev):
    sysfs_path = '/sys/block/%s/removable' % dev
    return (os.path.exists(sysfs_path) and
            open(sysfs_path).read().strip() == '0')
  alpha_re = re.compile(r'^/dev/([a-zA-Z]+)[0-9]+$')
  alnum_re = re.compile(r'^/dev/([a-zA-Z]+[0-9]+)p[0-9]+$')
  matched_alnum = False
  dev_set = set()
  for path in Shell('cgpt find -t rootfs').stdout.strip().split():
    for dev in alpha_re.findall(path):
      if IsFixed(dev):
        dev_set.add(dev)
        matched_alnum = False
    for dev in alnum_re.findall(path):
      if IsFixed(dev):
        dev_set.add(dev)
        matched_alnum = True
  if len(dev_set) != 1:
    raise Error('zero or multiple primary devs: %s' % dev_set)
  dev_path = os.path.join('/dev', dev_set.pop())
  if partition is None:
    return dev_path
  fmt_str = '%sp%d' if matched_alnum else '%s%d'
  return fmt_str % (dev_path, partition)


def GetReleaseRootPartitionPath():
  return GetPrimaryDevicePath(5)


def GetReleaseKernelPartitionPath():
  return GetPrimaryDevicePath(4)


def FindScript(script_name):
  script_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.realpath(__file__))), 'sh', script_name)
  if not os.path.exists(script_path):
    raise Error('Needed script %s does not exist.' % script_path)
  return script_path


def ReadVpd(fw_image_file, kind):
  raw_vpd_data = Shell('vpd -i %s -l -f %s' % (kind, fw_image_file)).stdout
  return ParseKeyValueData('"(.*)"="(.*)"$', raw_vpd_data)


def ReadRoVpd(fw_image_file):
  return ReadVpd(fw_image_file, 'RO_VPD')


def ReadRwVpd(fw_image_file):
  return ReadVpd(fw_image_file, 'RW_VPD')


@Command('write_hwid',
         CmdArg('hwid', metavar='HWID', help='HWID string'))
def WriteHwid(options):
  """Write specified HWID value into the system BB."""
  logging.debug('writing hwid string %r', options.hwid)
  main_fw = crosfw.LoadMainFirmware()
  Shell('gbb_utility --set --hwid="%s" "%s"' %
        (options.hwid, main_fw.GetFileName()))
  main_fw.Write(sections=['GBB'])
  _event_log.Log('write_hwid', hwid=options.hwid)


_hwdb_path_cmd_arg = CmdArg(
    '--hwdb_path', metavar='PATH',
    default=hwid_tool.DEFAULT_HWID_DATA_PATH,
    help='Path to the HWID database.')


@Command('probe_hwids',
         _hwdb_path_cmd_arg,
         CmdArg('-b', '--board', metavar='BOARD',
                help='BOARD name', required=True),
         CmdArg('--bom', metavar='BOM', help='BOM name'),
         CmdArg('--variant', metavar='VARIANT', help='VARIANT code'),
         CmdArg('--comp_map', action='store_true'),
         CmdArg('--status', nargs='*',
                help='consider only HWIDs with this status'))
def ProbeHwid(options):
  """Determine a list of possible HWIDs using provided args and probeing.

  VOLATILE can always be determined by probing.  To get a unique
  result, VARIANT must be specified for all cases where the matching
  BOM has more than one associated variant code, otherwise all HWID
  variants will be returned.  Both VARIANT and BOM information can
  alternatively be specified using the --comp_map argument, which
  allows specifying a list of

    component-class: canonical-component-name

  pairs on stdin, one per line (yaml format).  Based on what is known
  from BOM and comp_map, determine a list of components to probe for,
  and use those probe results to resolve a list of matching HWIDs.  If
  no boms, components, or variant codes are specified, then a list of
  all HWIDs that match probable components will be returned.

  Returns (on stdout): A list of HWIDs that match the available probe
  results and argument contraints, one per line.
  """
  hwdb = hwid_tool.ReadDatastore(options.hwdb_path)
  ro_vpd = ReadRoVpd(crosfw.LoadMainFirmware().GetFileName())
  if options.board not in hwdb.device_db:
    sys.exit('ERROR: unknown board %r' % options.board)
  device = hwdb.device_db[options.board]
  component_map = {}
  if options.bom:
    bom_details = device.hwid_map.get(options.bom, None)
    if bom_details is None:
      sys.exit('ERROR: unkown bom %r for board %r' %
               (options.bom, options.board))
    component_map.update(bom_details.component_map)
  comp_db_class_map = hwid_tool.CalcCompDbClassMap(hwdb.comp_db)
  if options.variant:
    variant_details = device.variant_map.get(options.variant, None)
    if options.variant is None:
      sys.exit('ERROR: unknown variant code %r for board %r' %
               (options.variant, options.board))
    for comp_name in variant_details:
      comp_class = comp_db_class_map[comp_name]
      if comp_class in component_map:
        sys.exit('ERROR: multiple specifications for %r components'
                 ' (both VARIANT and BOM)' % comp_class)
      component_map[comp_class] = comp_name
  else:
    # Parrot factory specific request to detect keyboard to determine HWID
    # from probing the components including keyboard. The keyboard is probed
    # from RO_VPD.
    if not ro_vpd['keyboard_layout']:
      sys.exit('ERROR: keyboard_layout in RO_VPD is not specified')
    keyboard_list = hwdb.comp_db.registry['keyboard']
    for kbd in keyboard_list.keys():
      if keyboard_list[kbd] == ro_vpd['keyboard_layout']:
        component_map['keyboard'] = kbd

  if options.comp_map:
    input_map = YamlRead(sys.stdin.read())
    logging.info('stdin component map: %r', input_map)
    for key, value in input_map.items():
      if key not in hwdb.comp_db.registry:
        sys.exit('ERROR: unknown component class %r (from stdin)' % key)
      if value not in comp_db_class_map:
        sys.exit('ERROR: unkown component name %r (from stdin)' % value)
      if key in component_map:
        sys.exit('ERROR: multiple specifications for %r components'
                 ' (stdin and BOM/VARIANT)' % key)
      component_map[key] = value
  missing_classes = list(set(hwdb.comp_db.registry) - set(component_map))
  if missing_classes:
    logging.info('probing for %s', ', '.join(missing_classes))
  probe_results = probe.Probe(target_comp_classes=missing_classes,
                              probe_volatile=True, probe_initial_config=False)
  cooked_results = hwid_tool.CookProbeResults(
    hwdb, probe_results, options.board)
  cooked_results.matched_components.update(component_map)
  status_set = set(options.status) if options.status else set(['supported'])
  hwid_set = hwid_tool.MatchHwids(hwdb, cooked_results, options.board,
                                  status_set)
  if not hwid_set:
    sys.exit('NO matching HWIDs found')
  print '\n'.join(hwid_set)


@Command('probe',
         CmdArg('--comps', nargs='*',
                help='List of keys from the component_db registry.'),
         CmdArg('--no_vol', action='store_true',
                help='Do not probe volatile data.'),
         CmdArg('--no_ic', action='store_true',
                help='Do not probe initial_config data.'))
def RunProbe(options):
  """Print yaml-formatted breakdown of probed device properties."""
  probe_results = probe.Probe(target_comp_classes=options.comps,
                              probe_volatile=not options.no_vol,
                              probe_initial_config=not options.no_ic)
  print YamlWrite(probe_results.__dict__)


@Command('verify_components',
         _hwdb_path_cmd_arg,
         CmdArg('comp_white_list', nargs='*'))
def VerifyComponents(options):
  """Verify that probable components all match entries in the component_db.

  Probe for each component class in the comp_white_list and verify
  that a corresponding match exists in the component_db -- make sure
  that these components are present, that they have been approved, but
  do not check against any specific BOM/HWID configurations.
  """
  hwdb = hwid_tool.ReadDatastore(options.hwdb_path)
  if not options.comp_white_list:
    sys.exit('ERROR: no component white list specified; possible choices:\n  %s'
             % '\n  '.join(sorted(hwdb.comp_db.registry)))
  for comp_class in options.comp_white_list:
    if comp_class not in hwdb.comp_db.registry:
      sys.exit('ERROR: specified white list component class %r does not exist'
               ' in the component DB.' % comp_class)
  probe_results = probe.Probe(target_comp_classes=options.comp_white_list,
                              probe_volatile=False, probe_initial_config=False)
  probe_val_map = hwid_tool.CalcCompDbProbeValMap(hwdb.comp_db)
  errors = []
  matches = []
  for comp_class in sorted(options.comp_white_list):
    probe_val = probe_results.found_components.get(comp_class, None)
    if probe_val is not None:
      comp_name = probe_val_map.get(probe_val, None)
      if comp_name is not None:
        matches.append(comp_name)
      else:
        errors.append('unsupported %r component found with probe result'
                      ' %r (no matching name in the component DB)' %
                      (comp_class, probe_val))
    else:
      errors.append('missing %r component' % comp_class)
  if errors:
    print '\n'.join(errors)
    sys.exit('component verification FAILURE')
  else:
    print 'component verification SUCCESS'
    print 'found components:\n  %s' % '\n  '.join(matches)


@Command('verify_hwid',
         _hwdb_path_cmd_arg)
def VerifyHwid(options):
  """Verify system HWID properties match probed device properties.

  First probe components, volatile and initial_config parameters for
  the DUT.  Then use the available device data to produce a list of
  candidate HWIDs.  Then verify the HWID from the DUT is present in
  that list.  Then verify that the DUT initial config values match
  those specified for its HWID.  Finally, verify that VPD contains all
  the necessary fields as specified by the board data, and when
  possible verify that values are legitimate.
  """
  hwdb = hwid_tool.ReadDatastore(options.hwdb_path)
  main_fw_file = crosfw.LoadMainFirmware().GetFileName()
  gbb_result = Shell('gbb_utility -g --hwid %s' % main_fw_file).stdout
  hwid = re.findall(r'hardware_id:(.*)', gbb_result)[0].strip()
  hwid_properties = hwid_tool.LookupHwidProperties(hwdb, hwid)
  logging.info('Verifying system HWID: %r', hwid_properties.hwid)
  logging.debug('expected system properties:\n%s',
                YamlWrite(hwid_properties.__dict__))
  probe_results = probe.Probe()
  cooked_results = hwid_tool.CookProbeResults(
      hwdb, probe_results, hwid_properties.board)
  logging.debug('found system properties:\n%s',
                YamlWrite(cooked_results.__dict__))
  _event_log.Log('probe',
                 results=cooked_results.__dict__)
  match_errors = []
  # TODO(tammo): Refactor to use hwid_tool.MatchHwids() ; this will
  # make error reporting harder...  Or maybe just factor out the
  # shared matching logic, and add error reporting to that, which the
  # MatchHwids routine could ignore.
  for comp_class, expected_name in hwid_properties.component_map.items():
    if expected_name == 'ANY':
      continue
    if expected_name == cooked_results.matched_components.get(comp_class, None):
      continue
    if comp_class in probe_results.missing_components:
      match_errors.append('  %s component mismatch, expected %s, found nothing'
                          % (comp_class, expected_name))
    else:
      probe_value = probe_results.found_components.get(comp_class, None)
      match_errors.append('  %s component mismatch, expected %s, found  %r' %
                          (comp_class, expected_name, probe_value))
  if match_errors:
    raise Error('HWID verification FAILED.\n%s' % '\n'.join(match_errors))
  if hwid_properties.volatile not in cooked_results.matched_volatile_tags:
    msg = ('  HWID specified volatile %s, but found match only for %s' %
           (hwid_properties.volatile,
            ', '.join(cooked_results.matched_volatile_tags)))
    raise Error('HWID verification FAILED.\n%s' % msg)
  if (hwid_properties.initial_config is not None and
      hwid_properties.initial_config not in
      cooked_results.matched_initial_config_tags):
    msg = ('  HWID specified initial_config %s, but only found match for [%s]' %
           (hwid_properties.initial_config,
            ', '.join(cooked_results.matched_initial_config_tags)))
    raise Error('HWID verification FAILED.\n%s' % msg)
  # TODO(tammo): Verify HWID status is supported (or deprecated for RMA).
  ro_vpd = ReadRoVpd(main_fw_file)
  for field in hwid_properties.vpd_ro_field_list:
    if field not in ro_vpd:
      raise Error('Missing required VPD field: %s' % field)
    known_valid_values = vpd_data.KNOWN_VPD_FIELD_DATA.get(field, None)
    value = ro_vpd[field]
    if known_valid_values is not None and value not in known_valid_values:
      raise Error('Invalid VPD entry : field %r, value %r' % (field, value))
  rw_vpd = ReadRwVpd(main_fw_file)
  _event_log.Log(
      'verify_hwid',
      matched_components=cooked_results.matched_components,
      initial_configs=cooked_results.matched_initial_config_tags,
      volatiles=cooked_results.matched_volatile_tags,
      ro_vpd=ro_vpd,
      rw_vpd=rw_vpd)


@Command('verify_keys')
def VerifyKeys(options):
  """Verify keys in firmware and SSD match."""
  script = FindScript('verify_keys.sh')
  kernel_device = GetReleaseKernelPartitionPath()
  main_fw_file = crosfw.LoadMainFirmware().GetFileName()
  result = Shell('%s %s %s' % (script, kernel_device, main_fw_file))
  if not result.success:
    raise Error, '%r failed, stderr: %r' % (script, result.stderr)


@Command('set_fw_bitmap_locale')
def SetFirmwareBitmapLocale(options):
  """Use VPD locale value to set firmware bitmap default language."""
  image_file = crosfw.LoadMainFirmware().GetFileName()
  locale = ReadRoVpd(image_file).get('initial_locale', None)
  if locale is None:
    raise Error, 'Missing initial_locale VPD.'
  bitmap_locales = []
  with NamedTemporaryFile() as f:
    Shell('gbb_utility -g --bmpfv=%s %s' % (f.name, image_file))
    bmpblk_data = bmpblk.unpack_bmpblock(f.read())
    bitmap_locales = bmpblk_data.get('locales', bitmap_locales)
  # Some locale values are just a language code and others are a
  # hyphen-separated language code and country code pair.  We care
  # only about the language code part.
  language_code = locale.partition('-')[0]
  if language_code not in bitmap_locales:
    raise Error, ('Firmware bitmaps do not contain support for the specified '
                  'initial locale language %r' % language_code)
  else:
    locale_index = bitmap_locales.index(language_code)
    logging.info('Firmware bitmap initial locale set to %d (%s).',
                 locale_index, bitmap_locales[locale_index])
    Shell('crossystem loc_idx=%d' % locale_index)


@Command('verify_system_time')
def VerifySystemTime(options):
  """Verify system time is later than release filesystem creation time."""
  script = FindScript('verify_system_time.sh')
  rootfs_device = GetReleaseRootPartitionPath()
  result = Shell('%s %s' % (script, rootfs_device))
  if not result.success:
    raise Error, '%r failed, stderr: %r' % (script, result.stderr)


@Command('verify_rootfs')
def VerifyRootFs(options):
  """Verify rootfs on SSD is valid by checking hash."""
  script = FindScript('verify_rootfs.sh')
  rootfs_device = GetReleaseRootPartitionPath()
  result = Shell('%s %s' % (script, rootfs_device))
  if not result.success:
    raise Error, '%r failed, stderr: %r' % (script, result.stderr)


@Command('verify_switch_wp')
def VerifyWpSwitch(options):
  """Verify hardware write protection switch is enabled."""
  if Shell('crossystem wpsw_cur').stdout.strip() != '1':
    raise Error, 'write protection switch is disabled'


@Command('verify_switch_dev')
def VerifyDevSwitch(options):
  """Verify developer switch is disabled."""
  VBSD_HONOR_VIRT_DEV_SWITCH = 0x400
  flags = int(Shell('crossystem vdat_flags').stdout.strip(), 0)
  if (flags & VBSD_HONOR_VIRT_DEV_SWITCH) != 0:
    # System is using virtual developer switch.  That will be handled in
    # prepare_wipe.sh by setting "crossystem disable_dev_request=1" -- although
    # we can't verify that until next reboot, because the real values are stored
    # in TPM.
    logging.warn('VerifyDevSwitch: No physical switch.')
    _event_log.Log('switch_dev', type='virtual switch')
    return
  if Shell('crossystem devsw_cur').stdout.strip() != '0':
    raise Error, 'developer mode is not disabled'


@Command('write_protect')
def EnableFwWp(options):
  """Enable then verify firmware write protection."""

  def CalculateLegacyRange(image, length, section_data):
    ro_size = length / 2
    ro_a = int(section_data[0] / ro_size)
    ro_b = int((section_data[0] + section_data[1] - 1) / ro_size)
    if ro_a != ro_b:
      raise Error("%s firmware section %s has illegal size" %
                  (fw_type, section))
    ro_offset = ro_a * ro_size
    return (ro_offset, ro_size)

  def WriteProtect(fw_file_path, fw_type, legacy_section):
    """Calculate protection size, then invoke flashrom.

    Our supported chips only allow write protecting half their total
    size, so we parition the flash chipset space accordingly.
    """
    raw_image = open(fw_file_path, 'rb').read()
    wp_section = 'WP_RO'
    image = crosfw.FirmwareImage(raw_image)
    if image.has_section(wp_section):
      section_data = image.get_section_area(wp_section)
      ro_offset = section_data[0]
      ro_size = section_data[1]
    elif image.has_section(legacy_section):
      section_data = image.get_section_area(legacy_section)
      (ro_offset, ro_size) = CalculateLegacyRange(
          image, len(raw_image), section_data)
    else:
      raise Error('could not find %s firmware section %s or %s' %
                  (fw_type, wp_section, legacy_section))

    logging.debug('write protecting %s [off=%x size=%x]', fw_type,
                  ro_offset, ro_size)
    crosfw.Flashrom(fw_type).EnableWriteProtection(ro_offset, ro_size)

  WriteProtect(crosfw.LoadMainFirmware().GetFileName(), 'main', 'RO_SECTION')
  _event_log.Log('wp', fw='main')
  ec_fw_file = crosfw.LoadEcFirmware().GetFileName()
  if ec_fw_file is not None:
    WriteProtect(ec_fw_file, 'ec', 'EC_RO')
    _event_log.Log('wp', fw='ec')
  else:
    logging.warning('EC not write protected (seems there is no EC flash).')


@Command('clear_gbb_flags')
def ClearGbbFlags(options):
  """Zero out the GBB flags, in preparation for transition to release state.

  No GBB flags are set in release/shipping state, but they are useful
  for factory/development.  See "gbb_utility --flags" for details.
  """
  script = FindScript('clear_gbb_flags.sh')
  result = Shell(script)
  if not result.success:
    raise Error, '%r failed, stderr: %r' % (script, result.stderr)
  _event_log.Log('clear_gbb_flags')


@Command('prepare_wipe',
         CmdArg('--fast', action='store_true',
                help='use non-secure but faster wipe method.'))
def PrepareWipe(options):
  """Prepare system for transition to release state in next reboot."""
  script = FindScript('prepare_wipe.sh')
  tag = 'fast' if options.fast else ''
  rootfs_device = GetReleaseRootPartitionPath()
  result = Shell('FACTORY_WIPE_TAGS=%s %s %s' % (tag, script, rootfs_device))
  if not result.success:
    raise Error, '%r failed, stderr: %r' % (script, result.stderr)


@Command('verify',
         CmdArg('--no_write_protect', action='store_true',
                help='Do not check write protection switch state.'),
         _hwdb_path_cmd_arg)
def Verify(options):
  """Verifies if whole factory process is ready for finalization.

  This routine performs all the necessary checks to make sure the
  device is ready to be finalized, but does not modify state.  These
  checks include dev switch, firmware write protection switch, hwid,
  system time, keys, and root file system.
  """
  if not options.no_write_protect:
    VerifyWpSwitch({})
  VerifyDevSwitch({})
  VerifyHwid(options)
  VerifySystemTime({})
  VerifyKeys({})
  VerifyRootFs({})


@Command('log_system_details')
def LogSystemDetails(options):
  """Write miscellaneous system details to the event log."""
  raw_cs_data = Shell('crossystem').stdout.strip().splitlines()
  # The crossytem output contains many lines like:
  # 'key = value  # description'
  # Use regexps to pull out the key-value pairs and build a dict.
  cs_data = dict((k, v.strip()) for k, v in
                 map(lambda x: re.findall(r'\A(\S+)\s+=\s+(.*)#.*\Z', x)[0],
                     raw_cs_data))
  _event_log.Log(
      'system_details',
      platform_name=Shell('mosys platform name').stdout.strip(),
      crossystem=cs_data,
      modem_status=Shell('modem status').stdout.splitlines(),
      ec_wp_status=Shell(
          'flashrom -p internal:bus=lpc --get-size 2>/dev/null && '
          'flashrom -p internal:bus=lpc --wp-status || '
          'echo "EC is not available."').stdout,
      bios_wp_status = Shell(
          'flashrom -p internal:bus=spi --wp-status').stdout)


_upload_method_cmd_arg = CmdArg(
    '--upload_method', metavar='METHOD:PARAM',
    help=('How to perform the upload.  METHOD should be one of '
          '{ftp, shopfloor, curl, cpfe, custom}.'))


@Command('upload_report',
         _upload_method_cmd_arg)
def UploadReport(options):
  """Create and a report containing key device details."""
  ro_vpd = ReadRoVpd(crosfw.LoadMainFirmware().GetFileName())
  device_sn = ro_vpd.get('serial_number', None)
  if device_sn is None:
    logging.warning('RO_VPD missing device serial number')
    device_sn = 'MISSING_SN_' + TimedUuid()
  target_name = '%s_%s.tbz2' % (TimeString(), device_sn)
  target_path = os.path.join(gettempdir(), target_name)
  # Intentionally ignoring dotfiles in EVENT_LOG_DIR.
  tar_cmd = 'cd %s ; tar cjf %s *' % (EVENT_LOG_DIR, target_path)
  tar_cmd += ' --add-file %s' % FACTORY_LOG_PATH
  cmd_result = Shell(tar_cmd)
  if not cmd_result.success:
    raise Error('unable to tar event logs, cmd %r failed, stderr: %r' %
                (tar_cmd, cmd_result.stderr))
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
    report_upload.CpfeUpload(target_path, param)
  else:
    raise Error('unknown report upload method %r', method)


@Command('prepare_finalize',
         CmdArg('--no_write_protect', action='store_true',
                help='Do not enable firmware write protection.'),
         CmdArg('--fast', action='store_true',
                help='use non-secure but faster wipe method.'),
         _hwdb_path_cmd_arg,
         _upload_method_cmd_arg)
def PrepareFinalize(options):
  """Verify system readiness and upload the factory logs.

  This routine first verifies system state (see verify command), modifies
  firmware bitmaps to match locale, and then clears all of the factory-friendly
  flags from the GBB.  If everything is fine, it enables firmware write
  protection (cannot rollback after this stage), uploads system logs & reports,
  and sets the necessary boot flags to cause wipe of the factory image on the
  next boot.
  """
  Verify(options)
  SetFirmwareBitmapLocale({})
  ClearGbbFlags({})
  if options.no_write_protect:
    logging.warn('WARNING: Firmware Write Protection is SKIPPED.')
    _event_log.Log('wp', fw='both', status='skipped')
  else:
    EnableFwWp({})
  LogSystemDetails(options)
  UploadReport(options)


@Command('finalize',
         CmdArg('--no_write_protect', action='store_true',
                help='Do not enable firmware write protection.'),
         CmdArg('--fast', action='store_true',
                help='use non-secure but faster wipe method.'),
         _hwdb_path_cmd_arg,
         _upload_method_cmd_arg)
def Finalize(options):
  """Verify system readiness and trigger transition into release state.

  This routine first verifies system state (see verify command), then
  clears all of the testing flags from the GBB, then modifies firmware
  bitmaps to match locale.  Then it enables firmware write protection
  and sets the necessary boot flags to cause wipe of the factory image
  on the next boot.
  """
  PrepareFinalize(options)
  PrepareWipe(options)


def Main():
  """Run sub-command specified by the command line args."""
  options = ParseCmdline(
      'Perform Google required factory tests.',
      CmdArg('-l', '--log', metavar='PATH',
             help='Write logs to this file.'),
      verbosity_cmd_arg)
  SetupLogging(options.verbosity, options.log)
  logging.debug('gooftool options: %s', repr(options))
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
  Main()
