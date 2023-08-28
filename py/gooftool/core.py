# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import codecs
from collections import namedtuple
from contextlib import contextmanager
import datetime
from distutils.version import LooseVersion
import enum
import glob
import logging
import os
import re
import sys
import tempfile
import time

import yaml

from cros.factory.gooftool import bmpblk
from cros.factory.gooftool.common import Util
from cros.factory.gooftool import gbb
from cros.factory.gooftool import management_engine
from cros.factory.gooftool import vpd_utils
from cros.factory.gooftool import wipe
from cros.factory.hwid.v3.database import Database
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test.l10n import regions
from cros.factory.test.rules import phase
from cros.factory.test.utils import bluetooth_utils
from cros.factory.test.utils import cbi_utils
from cros.factory.test.utils import gsc_utils
from cros.factory.test.utils import model_sku_utils
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import pygpt
from cros.factory.utils import sys_utils
from cros.factory.utils.type_utils import Error

from cros.factory.external.chromeos_cli import cros_config
from cros.factory.external.chromeos_cli import flashrom
from cros.factory.external.chromeos_cli import futility
from cros.factory.external.chromeos_cli import gsctool
from cros.factory.external.chromeos_cli import ifdtool
from cros.factory.external.chromeos_cli import vpd


# The mismatch result tuple.
Mismatch = namedtuple('Mismatch', ['expected', 'actual'])

_FIRMWARE_RELATIVE_PATH = 'usr/sbin/chromeos-firmwareupdate'

_MINIOS_VERIY_ERROR_TEMPLATE = 'Please run copy_minios pytest to fix it.'

_DLCVERIFY = 'dlcverify'

_DLCMETADATADIR = 'opt/google/dlc'

_DLC_ERROR_TEMPLATE = (
    'If you install the images via network, please make sure you use docker '
    'image version >= `20211102181209`. To re-install the DLC images, please '
    'run pytest `check_image_version.py` with argument `reinstall_only_dlc` '
    'set to true. For more information about DLCs, please read the partner '
    'site document: (Google partners only) https://chromeos.google.com/partner/'
    'dlm/docs/factory/factory-dlc-support.html.')


class FinalizeMode(str, enum.Enum):
  """The process that a device/MLB is needed before leaving the factory.

  MLB: The MLB is expected to leaving the factory after SMT, such as local
    OEM project or MLB for RMA.
  SHIMLESS_MLB: The MLB is produced for shimless RMA.
  ASSEMBLED: Verify the final state of the DUT and make it enter shipping mode.
  TODO(b/171467079): Add the reference doc in #1.
  """
  MLB = 'MLB'
  SHIMLESS_MLB = 'SHIMLESS_MLB'
  ASSEMBLED = 'ASSEMBLED'


class FactoryProcessEnum(str, enum.Enum):
  """The process that a device/MLB is produced or assembled.

  FULL: The device runs full factory process in current factory.
  TWOSTAGES: The MLB part is sent to a different location for assembly, such
    as local OEM project or MLB for RMA.
  RMA: The device runs factory process in RMA center.
  Check
  https://docs.google.com/document/d/15v7O8LWFL_tbTp2X4PKedGZ4IQAP11ZQeKsTJ_eQp1s/preview
  for details.
  """
  FULL = 'FULL'
  TWOSTAGES = 'TWOSTAGES'
  RMA = 'RMA'


class IdentitySourceEnum(str, enum.Enum):
  cros_config = 'Cros Config Database'
  current_identity = 'Current Identity'


class CrosConfigIdentity(dict):
  message_template = '%s:\nproduct name: %s\nsku id: %s\n' + \
      'frid: %s\ncustomization id: %s\ncustom label tag: %s\n'

  def __init__(self, config_source):
    dict.__init__(self)
    self.config_source = config_source.value
    identity_key_list = [
        'smbios-name-match',
        'sku-id',
        'frid',
        'device-tree-compatible-match',
    ] + [vpd_utils.IDENTITY_VPD_FIELDS.values()]
    for key in identity_key_list:
      self[key] = ''

  def __str__(self):
    product_name = self['smbios-name-match'] or \
        self['device-tree-compatible-match'] or 'empty'
    return CrosConfigIdentity.message_template % (
        self.config_source, product_name, self['sku-id'], self['frid'],
        self['customization-id'], self['custom-label-tag'])


class CrosConfigError(Error):
  message_template = '%s. Identity may be misconfigured.\n%s\n%s'

  def __init__(self, message, db_identity, cur_identity):
    Error.__init__(self)
    self.message = message
    self.db_identity = db_identity
    self.cur_identity = cur_identity

  def __str__(self):
    return CrosConfigError.message_template % (self.message, self.db_identity,
                                               self.cur_identity)

class HWWPError(Error):
  pass


class Gooftool:
  """A class to perform hardware probing and verification and to implement
  Google required tests.

  Properties:
    db: The HWID DB.  This is lazily loaded the first time it is used.
    _db_creator: The function used to create the db object the first time
      it is used.
  """
  # TODO(andycheng): refactor all other functions in gooftool.py to this.

  def __init__(self, hwid_version=3, project=None, hwdb_path=None):
    """Constructor.

    Args:
      hwid_version: The HWID version to operate on. Currently there is only one
        option: 3.
      project: A string indicating which project-specific component database to
        load. If not specified, the project name will be detected with
        cros.factory.hwid.ProbeProject(). Used for HWID v3 only.
      hwdb_path: The path to load the project-specific component database from.
        If not specified, cros.factory.hwid.hwid_utils.GetDefaultDataPath() will
        be used.  Used for HWID v3 only.
    """
    self._hwid_version = hwid_version
    if hwid_version == 3:
      self._project = project or hwid_utils.ProbeProject()
      self._hwdb_path = hwdb_path or hwid_utils.GetDefaultDataPath()
      self._db_creator = lambda: Database.LoadFile(
          os.path.join(self._hwdb_path, self._project.upper()))
    else:
      raise ValueError(f'Invalid HWID version: {hwid_version!r}')

    self._util = Util()
    self._flashrom = flashrom
    self.vpd = vpd.VPDTool()
    self.vpd_utils = vpd_utils.VPDUtils(self._project)
    self._unpack_gbb = gbb.UnpackGBB
    self._unpack_bmpblock = bmpblk.unpack_bmpblock
    self._named_temporary_file = tempfile.NamedTemporaryFile
    self._db = None
    self._cros_config = cros_config.CrosConfig()
    self._gsctool = gsctool.GSCTool()
    self.gsc_utils = gsc_utils.GSCUtils()
    self._ifdtool = ifdtool
    self.futility = futility.Futility()

  def GetLogicalBlockSize(self):
    """Get the logical block size of a DUT by reading file under /sys/block.

    Returns:
      The logical block size of a primary device.

    Raises:
      Error will be raised if the primary device is removable.
    """
    # GetPrimaryDevicePath() returns the device path under /dev.
    # For instance, on DUT with NVMe, it returns `/dev/nvme0n1`.
    # However, we only want its basename.
    dev_basename = os.path.basename(self._util.GetPrimaryDevicePath())
    # This is the same as `lsblk -d -n -r -o log-sec ${dev}`.
    logical_block_size_file = os.path.join(os.sep, 'sys', 'block', dev_basename,
                                           'queue', 'logical_block_size')
    logical_block_size = file_utils.ReadFile(logical_block_size_file)

    return int(logical_block_size)

  def IsReleaseLVM(self):
    """Check if release image has LVM stateful partition."""

    with sys_utils.MountPartition(
        self._util.GetReleaseRootPartitionPath()) as root:
      return self._util.UseLVMStatefulPartition(root)

  @property
  def db(self):
    """Lazy loader for the HWID database."""
    if not self._db:
      self._db = self._db_creator()
      # Hopefully not necessary, but just a safeguard to prevent
      # accidentally loading the DB multiple times.
      del self._db_creator
    return self._db

  def VerifyDLCImages(self):
    """Verify if the hashes of the factory installed DLC images are correct.

    The hashes of the factory installed DLC images must match with the DLC
    metadata in release rootfs under `/opt/google/dlc`. We enumerate all the
    factory installed DLC images under stateful partition and compare their
    hashes using `dlcverify`.
    """

    def _ListSubDirectories(dir_path):
      sub_dir_names = []
      for name in os.listdir(dir_path):
        if os.path.isdir(os.path.join(dir_path, name)):
          sub_dir_names.append(name)

      return sub_dir_names

    def _GetNumDLCToBeVerified():
      num_dlcs = 0
      with sys_utils.MountPartition(
          self._util.GetReleaseRootPartitionPath()) as root:
        dlc_metadata_path = os.path.join(root, _DLCMETADATADIR)
        # Enumerate all the possible paths to factory installed DLC metadata.
        sub_dir_names = _ListSubDirectories(dlc_metadata_path)
        for sub_dir_name in sub_dir_names:
          metadata_path = os.path.join(dlc_metadata_path, sub_dir_name,
                                       'package', 'imageloader.json')
          if os.path.exists(metadata_path):
            metadata = json_utils.LoadFile(metadata_path)
            # A DLC is a factory installed DLC if `factory-install` is true.
            if metadata['factory-install']:
              num_dlcs += 1

      return num_dlcs

    dlc_cache_path = os.path.join(wipe.STATEFUL_PARTITION_PATH,
                                  wipe.DLC_CACHE_PAYLOAD_NAME)
    expected_num_dlcs = _GetNumDLCToBeVerified()

    try:
      file_utils.CheckPath(dlc_cache_path)
    except IOError:
      if expected_num_dlcs == 0:
        logging.info(
            'Cannot find %s. Factory installed DLC images are not enabled. '
            'Skip checking.', dlc_cache_path)
        return
      raise Error(
          'No factory installed DLC images found! Expected number of DLCs: '
          f'{int(expected_num_dlcs)}! {_DLC_ERROR_TEMPLATE}') from None

    with file_utils.TempDirectory() as tmpdir:
      # The DLC images are stored as compressed format.
      decompress_command = f'tar -xpvf {dlc_cache_path} -C {tmpdir}'
      logging.info(decompress_command)
      decompress_out = self._util.shell(decompress_command)

      if not decompress_out.success:
        raise Error(
            f'DLC images decompressing failed: {decompress_out.stderr}. '
            f'{_DLC_ERROR_TEMPLATE}')

      dlc_image_path = os.path.join(tmpdir, 'unencrypted', 'dlc-factory-images')

      # Enumerate all the DLC sub-directories under dlc_image_path.
      sub_dir_names = _ListSubDirectories(dlc_image_path)
      cur_num_dlcs = len(sub_dir_names)

      if cur_num_dlcs != expected_num_dlcs:
        raise Error(
            f'Current number of factory installed DLCs: {int(cur_num_dlcs)}, '
            f'expected: {int(expected_num_dlcs)}. {_DLC_ERROR_TEMPLATE}')

      if cur_num_dlcs == 0:
        logging.info('No DLC images under %s. Skip checking.', dlc_image_path)
        return

      # Mount the release rootfs and check the hashes of the images
      error_messages = {}
      with sys_utils.MountPartition(
          self._util.GetReleaseRootPartitionPath()) as root:
        for sub_dir_name in sub_dir_names:
          image_path = os.path.join(dlc_image_path, sub_dir_name, 'package',
                                    'dlc.img')
          verify_command = (
              f'{_DLCVERIFY} --id={sub_dir_name} --image={image_path} '
              f'--rootfs_mount={root}')
          logging.info(verify_command)
          check_hash_out = self._util.shell(verify_command)

          if not check_hash_out.success:
            error_messages[image_path] = check_hash_out.stderr

      if error_messages:
        raise Error(f'{error_messages!r}. {_DLC_ERROR_TEMPLATE}')

  def VerifyFpKey(self):
    """Verify Fingerprint firmware public key.

    Verify the running fingerprint firmware is signed with the same key
    used to sign the fingerprint firmware binary in the release rootfs
    partition.
    """
    fp_board = self._cros_config.GetFingerPrintBoard()
    fp_location = self._cros_config.GetFingerPrintLocation()
    if not fp_board:
      db_identity, cur_identity = self.GetIdentity()
      raise CrosConfigError(
          'Failed to probe fingerprint board from cros_config', db_identity,
          cur_identity)
    if not fp_location or fp_location == 'none':
      raise Error('Fingerprint sensor is absent')

    with sys_utils.MountPartition(
        self._util.GetReleaseRootPartitionPath()) as root:
      fp_fw_pattern = os.path.join(root,
                                   f'opt/google/biod/fw/{fp_board}_v*.bin')
      fp_fw_files = glob.glob(fp_fw_pattern)
      if len(fp_fw_files) != 1:
        raise Error('No uniquely matched fingerprint firmware blob')
      release_key_id = self.futility.GetKeyHashFromFutil(fp_fw_files[0])

    key_id_result = self._util.shell(['ectool', '--name=cros_fp', 'rwsig',
                                      'dump', 'key_id'])
    if not key_id_result.success:
      raise Error('Failed to probe fingerprint key_id from ectool')
    live_key_id = key_id_result.stdout.strip()

    if live_key_id != release_key_id:
      raise Error(
          f'Failed to verify fingerprint key: expects ({release_key_id}) got '
          f'({live_key_id})')

  def VerifyKeys(self, release_rootfs=None, firmware_path=None, _tmpexec=None):
    """Verify keys in firmware and SSD match.

    We need both kernel and rootfs partitions in the release image. However,
    in order to share parameters with other commands, we use the rootfs in the
    release image to calculate the real kernel location.

    Args:
      release_rootfs: A string for release image rootfs path.
      firmware_path: A string for firmware image file path.
      _tmpexec: A function for overriding execution inside temp folder.
    """

    def _VerifyMiniOS(is_dev_rootkey, key_recovery, dir_devkeys):
      # disk_layout_v3.json adds two new partitions (MINIOS-A/B) to conduct
      # network based recovery. MINIOS-A locates at the beginning of the disk,
      # while MINIOS-B locates at the end of the disk. To determine whether a
      # disk layout is disk_layout_v3, we check if the last partition is
      # MINIOS-B.
      gpt = pygpt.GPT.LoadFromFile(self._util.GetPrimaryDevicePath())
      minios_a_no = self._util.MINIOS_A
      minios_b_no = self._util.MINIOS_B
      minios_a_part = self._util.GetPrimaryDevicePath(minios_a_no)
      minios_b_part = self._util.GetPrimaryDevicePath(minios_b_no)
      is_disk_layout_v3 = gpt.IsLastPartition(minios_b_no)

      # Check if minios is ready (see b/199021334#comment6).
      is_minios_ready = False
      if is_disk_layout_v3:
        logging.info('The disk layout version is v3.')

        logging.info(
            'Checking if the size of partition MINIOS_A and MINIOS_B are the '
            'same...')
        if gpt.GetPartition(minios_a_no).blocks != gpt.GetPartition(
            minios_b_no).blocks:
          raise Error(
              'The size of partition MINIOS_A and MINIOS_B are different. '
              f'{_MINIOS_VERIY_ERROR_TEMPLATE}')

        _TmpExec(
            'check if the content of partition MINIOS_A and MINIOS_B are the '
            'same', f'cmp {minios_a_part} {minios_b_part}',
            f'The content of partition MINIOS_A and MINIOS_B are different. '
            f'{_MINIOS_VERIY_ERROR_TEMPLATE}')

        try:
          _TmpExec(
              'check if minios is ready',
              f'futility dump_kernel_config {minios_a_part}',
              'MINIOS partitions are not ready. Skip checking their keys.')
        except Error as err:
          logging.info(err)
        else:
          logging.info('MINIOS partitions are ready.')
          is_minios_ready = True

      check_minios_sign = is_disk_layout_v3 and is_minios_ready

      if check_minios_sign:
        if is_dev_rootkey:
          # Dev-signed firmware is only allowed in early build phases. So we
          # can simply skip checking the signing key of minios partitions and
          # don't have to re-sign using dev-key.
          logging.info('Firmware is dev-signed. Skip checking the signing key'
                       'of minios partitions.')
          return
        logging.info('Checking the signing key of minios partitions...')
        try:
          # Check if minios is officially signed.
          for minios_part in minios_a_part, minios_b_part:
            _TmpExec(
                f'check recovery key signed minios image ({minios_part})',
                f'futility vbutil_kernel --verify {minios_part} '
                f'--signpubkey {key_recovery}')
        except Error:
          # Check if minios is dev-signed.
          for minios_part in minios_a_part, minios_b_part:
            _TmpExec(
                f'check dev-signed minios image ({minios_part})',
                f'! futility vbutil_kernel --verify {minios_part} '
                f'--signpubkey {dir_devkeys}/{key_recovery}',
                f'YOU ARE USING A DEV-SIGNED MINIOS IMAGE. ({minios_part})')
          raise

    if release_rootfs is None:
      release_rootfs = self._util.GetReleaseRootPartitionPath()

    kernel_dev = self._util.GetReleaseKernelPathFromRootPartition(
        release_rootfs)

    if firmware_path is None:
      firmware_path = self._flashrom.LoadMainFirmware().GetFileName()
      firmware_image = self._flashrom.LoadMainFirmware().GetFirmwareImage()
    else:
      with open(firmware_path, 'rb') as f:
        firmware_image = self._flashrom.FirmwareImage(f.read())

    with file_utils.TempDirectory() as tmpdir:

      def _DefaultTmpExec(message, command, fail_message=None, regex=None):
        """Executes a command inside temp folder (tmpdir).

        If regex is specified, return matched string from stdout.
        """
        logging.debug(message)
        result = self._util.shell(f'( cd {tmpdir}; {command} )')
        if not result.success:
          raise Error(fail_message or f'Failed to {message}: {result.stderr}')
        if regex:
          matched = re.findall(regex, result.stdout)
          if matched:
            return matched[0]
        return None

      _TmpExec = _tmpexec if _tmpexec else _DefaultTmpExec

      # define key names
      key_normal = 'kernel_subkey.vbpubk'
      key_normal_a = 'kernel_subkey_a.vbpubk'
      key_normal_b = 'kernel_subkey_b.vbpubk'
      key_root = 'rootkey.vbpubk'
      key_recovery = 'recovery_key.vbpubk'
      blob_kern = 'kern.blob'
      dir_devkeys = '/usr/share/vboot/devkeys'

      logging.debug('dump kernel from %s', kernel_dev)
      with open(kernel_dev, 'rb') as f:
        # The kernel is usually 8M or 16M, but let's read more.
        file_utils.WriteFile(os.path.join(tmpdir, blob_kern),
                             f.read(64 * 1048576), encoding=None)
      logging.debug('extract firmware from %s', firmware_path)
      for section in ('GBB', 'FW_MAIN_A', 'FW_MAIN_B', 'VBLOCK_A', 'VBLOCK_B'):
        file_utils.WriteFile(os.path.join(tmpdir, section),
                             firmware_image.get_section(section), encoding=None)

      _TmpExec(
          'get keys from firmware GBB',
          f'futility gbb -g --rootkey {key_root}  '
          f'--recoverykey {key_recovery} GBB')
      rootkey_hash = _TmpExec('unpack rootkey',
                              f'futility vbutil_key --unpack {key_root}',
                              regex=r'(?<=Key sha1sum:).*').strip()
      _TmpExec('unpack recoverykey',
               f'futility vbutil_key --unpack {key_recovery}')

      # Pre-scan for well-known problems.
      is_dev_rootkey = (
          rootkey_hash == 'b11d74edd286c144e1135b49e7f0bc20cf041f10')
      if is_dev_rootkey:
        logging.warning('YOU ARE TRYING TO FINALIZE WITH DEV ROOTKEY.')
        if phase.GetPhase() >= phase.PVT:
          raise Error('Dev-signed firmware should not be used in PVT phase.')

      _TmpExec(
          'verify firmware A with root key',
          f'futility vbutil_firmware --verify VBLOCK_A --signpubkey {key_root}'
          f'  --fv FW_MAIN_A --kernelkey {key_normal_a}')
      _TmpExec(
          'verify firmware B with root key',
          f'futility vbutil_firmware --verify VBLOCK_B --signpubkey {key_root}'
          f'  --fv FW_MAIN_B --kernelkey {key_normal_b}')

      # Unpack keys and keyblocks
      _TmpExec('unpack kernel keyblock',
               f'futility vbutil_keyblock --unpack {blob_kern}')
      try:
        for key in key_normal_a, key_normal_b:
          _TmpExec(f'unpack {key}', f'vbutil_key --unpack {key}')
          _TmpExec(
              f'verify kernel by {key}',
              f'futility vbutil_kernel --verify {blob_kern} --signpubkey '
              f'{key}')

      except Error:
        _TmpExec(
            'check recovery key signed image',
            f'! futility vbutil_kernel --verify {blob_kern} --signpubkey '
            f'{key_recovery}', 'YOU ARE USING A RECOVERY KEY SIGNED IMAGE.')

        for key in key_normal, key_recovery:
          _TmpExec(
              f'check dev-signed image <{key}>',
              f'! futility vbutil_kernel --verify {blob_kern} --signpubkey '
              f'{dir_devkeys}/{key}',
              f'YOU ARE FINALIZING WITH DEV-SIGNED IMAGE <{key}>')
        raise

      _VerifyMiniOS(is_dev_rootkey, key_recovery, dir_devkeys)

      if not is_dev_rootkey:
        model_name = self._cros_config.GetModelName()
        is_custom_label, custom_label_tag = (
            self._cros_config.GetCustomLabelTag())
        if is_custom_label and custom_label_tag:
          model_name = model_name + "-" + custom_label_tag
        with sys_utils.MountPartition(release_rootfs) as root:
          release_updater_path = os.path.join(root, _FIRMWARE_RELATIVE_PATH)
          _TmpExec('unpack firmware updater from release rootfs partition',
                   f'{release_updater_path} --unpack {tmpdir}')
        release_rootkey_hash = _TmpExec('get rootkey from signer',
                                        'cat VERSION.signer', regex=r'(?<='
                                        f'{model_name}:).*').strip()
        if release_rootkey_hash != rootkey_hash:
          raise Error(
              f'Firmware rootkey is not matched ({release_rootkey_hash} != '
              f'{rootkey_hash}).')

    logging.info('SUCCESS: Verification completed.')

  def VerifySystemTime(self, release_rootfs=None, system_time=None,
                       factory_process=FactoryProcessEnum.FULL):
    """Verify system time is later than release filesystem creation time."""
    if release_rootfs is None:
      release_rootfs = self._util.GetReleaseRootPartitionPath()
    if system_time is None:
      system_time = time.time()

    e2header = self._util.shell(f'dumpe2fs -h {release_rootfs}')
    if not e2header.success:
      raise Error(
          f'Failed to read file system: {release_rootfs}, {e2header.stderr}')
    matched = re.findall(r'^Filesystem created: *(.*)', e2header.stdout,
                         re.MULTILINE)
    if not matched:
      raise Error(f'Failed to find file system creation time: {release_rootfs}')
    created_time = time.mktime(time.strptime(matched[0]))
    logging.debug('Comparing system time <%s> and filesystem time <%s>',
                  system_time, created_time)
    if system_time < created_time:
      if factory_process != FactoryProcessEnum.RMA:
        raise Error(f'System time ({system_time}) earlier than file system '
                    f'({release_rootfs}) creation time ({created_time})')
      logging.warning('Set system time to file system creation time (%s)',
                      created_time)
      self._util.shell(f'toybox date @{int(created_time)}')

  def VerifyRootFs(self, release_rootfs=None):
    """Verify rootfs on SSD is valid by checking hash."""
    if release_rootfs is None:
      release_rootfs = self._util.GetReleaseRootPartitionPath()
    device = self._util.GetPartitionDevice(release_rootfs)

    # TODO(hungte) Using chromeos_invoke_postinst here is leaving a window
    # where unexpected reboot or test exit may cause the system to boot into
    # the release image. Currently "cgpt" is very close to the last step of
    # postinst so it may be OK, but we should seek for better method for this,
    # for example adding a "--nochange_boot_partition" to chromeos-postinst.

    # Always rollback GPT changes.
    curr_attrs = self._util.GetCgptAttributes(device)
    try:
      self._util.InvokeChromeOSPostInstall(release_rootfs)
    finally:
      self._util.SetCgptAttributes(curr_attrs, device)

  def VerifyTPM(self):
    """Verify TPM is cleared."""
    expected_status = {
        'enabled': '1',
        'owned': '0'
    }
    tpm_root = '/sys/class/tpm/tpm0/device'
    legacy_tpm_root = '/sys/class/misc/tpm0/device'
    # TPM device path has been changed in kernel 3.18.
    if not os.path.exists(tpm_root):
      tpm_root = legacy_tpm_root
    for key, value in expected_status.items():
      if file_utils.ReadFile(os.path.join(tpm_root, key)).strip() != value:
        raise Error('TPM is not cleared.')

    expected_tpm_manager_status = {
        'is_enabled': 'true',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }
    tpm_manager_status = self._util.GetTPMManagerStatus()
    for key, value in expected_tpm_manager_status.items():
      if tpm_manager_status[key] != value:
        raise Error('TPM manager status is not cleared.')

  def VerifyManagementEngineLocked(self):
    """Verify Management Engine is locked."""
    main_fw = self._ifdtool.LoadIntelMainFirmware()
    management_engine.VerifyMELocked(main_fw, self._util.shell)

  def VerifyReleaseChannel(self, enforced_channels=None):
    """Verify that release image channel is correct.

    Args:
      enforced_channels: a list of enforced release image channels, might
          be different per board. It should be the subset or the same set
          of the allowed release channels.
    """
    release_channel = self._util.GetReleaseImageChannel()
    allowed_channels = self._util.GetAllowedReleaseImageChannels()

    if enforced_channels is None:
      enforced_channels = allowed_channels
    elif not all(channel in allowed_channels for channel in enforced_channels):
      raise Error(f'Enforced channels are incorrect: {enforced_channels}. '
                  f'Allowed channels are {allowed_channels}.')

    if not any(channel in release_channel for channel in enforced_channels):
      raise Error(f'Release image channel is incorrect: {release_channel}. '
                  f'Enforced channels are {enforced_channels}.')

  def VerifyRLZCode(self):
    if phase.GetPhase() >= phase.EVT:
      rlz = self._cros_config.GetBrandCode()
      if not rlz or rlz == 'ZZCR':
        # this is incorrect...
        raise Error(f'RLZ code "{rlz}" is not allowed in/after EVT')

  def _MatchConfigWithIdentity(self, configs, identity):
    for config in configs:
      config_identity = config['identity']
      mismatch = False
      for key in config_identity.keys():
        if key == 'device-tree-compatible-match':
          # For device-tree-compatible-match, the original way of crosid
          # matching is using a sliding window with width =
          # len(config_identity[key]). For example, the original
          # device-tree-compatible-match for tentacruel is
          # 'google,tentacruelgoogle,corsolamediatek,mt8186'. For each
          # iteration it will try to match the window with 'google,tentacruel'
          # and if it could not match it will slide to the next complete window
          # starting from the next char of the last char in previous window.
          # [google,tentacruel][google,corsolamed][...].
          # We just match it with a simpler way here.
          if config_identity[key] not in identity[key]:
            mismatch = True
            break
        elif key == 'sku-id':
          # For x86 devices the format would be sku + at least 1 digit.
          # For arm devices it does not have sku prefix but in both types of
          # devices the sku-id in config.yaml is interpret as integer, we'll
          # perform a one-time transform here and let no digit cases error out.
          # Note that in some devices like hayato it has no sku-id in
          # config.yaml as it only has one sku. In this case identity['sku-id']
          # would be empty string but we're safe as it would not be compared.
          sku_string = identity[key]
          sku_value = int(sku_string.lstrip('sku'))
          if config_identity[key] != sku_value:
            mismatch = True
            break
        elif config_identity[key] != identity[key]:
          mismatch = True
          break

      if mismatch:
        continue

      for key in vpd_utils.IDENTITY_VPD_FIELDS.values():
        if key not in config_identity and identity[key] != 'empty':
          mismatch = True
          break

      if not mismatch:
        return config
    return None

  def VerifyCrosConfig(self):
    """Verify that entries in cros config make sense."""
    model = self._cros_config.GetModelName()
    if not model:
      db_identity, cur_identity = self.GetIdentity()
      raise CrosConfigError('Model name is empty', db_identity, cur_identity)

    self.vpd_utils.VerifyCacheForIdentity()

    def _ParseCrosConfig(config_path):
      with open(config_path, encoding='utf8') as f:
        obj = yaml.safe_load(f)

      # According to https://crbug.com/1070692, 'platform-name' is not a part of
      # identity info.  We shouldn't check it.
      for config in obj['chromeos']['configs']:
        config['identity'].pop('platform-name', None)

      fields = ['name', 'identity', 'brand-code']
      configs = [{field: config[field]
                  for field in fields}
                 for config in obj['chromeos']['configs']
                 if config['name'] == model]
      return configs

    # Load config.yaml from release image (FSI) and test image, and compare the
    # fields we cared about.
    config_path = 'usr/share/chromeos-config/yaml/config.yaml'
    test_configs = _ParseCrosConfig(os.path.join('/', config_path))
    with sys_utils.MountPartition(
        self._util.GetReleaseRootPartitionPath()) as root:
      release_configs = _ParseCrosConfig(os.path.join(root, config_path))

    unused_db_identity, cur_identity = self.GetIdentity()
    matched_test_config = self._MatchConfigWithIdentity(test_configs,
                                                        cur_identity)
    matched_release_config = self._MatchConfigWithIdentity(
        release_configs, cur_identity)

    error = []
    if matched_test_config and matched_release_config:
      if matched_test_config['brand-code'] != matched_release_config[
          'brand-code']:
        error += ['Detect mismatch brand code between test image and FSI.']
    else:
      if not matched_test_config:
        error += [
            'Cannot match any test image cros config with current identity'
        ]
      if not matched_release_config:
        error += [
            'Cannot match any release image cros config with current identity'
        ]

    if error:
      error += [str(cur_identity)]
      error += ['Configs in test image:']
      error += ['\t' + \
          json_utils.DumpStr(config, sort_keys=True) for config in test_configs]
      error += ['Configs in FSI:']
      error += ['\t' + \
          json_utils.DumpStr(config, sort_keys=True) for config
          in release_configs]
      raise Error('\n'.join(error))

  def EnableReleasePartition(self, release_rootfs=None):
    """Enables a release image partition on the disk.

    Args:
      release_rootfs: path to the release rootfs device. If not specified,
          the default (5th) partition will be used.
    """
    if not release_rootfs:
      release_rootfs = Util().GetReleaseRootPartitionPath()
    wipe.EnableReleasePartition(release_rootfs)


  def WipeInPlace(self, is_fast=None, shopfloor_url=None, station_ip=None,
                  station_port=None, wipe_finish_token=None,
                  boot_to_shimless=False, test_umount=False):
    """Start transition to release state directly without reboot.

    Args:
      is_fast: Whether or not to apply fast wipe.
      boot_to_shimless: Whether to initiate the Shimless RMA after performing
          wiping.
    """
    # check current GBB flags to determine if we need to keep .developer_mode
    # after clobber-state.
    try:
      main_fw = self._flashrom.LoadMainFirmware()
      fw_filename = main_fw.GetFileName(sections=['GBB'])
      gbb_flags = self.futility.GetGBBFlags(fw_filename)
    except Exception:
      logging.warning('Failed to get GBB flags, assume it is 0', exc_info=1)
      gbb_flags = 0

    if (not test_umount and
        phase.GetPhase() >= phase.PVT and gbb_flags != 0):
      raise Error(f'GBB flags should be cleared in PVT (it is {gbb_flags:#x})')

    GBB_FLAG_FORCE_DEV_SWITCH_ON = 0x00000008
    keep_developer_mode_flag = bool(gbb_flags & GBB_FLAG_FORCE_DEV_SWITCH_ON)

    wipe.WipeInRamFs(is_fast, shopfloor_url, station_ip, station_port,
                     wipe_finish_token, keep_developer_mode_flag,
                     boot_to_shimless, test_umount)

  def WipeInit(self, wipe_args, shopfloor_url, state_dev, release_rootfs,
               root_disk, old_root, station_ip, station_port, wipe_finish_token,
               keep_developer_mode_flag, boot_to_shimless, test_umount):
    """Start wiping test image."""
    wipe.WipeInit(wipe_args, shopfloor_url, state_dev, release_rootfs,
                  root_disk, old_root, station_ip, station_port,
                  wipe_finish_token, keep_developer_mode_flag, boot_to_shimless,
                  test_umount)

  def WriteVPDForRLZPing(self, embargo_offset=7):
    """Write VPD values related to RLZ ping into VPD."""

    if embargo_offset < 7:
      raise Error('embargo end date offset cannot less than 7 (days)')

    embargo_date = datetime.date.today()
    embargo_date += datetime.timedelta(days=embargo_offset)

    self.vpd.UpdateData(
        {
            'should_send_rlz_ping': '1',
            'rlz_embargo_end_date': embargo_date.isoformat(),
        }, partition=vpd.VPD_READWRITE_PARTITION_NAME)

  def WriteVPDForMFGDate(self):
    """Write manufacturing date into VPD."""
    mfg_date = datetime.date.today()
    self.vpd.UpdateData({'mfg_date': mfg_date.isoformat()},
                        partition=vpd.VPD_READONLY_PARTITION_NAME)

  def WriteHWID(self, hwid=None):
    """Writes specified HWID value into the system BB.

    Args:
      hwid: The HWID string to be written to the device.
    """

    assert hwid
    main_fw = self._flashrom.LoadMainFirmware()
    fw_filename = main_fw.GetFileName(sections=['GBB'])
    self.futility.WriteHWID(fw_filename, hwid)
    main_fw.Write(fw_filename)

  def ReadHWID(self):
    """Reads the HWID string from firmware GBB."""
    fw_filename = self._flashrom.LoadMainFirmware().GetFileName(
        sections=['GBB'])
    return self.futility.ReadHWID(fw_filename)

  def VerifyWPSwitch(self, has_ectool=True):
    """Verifies hardware write protection switch is enabled.

    Raises:
      Error when there is an error.
    """

    if self._util.shell('crossystem wpsw_cur').stdout.strip() != '1':
      raise HWWPError(
          'write protection switch of hardware is disabled. Please attach '
          'the battery or run `wp enable` on GSC console to enable HWWP.')

    if not has_ectool:
      return

    ectool_flashprotect = self._util.shell('ectool flashprotect').stdout
    if not re.search('^Flash protect flags:.+wp_gpio_asserted',
                     ectool_flashprotect, re.MULTILINE):
      raise Error('write protectioin switch of EC is disabled.')

  def VerifyCBIEEPROMWPStatus(self, cbi_eeprom_wp_status):
    """Verifies CBI EEPROM write protection status."""

    cbi_utils.VerifyCbiEepromWpStatus(self._util.sys_interface,
                                      cbi_eeprom_wp_status)

  def VerifyAltSetting(self):
    """Verifies the usb alt setting for RTL8852CE."""
    bluetooth_utils.VerifyAltSetting()

  def GetBitmapLocales(self, image_file):
    """Get bitmap locales

    Args:
      image_file: Path to the image file where locales are searched.

    Returns:
      List of language codes supported by the image
    """
    bitmap_locales = []
    with self._named_temporary_file('w+') as f:
      self._util.shell(
          f'cbfstool {image_file} extract -n locales -f {f.name} -r COREBOOT')
      bitmap_locales = f.read()
      # We reach here even if cbfstool command fails
      if bitmap_locales:
        # The line format is "code,rtl". We remove ",rtl" here.
        return re.findall(r'^(\S+?)(?:,\S*)?$', bitmap_locales, re.MULTILINE)
      # Looks like image does not have locales file. Do the old-fashioned way
      self._util.shell(f'futility gbb -g --bmpfv={f.name} {image_file}')
      bmpblk_data = self._unpack_bmpblock(f.read())
      bitmap_locales = bmpblk_data.get('locales', bitmap_locales)
    return bitmap_locales

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
    image_file = self._flashrom.LoadMainFirmware().GetFileName()
    ro_vpd = self.vpd.GetAllData(partition=vpd.VPD_READONLY_PARTITION_NAME)
    region = ro_vpd.get('region')
    if region is None:
      raise Error('Missing VPD "region".')
    if region not in regions.REGIONS:
      raise ValueError(f'Unknown region: "{region}".')
    # Use the primary locale for the firmware bitmap.
    locales = regions.REGIONS[region].language_codes
    bitmap_locales = self.GetBitmapLocales(image_file)

    # Some locale values are just a language code and others are a
    # hyphen-separated language code and country code pair.  We care
    # only about the language code part for some cases. Note some old firmware
    # bitmaps use underscore instead hyphen.
    for locale in locales:
      for language_code in [locale, locale.replace('-', '_'),
                            locale.partition('-')[0]]:
        if language_code in bitmap_locales:
          locale_index = bitmap_locales.index(language_code)
          self._util.shell(f'crossystem loc_idx={int(locale_index)}')
          return (locale_index, language_code)

    raise Error(
        'Firmware bitmaps do not contain support for the specified initial '
        f'locales: {locales!r}.\nCurrent supported locales are '
        f'{bitmap_locales!r}.')

  def GetSystemDetails(self):
    """Gets the system details including: platform name, crossystem,
    modem status, EC write-protect status and bios write-protect status.

    Returns:
      A dict of system details with the following format:
          {Name_of_the_detail: "result of the detail"}
      Note that the outputs could be multi-line strings.
    """
    return self._util.GetSystemInfo(filter_vpd=True)

  def GenerateStableDeviceSecret(self):
    """Generates a fresh stable device secret and stores it in RO VPD.

    The stable device secret generated here is a high-entropy identifier that
    is unique to each device. It gets generated at manufacturing time and reset
    during RMA, but is stable under normal operation and notably also across
    recovery image installation.

    The stable device secret is suitable to obtain per-device stable hardware
    identifiers and/or encryption keys. Please never use the secret directly,
    but derive a secret specific for your context like this:

        your_secret = HMAC_SHA256(stable_device_secret,
                                  context_label\0optional_parameters)

    The stable_device_secret acts as the HMAC key. context_label is a string
    that uniquely identifies your usage context, which allows us to generate as
    many per-context secrets as we need. The optional_parameters string can
    contain additional information to further segregate your context, for
    example if there is a need for multiple secrets.

    The resulting secret(s) can be used freely, in particular they may be
    shared with the environment or servers. Before you start generating and
    using a secret in a new context, please always make sure to contact the
    privacy and security teams to check whether your intended usage meets the
    Chrome OS privacy and security guidelines.

    MOST IMPORTANTLY: THE STABLE DEVICE SECRET MUST NOT LEAVE THE DEVICE AT ANY
    TIME. DO NOT INCLUDE IT IN NETWORK COMMUNICATION, AND MAKE SURE IT DOES NOT
    SHOW UP IN DATA THAT GETS SHARED POTENTIALLY (LOGS, ETC.). FAILURE TO DO SO
    MAY BREAK THE SECURITY AND PRIVACY OF ALL OUR USERS. YOU HAVE BEEN WARNED.
    """

    # Ensure that the release image is recent enough to handle the stable
    # device secret key in VPD. Version 6887.0.0 is the first one that has the
    # session_manager change to generate server-backed state keys for forced
    # re-enrollment from the stable device secret.
    release_image_version = LooseVersion(self._util.GetReleaseImageVersion())
    if release_image_version < LooseVersion('6887.0.0'):
      raise Error("Release image version can't handle stable device secret!")

    # A context manager useful for wrapping code blocks that handle the device
    # secret in an exception handler, so the secret value does not leak due to
    # exception handling (for example, the value will be part of the VPD update
    # command, which may get included in exceptions). Chances are that
    # exceptions will prevent the secret value from getting written to VPD
    # anyways, but better safe than sorry.
    @contextmanager
    def scrub_exceptions(operation):
      try:
        yield
      except Exception:
        # Re-raise an exception including type and stack trace for the original
        # exception to facilitate error analysis. Don't include the exception
        # value as it may contain the device secret.
        (exc_type, _, exc_traceback) = sys.exc_info()
        cause = f'{operation}: {exc_type}'
        raise Error(cause).with_traceback(exc_traceback) from None

    with scrub_exceptions('Error generating device secret'):
      # Generate the stable device secret and write it to VPD. Turn off logging,
      # so the generated secret doesn't leak to the logs.
      secret = self._util.shell('libhwsec_client get_random 32',
                                log=False).stdout.strip()

    with scrub_exceptions('Error validating device secret'):
      secret_bytes = codecs.decode(secret, 'hex')
      if len(secret_bytes) != 32:
        raise Error

    with scrub_exceptions('Error writing device secret to VPD'):
      self.vpd.UpdateData(
          {
              'stable_device_secret_DO_NOT_SHARE':
                  codecs.encode(secret_bytes, 'hex').decode('utf-8')
          }, partition=vpd.VPD_READONLY_PARTITION_NAME)

  def VerifyGSCBoardID(self):
    board_id = self._gsctool.GetBoardID()
    RLZ = self._cros_config.GetBrandCode()
    if RLZ == '':
      db_identity, cur_identity = self.GetIdentity()
      raise CrosConfigError('RLZ code is empty', db_identity, cur_identity)
    if board_id.type != int(codecs.encode(RLZ.encode('ascii'), 'hex'), 16):
      raise Error('RLZ does not match Board ID.')

  def VerifyCustomLabel(self):
    model_sku_config = model_sku_utils.GetDesignConfig(self._util.sys_interface)
    custom_type = model_sku_config.get('custom_type', '')
    is_custom_label, custom_label_tag = self._cros_config.GetCustomLabelTag()

    if is_custom_label:
      # If we can't find custom_label_tag in VPD, this will be None.
      vpd_custom_label_tag = self.vpd.GetValue('custom_label_tag')
      if vpd_custom_label_tag != custom_label_tag:
        if vpd_custom_label_tag is None and custom_type != 'rebrand':
          # custom_label_tag is not set in VPD.  Technically, this is allowed by
          # cros_config. It would be equivalent to custom_label_tag='' (empty
          # string).  However, it is ambiguous, we don't know if this is
          # intended or not.  Therefore, we enforce the custom_label_tag should
          # be set explicitly, even if it is an empty string.
          raise Error('This is a custom label device, but custom_label_tag is '
                      'not set in VPD.')
        # custom_label_tag is set in VPD, but it is different from what is
        # reported by cros_config.  We don't allow this, because
        # custom_label_tag affects RLZ code, and RLZ code will be written to
        # GSC board ID.
        raise Error('custom_label_tag reported by cros_config and VPD does not '
                    'match.  Have you reboot the device after updating VPD '
                    'fields?')


  def GSCSMTWriteFlashInfo(self):
    """Write device info into GSC flash in SMT, usually used in two stages
    projects.
    """

    self.VerifyCustomLabel()

    # The MLB is still not finalized, and some dependencies of
    # SN bits or AP RO Hash might be uncertain at this time.
    # So we only set Board ID flags for security issue.
    self.gsc_utils.GSCSetBoardId(two_stages=True, is_flags_only=True)

  def GSCWriteFlashInfo(
      self, enable_zero_touch=False, factory_process=FactoryProcessEnum.FULL,
      no_write_protect=True, skip_feature_tiering_steps=False):
    """Write full device info into GSC flash.

    Args:
      enable_zero_touch: Will set SN-bits in GSC if not in RMA center.
      factory_process: The process that a device/MLB is produced or assembled.
      skip_feature_tiering_steps: Skip provisioning feature flags if True.
    """

    rma_mode = factory_process == FactoryProcessEnum.RMA
    self.VerifyCustomLabel()

    set_sn_bits = enable_zero_touch and not rma_mode
    if set_sn_bits:
      self.gsc_utils.GSCSetSnBits()

    if self.gsc_utils.IsTi50():
      self.gsc_utils.Ti50ProvisionSPIData(no_write_protect)
    else:
      self.gsc_utils.Cr50SetROHashForShipping()

    skip_feature_tiering_steps |= (
        rma_mode and self.gsc_utils.IsGSCFeatureManagementFlagsLocked())

    # Setting the feature management flags to GSC is a write-once operation,
    # so we should set these flags right before GSCSetBoardId.
    if not skip_feature_tiering_steps:
      self.gsc_utils.GSCSetFeatureManagementFlags()

    if not rma_mode:
      self.gsc_utils.GSCSetBoardId(
          two_stages=factory_process == FactoryProcessEnum.TWOSTAGES)
      return

    # In RMA center, we don't know the process that the device was produced.
    try:
      self.gsc_utils.GSCSetBoardId(two_stages=True)
    except Exception:
      self.gsc_utils.GSCSetBoardId(two_stages=False)

  def GSCDisableFactoryMode(self):
    """Disable GSC Factory mode.

    GSC factory mode might be enabled in the factory and RMA center in order to
    open ccd capabilities. Before finalizing the DUT, factory mode MUST be
    disabled.
    """

    if not self._gsctool.IsGSCBoardIdTypeSet():
      raise Error('GSC board ID not set.')
    self.VerifyGSCBoardID()
    self.gsc_utils.GSCDisableFactoryMode()

  def FpmcuInitializeEntropy(self):
    """Initialze entropy of FPMCU.

    Verify entropy of FPMCU is not added yet and initialize the entropy in
    FPMCU.
    """

    RBINFO_PATTERN = r'^Rollback block id:\s*(\d)+$'
    RBINFO_REGEX = re.compile(RBINFO_PATTERN, re.MULTILINE)
    RBINFO_CMD = ['ectool', '--name=cros_fp', 'rollbackinfo']
    def get_rbinfo():
      proc = self._util.shell(RBINFO_CMD)
      if not proc.success:
        raise Error(f'Fail to call {RBINFO_CMD!r}. Log:\n{proc.stderr}')
      result = RBINFO_REGEX.search(proc.stdout)
      if result is None:
        raise Error(
            f'FPS rollback info not found.\n{RBINFO_PATTERN!r} not found in:'
            f'\n{proc.stdout}')
      return int(result.group(1))

    if get_rbinfo() != 0:
      raise Error(
          'FPMCU entropy should not be initialized already. To resolve this,'
          ' you have to first disable HW write protection, then run'
          ' update_fpmcu_firmware.py to flash the firmware again to clear'
          ' the entropy before finalization.')
    BIOWASH_CMD = ['bio_wash', '--factory_init']
    biowash = self._util.shell(BIOWASH_CMD)

    if not biowash.success:
      raise Error(f'Fail to call {BIOWASH_CMD!r}. Log:\n{biowash.stderr}')
    if get_rbinfo() != 1:
      raise Error(f'FPMCU entropy cannot be initialized properly.\nLog of '
                  f'{BIOWASH_CMD!r}:\n{biowash.stderr}')
    logging.info('FPMCU entropy initialized successfully.')

  def GetIdentity(self):
    """Return identities in cros_config database and current identities.

    cros_config is a database and uses `identity` as key to query the
    configuration. However, if `identity` is misconfigured, cros_config will
    return either false or empty configuration. We print identities in
    cros_config database and current identities to help identify the wrong
    settings.

    Returns:
      CrosConfigIdentity objects which contain identity information read from
      cros_config database and from firmware, which is the current setting.
    """

    def get_cros_config_val(val):
      return val if val else 'empty'

    def get_file_if_exist(path_to_file, read_byte=False):
      if os.path.exists(path_to_file):
        if read_byte:
          big_endian_data = file_utils.ReadFile(path_to_file, None)
          ret = str(int.from_bytes(big_endian_data, byteorder='big'))
        else:
          ret = file_utils.ReadFile(path_to_file).strip()
        return ret
      return ''

    def get_vpd_val(tag_name):
      return self.vpd.GetValue(tag_name, 'empty')

    db_identity = CrosConfigIdentity(IdentitySourceEnum.cros_config)
    product_name, product_name_match = self._cros_config.GetProductName()
    if product_name_match:
      db_identity[product_name_match] = get_cros_config_val(product_name)
    db_identity['frid'] = get_cros_config_val(self._cros_config.GetFrid())
    db_identity['sku-id'] = get_cros_config_val(self._cros_config.GetSkuID())
    db_identity['customization-id'] = get_cros_config_val(
        self._cros_config.GetCustomizationId())
    db_identity['custom-label-tag'] = get_cros_config_val(
        self._cros_config.GetCustomLabelTag()[1])

    cur_identity = CrosConfigIdentity(IdentitySourceEnum.current_identity)
    # one for x86 device another for ARM device
    cur_identity['smbios-name-match'] = get_file_if_exist(
        cros_config.PRODUCT_NAME_PATH)
    cur_identity['device-tree-compatible-match'] = get_file_if_exist(
        cros_config.DEVICE_TREE_COMPATIBLE_PATH)
    firmware_ro_info = get_file_if_exist(
        cros_config.SYSFS_CHROMEOS_ACPI_FRID_LEGACY_FW_PATH
    ) or get_file_if_exist(
        cros_config.SYSFS_CHROMEOS_ACPI_FRID_PATH) or get_file_if_exist(
            cros_config.PROC_FDT_CHROMEOS_FRID_PATH) or 'empty'
    cur_identity['frid'] = firmware_ro_info.split('.')[0]
    # For some devices (e.g. hayato), there's only one SKU.
    # In this case, sku-id might not be set.
    cur_identity['sku-id'] = get_file_if_exist(
        cros_config.PRODUCT_SKU_ID_PATH) or get_file_if_exist(
            cros_config.DEVICE_TREE_SKU_ID_PATH, True) or 'empty'
    for vpd_key, cros_id_key in vpd_utils.IDENTITY_VPD_FIELDS.items():
      cur_identity[cros_id_key] = get_vpd_val(vpd_key)

    return db_identity, cur_identity
