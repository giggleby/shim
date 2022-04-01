# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import os
import subprocess
import tempfile

from cros.factory.gooftool import cros_config as cros_config_module
from cros.factory.probe.lib import cached_probe_function
from cros.factory.test.utils import fpmcu_utils
from cros.factory.utils import file_utils
from cros.factory.utils import fmap
from cros.factory.utils import process_utils
from cros.factory.utils import sys_interface
from cros.factory.utils import sys_utils

_FIRMWARE_DIR = 'opt/google/biod/fw'
_EC_RO = 'EC_RO'


class ReferenceFirmwareError(Exception):
  pass


class FingerprintFunction(cached_probe_function.CachedProbeFunction):
  """Probe the fingerprint information."""

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    if not os.path.exists('/dev/cros_fp'):
      return None

    _fpmcu = fpmcu_utils.FpmcuDevice(sys_interface.SystemInterface())

    sensor_vendor, sensor_model = _fpmcu.GetFpSensorInfo()
    fpmcu_name = _fpmcu.GetFpmcuName()
    ro_fw_version, unused_rw_fw_version = _fpmcu.GetFpmcuFirmwareVersion()

    with sys_utils.MountPartition(GetReleaseRootFS()) as root:
      cros_config = cros_config_module.CrosConfig()
      board_name = cros_config.GetFingerPrintBoard()
      firmware_search_dir = os.path.join(root, _FIRMWARE_DIR)
      reference_firmware = GetReferenceFirmware(firmware_search_dir, board_name)
      firmware_blob = file_utils.ReadFile(reference_firmware, encoding=None)
      firmware_image = fmap.FirmwareImage(firmware_blob)
    ro_offset, ro_size = firmware_image.get_section_area(_EC_RO)
    ro_hash = GetDumpedROHash(ro_offset, ro_size)

    results = [{
        'sensor_vendor': sensor_vendor,
        'sensor_model': sensor_model,
        'fpmcu_name': fpmcu_name,
        'ro_fw_version': ro_fw_version,
        'hash': ro_hash,
    }]
    return results


def GetReleaseRootFS():
  """Gets the partition of release rootfs.

  Logic is the same as cros.factory.device.partitions.
  """
  rootdev = process_utils.CheckOutput(['rootdev', '-s', '-d']).strip()
  if rootdev[-1].isdigit():
    return rootdev + 'p5'
  return rootdev + '5'


def GetReferenceFirmware(firmware_dir, fingerprint_board_name):
  """Gets full path of the reference firmware.

  Searches the firmware under _FIRMWARE_DIR. The firmware is in the form of
  <fingerprint_board_name>_<RO version>-RO_<RW version>-RW.bin. The <RO version>
  and <RW version> need not to be strictly matched. An exception is raised if
  there are multiple files or no file matched.
  """
  firmware_files = glob.glob(
      f'{firmware_dir}/{fingerprint_board_name}_*-RO_*-RW.bin')
  if len(firmware_files) != 1:
    raise ReferenceFirmwareError(
        f'No firmware found under {firmware_dir}' if not firmware_files else
        f'Multiple firmwares found under {firmware_dir}')
  return firmware_files[0]


def GetDumpedROHash(ro_offset, ro_size):
  """Gets RO sha256 hash from the partial dumped fingerprint firmware."""
  with tempfile.TemporaryDirectory() as tmp:
    dump_path = f'{tmp}/fp_ro_dump.bin'
    process_utils.CheckCall([
        'ectool', '--name=cros_fp', 'flashread',
        str(ro_offset),
        str(ro_size), dump_path
    ], stdout=subprocess.DEVNULL)
    return file_utils.FileHash(dump_path, 'sha256').hexdigest()
