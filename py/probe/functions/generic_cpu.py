# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import glob
import logging
import re
import struct
import subprocess

from cros.factory.probe import function
from cros.factory.probe.functions import file
from cros.factory.probe.lib import probe_function
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils


CPU_INFO_FILE = '/proc/cpuinfo'
SOC_ID_FILE_GLOB = '/sys/bus/soc/devices/soc*/soc_id'
NVMEM_FILE = '/sys/bus/nvmem/devices/nvmem0/nvmem'

VENDOR0426_NVMEM_OFFSET = 0x7a0


class KnownCPUTypes(str, enum.Enum):
  x86 = 'x86'
  arm = 'arm'

  def __str__(self):
    return self.name

  @classmethod
  def has_value(cls, value):
    return value in cls.__members__


def _ProbeChipIDVendor0426():
  # TODO(b/253555789): The offset "0x7A0" which stores chip ID is only supported
  # by the platforms after MT8195. Need the vendor to provide a more generic way
  # to probe chip_id.
  chip_id_bytes = file.ReadFile(NVMEM_FILE, True, VENDOR0426_NVMEM_OFFSET, 4)
  # Unpack the bytes since all vendor0426 chipsets today use little-endian.
  (chip_id, ) = struct.unpack('<I', chip_id_bytes)
  return f'{chip_id:#08x}'


def _ProbeChipID(vendor_id):
  """Probes Chip ID for the corresponding CPU vendor ID."""
  if vendor_id == '0426':
    return _ProbeChipIDVendor0426()
  if vendor_id == '0070':
    # vendor0070 CPU can be distinguished by SoC ID so we don't need to
    # additionally probe chip ID.
    return None
  raise ValueError(f'Vendor ID {vendor_id!r} is not supported for ChromeOS '
                   'projects.')


def _GetSoCInfo():
  """Gets SoC information for ARMv8"""
  match = None
  pattern = re.compile(r'jep106:([\d]{4}):([a-z\d]{4})')
  for path in glob.glob(SOC_ID_FILE_GLOB):
    raw_soc_id = file.ReadFile(path)
    match = pattern.match(raw_soc_id)
    if match:
      break
  if not match:
    raise ValueError(f'No valid SoC ID found in {SOC_ID_FILE_GLOB!r}')

  vendor_id = match.group(1)
  soc_id = match.group(2)

  model = f'ARMv8 Vendor{vendor_id} {soc_id}'
  hardware = _ProbeChipID(vendor_id)
  return model, hardware


class GenericCPUFunction(probe_function.ProbeFunction):
  """Probe the generic CPU information."""

  ARGS = [
      Arg('cpu_type', str,
          'The type of CPU. "x86" or "arm". Default: Auto detection.',
          default=None),
  ]

  def __init__(self, **kwargs):
    super(GenericCPUFunction, self).__init__(**kwargs)

    if self.args.cpu_type is None:
      logging.info('cpu_type not specified. Determine by crossystem.')
      self.args.cpu_type = process_utils.CheckOutput(
          'crossystem arch', shell=True)
    if not KnownCPUTypes.has_value(self.args.cpu_type):
      raise ValueError('cpu_type should be one of '
                       f'{list(KnownCPUTypes.__members__)!r}.')

  def Probe(self):
    if self.args.cpu_type == KnownCPUTypes.x86:
      return self._ProbeX86()
    return self._ProbeArm()

  @staticmethod
  def _ProbeX86():
    cmd = r'/usr/bin/lscpu'
    try:
      stdout = process_utils.CheckOutput(cmd, shell=True, log=True)
    except subprocess.CalledProcessError:
      return function.NOTHING

    def _CountCores(cpu_list):
      count = 0
      for cpu in cpu_list.split(','):
        if '-' in cpu:
          # e.g. 3-5 ==> core 3, 4, 5 are enabled
          l, r = map(int, cpu.split('-'))
          count += r - l + 1
        else:
          # e.g. 12 ==> core 12 is enabled
          count += 1
      return count

    def _ReSearch(regex):
      return re.search(regex, stdout).group(1).strip()

    model = _ReSearch(r'Model name:(.*)')
    physical = int(_ReSearch(r'CPU\(s\):(.*)'))
    online = _CountCores(_ReSearch(r'On-line.*:(.*)'))
    return {
        'model': model,
        'cores': str(physical),
        'online_cores': str(online)}

  @staticmethod
  def _ProbeArm():
    # For ARM platform, ChromeOS kernel has/had special code to expose fields
    # like 'model name' or 'Processor' and 'Hardware' field.  However, this
    # doesn't seem to be available in ARMv8 (and probably all future versions).
    # In this case, we will use 'CPU architecture' to identify the ARM version.

    cpuinfo = file.ReadFile(CPU_INFO_FILE)

    def _SearchCPUInfo(regex, name):
      matched = re.search(regex, cpuinfo, re.MULTILINE)
      if matched is None:
        logging.warning('Unable to find "%s" field in %s.', name, CPU_INFO_FILE)
        return 'unknown'
      return matched.group(1)

    # For ARMv7, model and hardware should be available.
    model = _SearchCPUInfo(r'^(?:Processor|model name)\s*: (.*)$', 'model')
    hardware = _SearchCPUInfo(r'^Hardware\s*: (.*)$', 'hardware')
    architecture = _SearchCPUInfo(r'^CPU architecture\s*: (\d+)$',
                                  'architecture')

    if model.strip() == 'unknown' and architecture == '8':
      # For ARMv8, the model and hardware are not available from the cpuinfo
      # file; but the identifiers can be found from the soc_id and some
      # vendor-specific information.
      model, hardware = _GetSoCInfo()

    if model.strip() == 'unknown':
      logging.error('Unable to construct "model" of ARM CPU')

    cores = process_utils.CheckOutput('nproc', shell=True, log=True)
    # TODO(frankbozar): count the number of online cores

    values = {
        'model': model.strip(),
        'cores': cores.strip(),
    }
    if hardware:
      values['hardware'] = hardware.strip()
    return values
