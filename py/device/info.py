#!/usr/bin/env python3
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to retrieve non-volatile system information."""

import copy
import logging
import os
import re

from cros.factory.device import device_types
from cros.factory.device import storage
from cros.factory.gooftool import write_protect_target
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test import device_data
from cros.factory.test.env import paths
from cros.factory.test.rules import phase
from cros.factory.test import session
from cros.factory.test.utils import cbi_utils
from cros.factory.utils import file_utils
from cros.factory.utils import gsc_utils
from cros.factory.utils import net_utils
from cros.factory.utils.sys_utils import MountDeviceAndReadFile

from cros.factory.external.chromeos_cli import gsctool as gsctool_module
from cros.factory.external.chromeos_cli import vpd


# Static list of known properties in SystemInfo.
_INFO_PROP_LIST = []


def InfoProperty(f):
  """Decoration function for SystemInfo properties."""
  name = f.__name__
  if not name.startswith('_'):
    _INFO_PROP_LIST.append(name)
  @property
  def prop(self):
    # pylint: disable=protected-access
    if name in self._overrides:
      return self._overrides[name]
    if name in self._cached:
      return self._cached[name]
    value = None
    try:
      value = f(self)
    except Exception:
      pass
    self._cached[name] = value
    return value
  return prop


class SystemInfo(device_types.DeviceComponent):
  """Static information about the system.

  This is mostly static information that changes rarely if ever
  (e.g., version numbers, serial numbers, etc.).

  You can access the information by reading individual properties. However all
  values are cached by default unless you call Invalidate(name). Calling
  Invalidate() without giving particular name will invalidate all properties.

  To get a dictionary object of all properties, use GetAll().
  To refresh, do Invalidate() then GetAll().
  You can also "override" some properties by using Overrides(name, value).
  """

  _FIRMWARE_NV_INDEX = 0x1007
  _FLAG_VIRTUAL_DEV_MODE_ON = 0x02

  # KEY=VALUE
  _REGEX_KEY_EQUAL_VALUE = r'^(?P<key>.+)=(?P<value>.+)$'
  # KEY: VALUE
  _REGEX_LSCPU = r'(?P<key>.+):\s+(?P<value>.+)$'
  # KEY = VALUE # COMMENT
  _REGEX_CROSSYSTEM = r'^(?P<key>.+?)\s+=\s+(?P<value>.+?)\s*#'

  def __init__(self, device=None):
    super().__init__(device)
    self._cached = {}
    self._overrides = {}

  def _IntToHexStr(self, num):
    return hex(num) if isinstance(num, int) else None

  def _ParseStrToDict(self, regex, string):
    return {
        m.group('key'): m.group('value')
        for m in re.finditer(regex, string, re.MULTILINE)
    }

  def GetAll(self):
    """Returns all properties in a dictionary object."""
    return copy.deepcopy(
        {name: getattr(self, name) for name in _INFO_PROP_LIST})

  def Invalidate(self, name=None):
    """Invalidates a property in system information object in cache.

    When name is omitted, invalidate all properties.

    Args:
      name: A string for the property to be refreshed.
    """
    if name is not None:
      self._cached.pop(name, None)
    else:
      self._cached.clear()

  def Overrides(self, name, value):
    """Overrides an information property to given value.

    This is useful for setting shared information like update_toolkit_version.

    Args:
      name: A string for the property to override.
      value: The value to return in future for given property.
    """
    self._overrides[name] = value

  @InfoProperty
  def cpu_count(self):
    """Gets number of CPUs on the machine"""
    return int(self._cpu_info['CPU(s)'])

  @InfoProperty
  def cpu_model(self):
    """Gets the name of the CPU model on the machine"""
    return self._cpu_info['Model name']

  @InfoProperty
  def _cpu_info(self):
    output = self._device.CheckOutput('lscpu')
    return self._ParseStrToDict(self._REGEX_LSCPU, output)

  @InfoProperty
  def memory_total_kb(self):
    return self._device.memory.GetTotalMemoryKB()

  @InfoProperty
  def storage_type(self):
    return storage.Storage(self._device).GetMainStorageType().value

  @InfoProperty
  def release_image_version(self):
    """Version of the image on release partition."""
    return self._release_lsb_data['GOOGLE_RELEASE']

  @InfoProperty
  def release_image_channel(self):
    """Channel of the image on release partition."""
    return self._release_lsb_data['CHROMEOS_RELEASE_TRACK']

  def ClearSerialNumbers(self):
    """Clears any serial numbers from DeviceData."""
    return device_data.ClearAllSerialNumbers()

  def GetAllSerialNumbers(self):
    """Returns all available serial numbers in a dict."""
    return device_data.GetAllSerialNumbers()

  def GetSerialNumber(self, name=device_data.NAME_SERIAL_NUMBER):
    """Retrieves a serial number from device.

    Tries to load the serial number from DeviceData.  If not found, loads
    from DUT storage, and caches into DeviceData.
    """
    if not device_data.GetSerialNumber(name):
      serial = self._device.storage.LoadDict().get(name)
      if serial:
        device_data.UpdateSerialNumbers({name: serial})
    return device_data.GetSerialNumber(name)

  @InfoProperty
  def serial_number(self):
    """Device serial number (usually printed on device package)."""
    return self.GetSerialNumber()

  @InfoProperty
  def mlb_serial_number(self):
    """Motherboard serial number."""
    return self.GetSerialNumber(device_data.NAME_MLB_SERIAL_NUMBER)

  @InfoProperty
  def stage(self):
    """Manufacturing build stage. Examples: PVT, EVT, DVT."""
    # TODO(hungte) Umpire thinks this should be SMT, FATP, etc. Goofy monitor
    # simply displays this. We should figure out different terms for both and
    # find out the right way to print this value.
    return str(phase.GetPhase())

  @InfoProperty
  def test_image_version(self):
    """Version of the image on factory test partition."""
    return self._test_lsb_data['GOOGLE_RELEASE']

  @InfoProperty
  def test_image_channel(self):
    """Channel of the image on factory test partition."""
    return self._test_lsb_data['CHROMEOS_RELEASE_TRACK']

  @InfoProperty
  def test_image_builder_path(self):
    """Builder path of the image on factory test partition."""
    return self._test_lsb_data['CHROMEOS_RELEASE_BUILDER_PATH']

  @InfoProperty
  def factory_image_version(self):
    """Version of the image on factory test partition.

    This is same as test_image_version.
    """
    return self.test_image_version

  @InfoProperty
  def wlan0_mac(self):
    """MAC address of first wireless network device."""
    for wlan_interface in ['wlan0', 'mlan0']:
      address_path = self._device.path.join(
          '/sys/class/net/', wlan_interface, 'address')
      if self._device.path.exists(address_path):
        return self._device.ReadFile(address_path).strip()
    return None

  @InfoProperty
  def eth_macs(self):
    """MAC addresses of ethernet devices."""
    macs = {}
    eth_paths = sum([self._device.Glob(os.path.join('/sys/class/net', pattern))
                     for pattern in net_utils.DEFAULT_ETHERNET_NAME_PATTERNS],
                    [])
    for eth_path in eth_paths:
      address_path = self._device.path.join(eth_path, 'address')
      if self._device.path.exists(address_path):
        interface = self._device.path.basename(eth_path)
        macs[interface] = self._device.ReadSpecialFile(address_path).strip()
    return macs

  @InfoProperty
  def toolkit_version(self):
    """Version of ChromeOS factory toolkit."""
    return self._device.ReadFile(paths.FACTORY_TOOLKIT_VERSION_PATH).rstrip()

  @InfoProperty
  def kernel_version(self):
    """Version of running kernel."""
    return self._device.CheckOutput(['uname', '-r']).strip()

  @InfoProperty
  def architecture(self):
    """System architecture."""
    return self._device.CheckOutput(['uname', '-m']).strip()

  @InfoProperty
  def root_device(self):
    """The root partition that boots current system."""
    return self._device.CheckOutput(['rootdev', '-s']).strip()

  @InfoProperty
  def firmware_version(self):
    """Version of main firmware."""
    return self._crossystem['fwid']

  @InfoProperty
  def ro_firmware_version(self):
    """Version of RO main firmware."""
    return self._crossystem['ro_fwid']

  @InfoProperty
  def mainfw_type(self):
    """Type of main firmware."""
    return self._crossystem['mainfw_type']

  @InfoProperty
  def mainfw_act(self):
    return self._crossystem['mainfw_act']

  @InfoProperty
  def ecfw_act(self):
    return self._crossystem['ecfw_act']

  @InfoProperty
  def hwwp(self):
    return self._crossystem['wpsw_cur']

  @InfoProperty
  def hwid(self):
    return self._crossystem['hwid']

  @InfoProperty
  def _crossystem(self):
    output = self._device.CheckOutput(['crossystem']).strip()
    return self._ParseStrToDict(self._REGEX_CROSSYSTEM, output)

  @InfoProperty
  def ec_active_version(self):
    """Version of active embedded controller."""
    return self._device.ec.GetActiveVersion().strip()

  @InfoProperty
  def pd_version(self):
    return self._device.usb_c.GetPDVersion().strip()

  @InfoProperty
  def update_toolkit_version(self):
    """Indicates if an update is available on server.

    Usually set by using Overrides after checking shopfloor server.
    """
    # TODO(youcheng) Implement this in another way. Probably move this to goofy
    # state variables.
    return None

  @InfoProperty
  def _release_lsb_data(self):
    """Returns the lsb-release data in dict from release image partition."""
    release_rootfs = self._device.partitions.RELEASE_ROOTFS.path
    lsb_content = MountDeviceAndReadFile(
        release_rootfs, '/etc/lsb-release', dut=self._device)
    return self._ParseStrToDict(self._REGEX_KEY_EQUAL_VALUE, lsb_content)

  @InfoProperty
  def _test_lsb_data(self):
    """Returns the lsb-release data in dict from test image partition."""
    lsb_content = file_utils.ReadFile('/etc/lsb-release')
    return self._ParseStrToDict(self._REGEX_KEY_EQUAL_VALUE, lsb_content)

  @InfoProperty
  def hwid_database_version(self):
    """Uses checksum of hwid file as hwid database version."""
    hwid_file_path = self._device.path.join(
        hwid_utils.GetDefaultDataPath(), hwid_utils.ProbeProject().upper())
    # TODO(hungte) Support remote DUT.
    return hwid_utils.ComputeDatabaseChecksum(hwid_file_path)

  @InfoProperty
  def pci_device_number(self):
    """Returns number of PCI devices."""
    res = self._device.CheckOutput(['busybox', 'lspci'])
    return len(res.splitlines())

  @InfoProperty
  def device_id(self):
    """Returns the device ID of the device."""
    return self._device.ReadFile(session.DEVICE_ID_PATH).strip()

  @InfoProperty
  def device_name(self):
    """Returns the device name of the device."""
    return self._device.CheckOutput(['cros_config', '/', 'name']).strip()

  @InfoProperty
  def system_timezone(self):
    """Returns the system timezone of the device."""
    timezone = self._device.CheckOutput(['date', '+%Z']).strip()
    offset = self._device.CheckOutput(['date', '+%:z']).strip()
    return {
        'timezone': timezone,
        'offset': offset,
    }

  @InfoProperty
  def image_info(self):
    return {
        'test_image': {
            'version': self.test_image_version,
            'channel': self.test_image_channel,
        },
        'release_image': {
            'version': self.release_image_version,
            'channel': self.release_image_channel,
        },
    }

  @InfoProperty
  def factory_info(self):
    return {
        'stage': self.stage,
        'toolkit_version': self.toolkit_version,
        'hwid_database_version': self.hwid_database_version,
    }

  @InfoProperty
  def system_info(self):
    return {
        'architecture': self.architecture,
        'kernel_version': self.kernel_version,
        'root_device': self.root_device,
    }

  @InfoProperty
  def ec(self):
    return {
        'active': self.ecfw_act,
        'version': self.ec_version,
    }

  @InfoProperty
  def ap(self):
    return {
        'active': self.mainfw_act,
        'ro_version': self.firmware_version,
        'rw_version': self.ro_firmware_version,
        'type': self.mainfw_type,
    }

  @InfoProperty
  def pd(self):
    return {
        'version': self.pd_version,
    }

  # TODO (phoebewang): collect more fw version from /var/log/message
  @InfoProperty
  def fw_info(self):
    return {
        'ap': self.ap,
        'ec': self.ec,
        'hwid': self.hwid,
        'pd': self.pd,
    }

  @InfoProperty
  def hw_info(self):
    return {
        'cpu_info': {
            'model_name': self.cpu_model,
            'count': self.cpu_count,
        },
        'storage': self.storage_type,
        'total_memory_kb': self.memory_total_kb,
        'wlan0_mac': self.wlan0_mac,
        'eth_mac': self.eth_macs,
    }

  @InfoProperty
  def device_info(self):
    return {
        'name': self.device_name,
        'id': self.device_id,
        'serial_number': self.serial_number,
        'mlb_serial_number': self.mlb_serial_number,
        'pci_device_number': self.pci_device_number,
        'system_timezone': self.system_timezone,
    }

  @InfoProperty
  def gsc_sn_bits(self):
    return self._device.CheckOutput(
        ['/usr/share/cros/cr50-read-rma-sn-bits.sh']).strip()

  @InfoProperty
  def gsc_factory_config(self):
    factory_config = gsctool_module.GSCTool(
        self._device).GetFeatureManagementFlags()
    return factory_config.__dict__

  @InfoProperty
  def gsc_version(self):
    fw_version = gsctool_module.GSCTool(self._device).GetGSCFirmwareVersion()
    return {
        'ro_version': fw_version.ro_version,
        'rw_version': fw_version.rw_version,
    }

  @InfoProperty
  def ap_ro_verify(self):
    gsctool = gsctool_module.GSCTool(self._device)
    wpsr_list = gsctool.GetWpsr()
    wpsr_hex_str_list = []
    for wpsr_tuple in wpsr_list:
      wpsr_hex_str_list.append({
          'value': self._IntToHexStr(wpsr_tuple.value),
          'mask': self._IntToHexStr(wpsr_tuple.mask)
      })

    return {
        'addressing_mode': gsctool.GetAddressingMode(),
        'wpsr': wpsr_hex_str_list,
        'result': str(gsctool.GSCGetAPROResult()),
    }

  @InfoProperty
  def board_id(self):
    # Though the board id info from gsctool.GetBoardID() should be sufficient,
    # we still store all the fields from command `gsctool -a -M -i` to improve
    # the readability.
    content = self._device.CheckOutput(
        [gsctool_module.GSCTOOL_PATH, '-a', '-M', '-i']).strip()
    return self._ParseStrToDict(self._REGEX_KEY_EQUAL_VALUE, content)

  @InfoProperty
  def gsc_info(self):
    """Returns the Google Security Chip (GSC) info of the device."""

    return {
        'gsc_type': gsc_utils.GSCUtils().name,
        'board_id': self.board_id,
        'fw_version': self.gsc_version,
        'sn_bits': self.gsc_sn_bits,
        'factory_config': self.gsc_factory_config,
        'ap_ro_verify': self.ap_ro_verify,
    }

  @InfoProperty
  def cbi_info(self):
    """Returns the cbi info of the device."""
    cbi_info = {}
    cbi_info['board_version'] = cbi_utils.GetCbiData(
        self._device, cbi_utils.CbiDataName.BOARD_VERSION)
    cbi_info['sku_id'] = self._IntToHexStr(
        cbi_utils.GetCbiData(self._device, cbi_utils.CbiDataName.SKU_ID))
    cbi_info['fw_config'] = self._IntToHexStr(
        cbi_utils.GetCbiData(self._device, cbi_utils.CbiDataName.FW_CONFIG))
    return cbi_info

  @InfoProperty
  def vpd_info(self):
    """Returns the VPD info of the device."""
    vpd_tool = vpd.VPDTool(self._device)
    return {
        'ro': vpd_tool.GetAllData(partition=vpd.VPD_READONLY_PARTITION_NAME),
        'rw': vpd_tool.GetAllData(partition=vpd.VPD_READWRITE_PARTITION_NAME),
    }

  @InfoProperty
  def crosid(self):
    """Returns the crosid of the device.

    The output of `crosid` command looks like:
      SKU='xxx'
      CONFIG_INDEX='xxx'
      FIRMWARE_MANIFEST_KEY='xxx'
    """
    output = self._device.CheckOutput(['crosid']).strip()
    crosid = self._ParseStrToDict(self._REGEX_KEY_EQUAL_VALUE, output)
    # Removes the quotes around string.
    for k, v in crosid.items():
      crosid[k] = v.replace('\'', '')
    return {
        'sku': self._IntToHexStr(int(crosid['SKU'])),
        'config_index': int(crosid['CONFIG_INDEX']),
        'firmware_manifest_key': crosid['FIRMWARE_MANIFEST_KEY'],
    }

  @InfoProperty
  def wp_info(self):
    software_wp = {}
    for target in set(write_protect_target.WriteProtectTargetType):
      wp_target = write_protect_target.CreateWriteProtectTarget(target)
      try:
        software_wp[target.name] = wp_target.GetStatus()
      except write_protect_target.UnsupportedOperationError:
        pass

    return {
        'hardware_wp': {
            "enabled": {
                '0': False,
                '1': True
            }[self.hwwp]
        },
        'software_wp': software_wp,
    }

def main():
  import pprint

  from cros.factory.device import device_utils
  logging.basicConfig()
  info = SystemInfo(device_utils.CreateDUTInterface())
  pprint.pprint(info.GetAll())


if __name__ == '__main__':
  main()
