#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import re

import collections
from collections import namedtuple
from tempfile import NamedTemporaryFile

import factory_common  # pylint: disable=W0611
import cros.factory.hwid.common as hwid3_common
from cros.factory.common import Error, Shell
from cros.factory.hwdb import hwid_tool
from cros.factory.hwid import common
from cros.factory.gooftool import crosfw
from cros.factory.gooftool.bmpblk import unpack_bmpblock
from cros.factory.gooftool.probe import Probe, ReadRoVpd, ReadRwVpd
from cros.factory.gooftool.vpd_data import KNOWN_VPD_FIELD_DATA
from cros.factory.hwid.database import Database
from cros.factory.hwid.decoder import Decode
from cros.factory.hwid.encoder import Encode, BOMToBinaryString
from cros.factory.hwid.encoder import BinaryStringToEncodedString
from cros.factory.privacy import FilterDict
from cros.factory.rule import Context
from cros.factory.system import vpd
from cros.factory.utils.process_utils import CheckOutput, GetLines
from cros.factory.utils.string_utils import ParseDict

# A named tuple to store the probed component name and the error if any.
ProbedComponentResult = namedtuple('ProbedComponentResult',
                                  ['component_name', 'probed_string', 'error'])

# The mismatch result tuple.
Mismatch = namedtuple('Mismatch', ['expected', 'actual'])

class Util(object):
  """A collection of util functions that Gooftool needs."""

  def __init__(self):
    self.shell = Shell

  def _IsDeviceFixed(self, dev):
    """Check if a device is a fixed device, i.e. not a removable device.

    Args:
      dev: A device string under /sys/block.

    Returns:
      True if the given device is fixed, and false if it is not.
    """

    sysfs_path = '/sys/block/%s/removable' % dev
    return (os.path.exists(sysfs_path) and
            open(sysfs_path).read().strip() == '0')

  def GetPrimaryDevicePath(self, partition=None):
    """Gets the path for the primary device, which is the only non-removable
    device in the system.

    Args:
      partition: The index of the partition on primary device.

    Returns:
      The path to the primary device. If partition is specified, the path
      points to that partition of the primary device. e.g. /dev/sda1
    """

    alpha_re = re.compile(r'^/dev/([a-zA-Z]+)[0-9]+$')
    alnum_re = re.compile(r'^/dev/([a-zA-Z]+[0-9]+)p[0-9]+$')
    matched_alnum = False
    dev_set = set()
    for path in self.shell('cgpt find -t rootfs').stdout.strip().split():
      for dev in alpha_re.findall(path):
        if self._IsDeviceFixed(dev):
          dev_set.add(dev)
          matched_alnum = False
      for dev in alnum_re.findall(path):
        if self._IsDeviceFixed(dev):
          dev_set.add(dev)
          matched_alnum = True
    if len(dev_set) != 1:
      raise Error('zero or multiple primary devs: %s' % dev_set)
    dev_path = os.path.join('/dev', dev_set.pop())
    if partition is None:
      return dev_path
    fmt_str = '%sp%d' if matched_alnum else '%s%d'
    return fmt_str % (dev_path, partition)

  def FindScript(self, script_name):
    """Finds the script under /usr/local/factory/sh

    Args:
      script_name: The name of the script to look for.

    Returns:
      The path of the found script.

    Raises:
      Error if the script is not found.
    """

    # __file__ is in /usr/local/factory/py/gooftool/__init__.py
    factory_base = os.path.realpath(os.path.join(
        os.path.dirname(os.path.realpath(__file__)), '..', '..'))
    script_path = os.path.join(factory_base, 'sh', script_name)
    if not os.path.isfile(script_path):
      raise Error('Needed script %s does not exist.' % script_path)
    return script_path

  def FindAndRunScript(self, script_name, post_opts=None, pre_opts=None):
    """Finds and runs the script with given options.

    Args:
      script_name: The name of the script to look up and run.
      post_opts: A list of strings that will be appended in the command after
        the script's name.
      pre_opts: A list of strings that will be prepended in the command before
        the script's name.

    Returns:
      The result of execusion.

    Raises:
      Error if execusion failed.
    """

    assert not post_opts or isinstance(post_opts, list)
    assert not pre_opts or isinstance(pre_opts, list)

    script = self.FindScript(script_name)
    cmd = '%s %s %s' % (" ".join(pre_opts) if pre_opts else "",
                        script,
                        " ".join(post_opts) if post_opts else "")
    result = self.shell(cmd.strip())
    if not result.success:
      raise Error, '%r failed, stderr: %r' % (cmd, result.stderr)

    return result

  def GetReleaseRootPartitionPath(self):
    """Gets the path for release root partition."""

    return self.GetPrimaryDevicePath(5)

  def GetReleaseKernelPartitionPath(self):
    """Gets the path for release kernel partition."""

    return self.GetPrimaryDevicePath(4)

  def GetVBSharedDataFlags(self):
    """Gets VbSharedData flags.

    Returns:
      An integer representation of the flags.
    """

    return int(self.shell('crossystem vdat_flags').stdout.strip(), 0)

  def GetCurrentDevSwitchPosition(self):
    """Gets the position for the current developer switch.

    Returns:
      An integer representation of the current developer switch position.
    """
    return int(self.shell('crossystem devsw_cur').stdout.strip(), 0)

  def GetCrosSystem(self):
    """Gets the output of 'crossystem'.

    Returns:
      A dict for key-value pairs for the output of 'crossystem'.
      e.g. {'flag_name': 'flag_value'}
    """
    crossystem_result = self.shell('crossystem').stdout.strip().splitlines()
    # The crossytem output contains many lines like:
    # 'key = value  # description'
    # Use regexps to pull out the key-value pairs and build a dict.
    # Note that value could also contain equal signs.
    output = {}
    for entry in crossystem_result:
      # Any unrecognized format should fail here.
      key, value = re.findall(r'\A(\S+)\s+=\s+(.*)#.*\Z', entry)[0]
      output[key] = value.strip()

    return output

class Gooftool(object):
  """A class to perform hardware probing and verification and to implement
  Google required tests.

  Properties:
    db: The HWID DB.  This is lazily loaded the first time it is used.
    _db_creator: The function used to create the db object the first time
      it is used.
  """
  # TODO(andycheng): refactor all other functions in gooftool.py to this.

  def __init__(self, probe=None, hwid_version=2,
               hardware_db=None, component_db=None,
               board=None, hwdb_path=None):
    """Constructor.

    Args:
      probe: The probe to use for detecting installed components. If not
        specified, cros.factory.gooftool.probe.Probe is used.
      hwid_version: The HWID version to operate on. Currently there are only two
        options: 2 or 3.
      hardware_db: The hardware db to use. If not specified, the one in
        hwid_tool.DEFAULT_HWID_DATA_PATH is used.
      component_db: The component db to use for both component names and
        component classes lookup. If not specified,
        hardware_db.component.db is used.
      board: A string indicating which board-specific component database to
        load. If not specified, the board name will be detected with
        cros.factory.hwid.ProbeBoard(). Used for HWID v3 only.
      hwdb_path: The path to load the board-specific component database from. If
        not specified, cros.factory.hwid.DEFAULT_HWID_DATA_PATH will be used.
        Used for HWID v3 only.
    """
    self._hwid_version = hwid_version
    if hwid_version == 2:
      self._hardware_db = (
          hardware_db or
          hwid_tool.HardwareDb(hwid_tool.DEFAULT_HWID_DATA_PATH))
      self._db_creator = lambda: component_db or self._hardware_db.comp_db
    elif hwid_version == 3:
      self._board = board or hwid3_common.ProbeBoard()
      self._hwdb_path = hwdb_path or hwid3_common.DEFAULT_HWID_DATA_PATH
      self._db_creator = lambda: Database.LoadFile(
          os.path.join(self._hwdb_path, self._board.upper()))
    else:
      raise ValueError("Invalid HWID version: %r" % hwid_version)

    self._probe = probe or Probe
    self._util = Util()
    self._crosfw = crosfw
    self._read_ro_vpd = ReadRoVpd
    self._read_rw_vpd = ReadRwVpd
    self._hwid_decode = Decode
    self._unpack_bmpblock = unpack_bmpblock
    self._named_temporary_file = NamedTemporaryFile
    self._db = None

  @property
  def db(self):
    """Lazy loader for the HWID database."""
    if not self._db:
      self._db = self._db_creator()
      # Hopefully not necessary, but just a safeguard to prevent
      # accidentally loading the DB multiple times.
      del self._db_creator
    return self._db

  def VerifyComponents(self, component_list):
    """Verifies the given component list against the component db to ensure
    the installed components are correct.

    Args:
      component_list: A list of components to verify.
        (e.g., ['camera', 'cpu'])

    Returns:
      A dict from component class to a list of one or more
      ProbedComponentResult tuples.
      {component class: [ProbedComponentResult(
          component_name,  # The component name if found in the db, else None.
          probed_string,   # The actual probed string. None if probing failed.
          error)]}         # The error message if there is one.
    """
    probeable_classes = self.db.probeable_components.keys()
    if not component_list:
      raise ValueError("No component classes specified;\n" +
                       "Possible choices: %s" % probeable_classes)

    unknown_class = [component_class for component_class in component_list
                     if component_class not in probeable_classes]
    if unknown_class:
      raise ValueError(("Invalid component classes specified: %s\n" +
                        "Possible choices: %s") %
                        (unknown_class, probeable_classes))

    probe_results = self._probe(
        target_comp_classes=component_list,
        probe_volatile=False, probe_initial_config=False)
    result = {}
    for comp_class in sorted(component_list):
      probe_vals = probe_results.found_probe_value_map.get(comp_class, None)

      if probe_vals is not None:
        if isinstance(probe_vals, str):
          # Force cast probe_val to be a list so it is easier to process later
          probe_vals = [probe_vals]

        result_tuples = []
        for val in probe_vals:
          comp_name = self.db.result_name_map.get(val, None)
          if comp_name is not None:
            result_tuples.append(ProbedComponentResult(comp_name, val, None))
          else:
            result_tuples.append(ProbedComponentResult(None, val, (
                'unsupported %r component found with probe result'
                ' %r (no matching name in the component DB)' %
                (comp_class, val))))
        result[comp_class] = result_tuples
      else:
        result[comp_class] = [ProbedComponentResult(None, None, (
            'missing %r component' % comp_class))]

    return result

  def FindBOMMismatches(self, board, bom_name, probed_comps):
    """Finds mismatched components for a BOM.

    Args:
      board: The name of the board containing a list of BOMs .
      bom_name: The name of the BOM listed in the hardware database.
      probed_comps: A named tuple for probed results.
        Format: (component_name, probed_string, error)

    Returns:
      A dict of mismatched component list for the given BOM.
      {component class: [Mismatch(
        expected,  # The expected result.
        actual)]}  # The actual probed result.
    """

    if board not in self._hardware_db.devices:
      raise ValueError("Unable to find BOMs for board %r" % board)

    boms = self._hardware_db.devices[board].boms
    if not bom_name or not probed_comps:
      raise ValueError("both bom_name and probed components must be specified")

    if bom_name not in boms:
      raise ValueError("BOM %r not found. Available BOMs: %s" % (
          bom_name, boms.keys()))

    primary = boms[bom_name].primary
    mismatches = {}

    for comp_class, results in probed_comps.items():
      if comp_class in primary.classes_dontcare:  # skip don't care components
        continue

      # If a component is expected to be missing, then empty probed result
      # is expected.
      if comp_class in primary.classes_missing and (
          not any(result.probed_string for result in results)):
        continue

      if comp_class not in primary.components:
        mismatches[comp_class] = Mismatch(None, results)
        continue

      # Since the component names could be either str or list of str,
      # detect its type before converting to a set.
      expected_names = primary.components[comp_class]
      if isinstance(expected_names, str):
        expected_names = [expected_names]
      expected_names = set(expected_names)

      probed_comp_names = set([result.component_name for result in results])

      if probed_comp_names != expected_names:
        mismatches[comp_class] = Mismatch(expected_names, probed_comp_names)

    return mismatches

  def VerifyKeys(self):
    """Verify keys in firmware and SSD match."""

    return self._util.FindAndRunScript(
        'verify_keys.sh',
        [self._util.GetReleaseKernelPartitionPath(),
         self._crosfw.LoadMainFirmware().GetFileName()])

  def VerifySystemTime(self):
    """Verify system time is later than release filesystem creation time."""

    return self._util.FindAndRunScript(
        'verify_system_time.sh',
        [self._util.GetReleaseRootPartitionPath()])

  def VerifyRootFs(self):
    """Verify rootfs on SSD is valid by checking hash."""
    return self._util.FindAndRunScript(
        'verify_rootfs.sh',
        [self._util.GetReleaseRootPartitionPath()])

  def VerifyTPM(self):
    """Verify TPM is cleared."""
    tpm_status = ParseDict(GetLines(
        CheckOutput(['cryptohome', '--action=tpm_status']),
        True))
    tpm_cleared_status = {
        'TPM Enabled': 'true',
        'TPM Owned': 'false',
        'TPM Being Owned': 'false'}
    if any(tpm_status[k] != v for k, v in tpm_cleared_status.iteritems()):
      raise Error, 'TPM is not cleared.'

  def ClearGBBFlags(self):
    """Zero out the GBB flags, in preparation for transition to release state.

    No GBB flags are set in release/shipping state, but they are useful
    for factory/development.  See "gbb_utility --flags" for details.
    """

    self._util.FindAndRunScript('clear_gbb_flags.sh')

  def PrepareWipe(self, is_fast=None):
    """Prepare system for transition to release state in next reboot.

    Args:
      is_fast: Whether or not to apply fast wipe.
    """

    self._util.FindAndRunScript(
        'prepare_wipe.sh',
        [self._util.GetReleaseRootPartitionPath()],
        ['FACTORY_WIPE_TAGS=fast'] if is_fast else [])

  def Probe(self, target_comp_classes, fast_fw_probe=False, probe_volatile=True,
            probe_initial_config=True, probe_vpd=False):
    """Returns probed results for device components, hash, and initial config
    data.

    This method is essentially a wrapper for probe.Probe. Please refer to
    probe.Probe for more detailed description.

    Args:
      target_comp_classes: Which component classes to probe for.  A None value
        implies all classes.
      probe_volatile: On False, do not probe for volatile data and
        return None for the corresponding field.
      probe_initial_config: On False, do not probe for initial_config
        data and return None for the corresponding field.
      probe_vpd: On True, include vpd data in the volatiles.

    Returns:
      cros.factory.hwdb.hwid_tool.ProbeResults object containing the probed
      results.
    """

    return self._probe(target_comp_classes=target_comp_classes,
                       fast_fw_probe=fast_fw_probe,
                       probe_volatile=probe_volatile,
                       probe_initial_config=probe_initial_config,
                       probe_vpd=probe_vpd)

  def WriteHWID(self, hwid=None):
    """Writes specified HWID value into the system BB.

    Args:
      hwid: The HWID string to be written to the device.
    """

    assert hwid
    main_fw = self._crosfw.LoadMainFirmware()
    self._util.shell('gbb_utility --set --hwid="%s" "%s"' %
          (hwid, main_fw.GetFileName()))
    main_fw.Write(sections=['GBB'])

  def VerifyWPSwitch(self):  # pylint: disable=W0613
    """Verifes hardware write protection switch is enabled.

    Raises:
      Error when there is an error.
    """

    if self._util.shell('crossystem wpsw_cur').stdout.strip() != '1':
      raise Error, 'write protection switch is disabled'

  def CheckDevSwitchForDisabling(self):  # pylint: disable=W0613
    """Checks if the developer switch is ready for disabling.

    It checks the developer switch is either already disabled or is virtual so
    it could be disabled programmatically.

    Returns:
      Whether or not the developer switch is virtual.

    Raises:
      Error, if the developer switch is not ready for disabling. i.e. it is not
      disabled and it is not virtual.
    """

    VBSD_HONOR_VIRT_DEV_SWITCH = 0x400
    if (self._util.GetVBSharedDataFlags() & VBSD_HONOR_VIRT_DEV_SWITCH) != 0:
      # Note when the system is using virtual developer switch. It could be
      # disabled by "crossystem disable_dev_request=1", which is exactly what
      # it does in prepare_wipe.sh.
      return True

    if self._util.GetCurrentDevSwitchPosition() == 0:
      return False

    raise Error, 'developer mode is not disabled'

  def SetFirmwareBitmapLocale(self):
    """Sets firmware bitmap locale to the default value stored in VPD.

    This function ensures the default locale set in VPD is listed in the
    supported locales in the firmware bitmap and sets loc_idx to the default
    locale.

    Returns:
      A tuple of the default locale index and default locale. i.e.
      (index, locale)

      index: The index of the default locale in the bitmap.
      locale: The 2-character-string format of the locale. e.g. "en", "zh"

    Raises:
      Error, if the initial locale is missing in VPD or the default locale is
      not supported.
    """
    image_file = self._crosfw.LoadMainFirmware().GetFileName()
    locale = self._read_ro_vpd(image_file).get('initial_locale', None)
    if locale is None:
      raise Error, 'Missing initial_locale VPD.'
    bitmap_locales = []
    with self._named_temporary_file() as f:
      self._util.shell('gbb_utility -g --bmpfv=%s %s' % (f.name, image_file))
      bmpblk_data = self._unpack_bmpblock(f.read())
      bitmap_locales = bmpblk_data.get('locales', bitmap_locales)

    # Some locale values are just a language code and others are a
    # hyphen-separated language code and country code pair.  We care
    # only about the language code part for some cases. We need to
    # replace hyphen with underscore for some cases.
    for language_code in [locale.replace('-','_'), locale.partition('-')[0]]:
      if language_code in bitmap_locales:
        locale_index = bitmap_locales.index(language_code)
        self._util.shell('crossystem loc_idx=%d' % locale_index)
        return (locale_index, language_code)

    raise Error, ('Firmware bitmaps do not contain support for the specified '
                  'initial locale language %r' % locale)

  def GetSystemDetails(self):
    """Gets the system details including: platform name, crossystem,
    modem status, EC write-protect status and bios write-protect status.

    Returns:
      A dict of system details with the following format:
          {Name_of_the_detail: "result of the detail"}
      Note that the outputs could be multi-line strings.
    """

    # Note: Handle the shell commands with care since unit tests cannot
    # ensure the correctness of commands executed in shell.
    return {
        'platform_name': self._util.shell('mosys platform name').stdout.strip(),
        'crossystem': self._util.GetCrosSystem(),
        'modem_status': self._util.shell('modem status').stdout.splitlines(),
        'ec_wp_status': self._util.shell(
            'flashrom -p ec --get-size 2>/dev/null && '
            'flashrom -p ec --wp-status || '
            'echo "EC is not available."').stdout,
        'bios_wp_status': self._util.shell(
            'flashrom -p host --wp-status').stdout}

  def VerifyComponentsV3(self, component_list, fast_fw_probe=False):
    """Verifies the given component list against the component db to ensure
    the installed components are correct. This method uses the HWIDv3 component
    database to verify components.

    Args:
      component_list: A list of components to verify.
        (e.g., ['camera', 'cpu'])

    Returns:
      A dict from component class to a list of one or more
      ProbedComponentResult tuples.
      {component class: [ProbedComponentResult(
          component_name,  # The component name if found in the db, else None.
          probed_string,   # The actual probed string. None if probing failed.
          error)]}         # The error message if there is one.
    """
    if self._hwid_version != 3:
      raise Error, 'hwid_version needs to be 3 to run VerifyComponentsV3'
    if not component_list:
      yaml_probe_results = self._probe().Encode()
    else:
      yaml_probe_results = self._probe(
          target_comp_classes=component_list, fast_fw_probe=fast_fw_probe,
          probe_volatile=False, probe_initial_config=False).Encode()
    return self.db.VerifyComponents(yaml_probe_results, component_list)

  def GenerateHwidV3(self, device_info=None, probe_results=None,
                     probed_ro_vpd=None, probed_rw_vpd=None,
                     rma_mode=False):
    """Generates the version 3 HWID of the DUT.

    The HWID is generated based on the given device info and probe result. If
    there are conflits about component information between device_info and
    probe_results, priority is given to device_info.

    Args:
      device_info: A dict of component infomation keys to their corresponding
        values. The format is device-specific and the meanings of each key and
        value vary from device to device. The valid keys and values should be
        specified in board-specific component database.
      probe_results: A ProbeResults object containing the probe result to be
        used.
      probed_ro_vpd: A dict of RO VPD values.
      probed_rw_vpd: A dict of RW VPD values.
      rma_mode: Whether to verify components status in RMA mode.

    Returns:
      The generated HWID object.
    """
    if self._hwid_version != 3:
      raise Error, 'hwid_version needs to be 3 to run GenerateHwidV3'
    if not probe_results:
      probe_results = self._probe(None)
    # pylint: disable=E1101
    if not isinstance(probe_results, hwid_tool.ProbeResults):
      raise Error, 'probe_results is not a ProbeResults object'

    if rma_mode:
      hwid_mode = hwid3_common.HWID.OPERATION_MODE.rma
    else:
      hwid_mode = hwid3_common.HWID.OPERATION_MODE.normal

    # Construct a base BOM from probe_results.
    device_bom = self.db.ProbeResultToBOM(probe_results.Encode())
    hwid = Encode(self.db, device_bom, mode=hwid_mode, skip_check=True)

    # Verify the probe result with the generated HWID to make sure nothing is
    # mis-configured after setting default values to unprobeable encoded fields.
    hwid.VerifyProbeResult(probe_results.Encode())

    # Get the VPD on the system if no VPD values are given.
    if probed_ro_vpd is None:
      probed_ro_vpd = vpd.ro.GetAll()
    if probed_rw_vpd is None:
      probed_rw_vpd = vpd.rw.GetAll()
    vpd_dict = {'ro': {}, 'rw': {}}
    vpd_dict['ro'].update(probed_ro_vpd)
    vpd_dict['rw'].update(probed_rw_vpd)

    # Update unprobeable components with rules defined in database.
    context = Context(hwid=hwid, device_info=device_info, vpd=vpd_dict)
    self.db.rules.EvaluateRules(context, namespace='device_info.*')
    # Verify status of components base of RMA mode setting.
    hwid.VerifyComponentStatus()
    return hwid

  def VerifyHwidV3(self, encoded_string=None, probe_results=None,
                   probed_ro_vpd=None, probed_rw_vpd=None, rma_mode=False):
    """Verifies the given encoded version 3 HWID string against the component
    db.

    A HWID context is built with the encoded HWID string and the board-specific
    component database. The HWID context is used to verify that the probe
    results match the infomation encoded in the HWID string.

    RO and RW VPD are also loaded and checked against the required values stored
    in the board-specific component database.

    Args:
      encoded_string: The encoded HWID string to test. If not specified,
        defaults to the HWID read from GBB on DUT.
      probe_results: A ProbeResults object containing the probe result to be
        tested. If not specified, defaults to the probe result got with
        self._probe().
      probed_ro_vpd: A dict of probed RO VPD keys and values. If not specified,
        defaults to the RO VPD stored on DUT.
      probed_rw_vpd: A dict of probed RW VPD keys and values. If not specified,
        defaults to the RW VPD stored on DUT.
      rma_mode: True for RMA mode to allow deprecated components. Defaults to
        False.
    """
    if self._hwid_version != 3:
      raise Error, 'hwid_version needs to be 3 to run VerifyHwidV3'
    if not all([encoded_string, probed_ro_vpd, probed_rw_vpd]):
      main_fw_file = crosfw.LoadMainFirmware().GetFileName()
    if not encoded_string:
      gbb_result = self._util.shell(
          'gbb_utility -g --hwid %s' % main_fw_file).stdout
      encoded_string = re.findall(r'hardware_id:(.*)', gbb_result)[0].strip()
    if not probe_results:
      probe_results = self._probe(None)
    # pylint: disable=E1101
    if not isinstance(probe_results, hwid_tool.ProbeResults):
      raise Error, 'probe_results is not a ProbeResults object'
    if probed_ro_vpd is None:
      probed_ro_vpd = self._read_ro_vpd(main_fw_file)
    if probed_rw_vpd is None:
      probed_rw_vpd = self._read_rw_vpd(main_fw_file)

    if rma_mode:
      hwid_mode = hwid3_common.HWID.OPERATION_MODE.rma
    else:
      hwid_mode = hwid3_common.HWID.OPERATION_MODE.normal
    hwid = self._hwid_decode(self.db, encoded_string, mode=hwid_mode)
    hwid.VerifyProbeResult(probe_results.Encode())
    hwid.VerifyComponentStatus()
    vpd_dict = {'ro': {}, 'rw': {}}
    vpd_dict['ro'].update(probed_ro_vpd)
    vpd_dict['rw'].update(probed_rw_vpd)
    context = Context(hwid=hwid, vpd=vpd_dict)
    self.db.rules.EvaluateRules(context, namespace="verify.*")

  def DecodeHwidV3(self, encoded_string):
    """Decodes the given HWIDv3 encoded string and returns the decoded info.

    Args:
      encoded_string: The encoded HWID string to test. If not specified,
        use gbb_utility to get HWID.

    Returns:
      The decoded HWIDv3 context object.
    """
    if self._hwid_version != 3:
      raise Error, 'hwid_version needs to be 3 to run DecodeHwidV3'
    if not encoded_string:
      main_fw_file = crosfw.LoadMainFirmware().GetFileName()
      gbb_result = self._util.shell(
          'gbb_utility -g --hwid %s' % main_fw_file).stdout
      encoded_string = re.findall(r'hardware_id:(.*)', gbb_result)[0].strip()
    decoded_hwid_context = Decode(self.db, encoded_string)
    return decoded_hwid_context

  def FindBOMMismatchesV3(self, board, bom_name, probed_comps):
    """Finds mismatched components for a BOM. This method uses the HWIDv3
    component database to match components.

    Args:
      board: The name of the board containing a list of BOMs .
      bom_name: The name of the BOM listed in the hardware database.
      probed_comps: A named tuple for probed results.
        Format: (component_name, probed_string, error)

    Returns:
      A dict of mismatched component list for the given BOM.
      {component class: [Mismatch(
        expected,  # The expected result.
        actual)]}  # The actual probed result.
    """
    # TODO(jcliang): Re-implement this after rule language refactoring.
    pass

  def ClearFactoryVPDEntries(self):
    """Clears factory.* items in the RW VPD.

    Returns:
      A dict of the removed entries.
    """
    entries = dict((k, v) for k, v in vpd.rw.GetAll().items()
                   if k.startswith('factory.'))
    logging.info('Removing VPD entries %s', FilterDict(entries))
    vpd.rw.Delete(*entries.keys())

  def GetHWIDV3List(self, image_id=None):
    """Generate all components of HWID with image_id for the board.

    Args:
      image_id: The image id of the board. If image_id is omitted,
        The maximum of image id will be used.

    Returns:
      a dict of HWID and components set.
    """

    def _GenerateEncodedString(encoded_fields):
      """Generate encoded string by encoded_fields

      Args:
        encoded_fields: This parameter records indices of encoded fields
      """
      encoding_pattern = 0
      pass_check = True
      components = collections.defaultdict(list)
      component_list = []
      for field, index in encoded_fields.iteritems():
        # pylint: disable=W0212
        attr_dict = self.db._GetAttributesByIndex(field, index)
        comp_items = []
        for comp_cls, attr_list in attr_dict.iteritems():
          if attr_list is None:
            comp_items.append('None')
            components[comp_cls].append(common.ProbedComponentResult(
                None, None, common.MISSING_COMPONENT_ERROR(comp_cls)))
          else:
            for attrs in attr_list:
              if attrs.get('status') in (
                  hwid3_common.HWID.COMPONENT_STATUS.unsupported,
                  hwid3_common.HWID.COMPONENT_STATUS.deprecated):
                pass_check = False
                break
              comp_items.append(attrs['name'])
              components[comp_cls].append(common.ProbedComponentResult(
                  attrs['name'], attrs['values'], None))
        component_list.append(' '.join(comp_items))
      if pass_check:
        bom = common.BOM(self._board, encoding_pattern, image_id, components,
            encoded_fields)
        binary_string = BOMToBinaryString(self.db, bom)
        encoded_string = BinaryStringToEncodedString(self.db, binary_string)
        hwid_dict[encoded_string] = ','.join(component_list)

    def _RecursivelyGenerate(index=None, encoded_fields=None):
      """Recursive function to generate all combinations.

      Args:
        index: This parameter means the index of pattern fields
        encoded_fields: This parameter records index of components
      """
      if index >= len(fields_list):
        _GenerateEncodedString(encoded_fields)
        return

      field = fields_list[index]
      if field not in fields_bits.keys():
        encoded_fields[field] = 0
        _RecursivelyGenerate(index + 1, encoded_fields)
      else:
        for i in xrange(0, len(self.db.encoded_fields[field])):
          if i >= 2 ** fields_bits[field]:
            break
          encoded_fields[field] = i
          _RecursivelyGenerate(index + 1, encoded_fields)


    def _GetImageID(_image_id=None):
      """Image ID from three ways
      1. number
      2. Image ID name
      3. if _image_id is None, return the maximum image id
      """
      max_image_id = max(self.db.image_id.keys())
      if _image_id is None:
        _image_id = max_image_id
      else:
        if _image_id.isdigit():
          _image_id = int(_image_id)
        else:
          for k, v in self.db.image_id.iteritems():
            if _image_id == v:
              _image_id = k
        assert _image_id in range(0, max_image_id+1), "Invalid Image ID"
      return _image_id

    hwid_dict = {}
    encoded_fields = collections.defaultdict(int)
    #The first step is to choose image_id
    image_id = _GetImageID(image_id)

    fields_bits = collections.defaultdict(int)
    for field in self.db.pattern.GetPatternByImageId(image_id)['fields']:
      comp, bit_width = field.items()[0]
      fields_bits[comp] += bit_width
    fields_list = []
    for comp_cls in self.db.encoded_fields.keys():
      fields_list.append(comp_cls)

    #Use recursive to generate all combinations of HWID
    _RecursivelyGenerate(0, encoded_fields)
    return hwid_dict
