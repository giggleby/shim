# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import logging
import os
import re
import sys

from cros.factory.probe import function
from cros.factory.probe.lib import cached_probe_function
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils
from cros.factory.utils.type_utils import Obj


try:
  sys.path.append('/usr/local/lib/flimflam/test')
  import flimflam
except ImportError:
  pass


class KnownDeviceTypes(str, enum.Enum):
  wireless = 'wireless'
  ethernet = 'ethernet'
  cellular = 'cellular'

  def __str__(self):
    return self.name


class NetworkDevices:
  """A general probing module for network devices."""

  cached_dev_list = None
  find_cellular = False

  @classmethod
  def _GetIwconfigDevices(cls, extension='IEEE 802.11'):
    """Wrapper around iwconfig(8) information.

    Example output:

    eth0    no wireless extensions.

    wlan0   IEEE 802.11abgn ESSID:off/any
            Mod:Managed Access Point: Not-Associated Tx-Power=20 dBm
            ...

    Returns a list of network objects having WiFi extension.
    """
    return [
        Obj(devtype='wifi', path=f'/sys/class/net/{node.split()[0]}/device')
        for node in process_utils.CheckOutput(['iwconfig']).splitlines()
        if extension in node
    ]

  @classmethod
  def _GetIwDevices(cls, iw_type='managed'):
    """Wrapper around iw(8) information.

    Command 'iw' explicitly said "Do NOT screenscrape this tool" but we have no
    any better solutions. A typical output for 'iw dev' on mwifiex:

    phy#0
          Interface p2p0
                  ifindex 4
                  wdev 0x3
                  addr 28:c2:dd:45:94:39
                  type P2P-client
          Interface uap0
                  ifindex 3
                  wdev 0x2
                  addr 28:c2:dd:45:94:39
                  type AP
          Interface mlan0
                  ifindex 2
                  wdev 0x1
                  addr 28:c2:dd:45:94:39
                  type managed

    p2p0 and uap0 are virtual nodes and what we really want is mlan0 (managed).

    Returns:
      A list of network objects with correct iw type.
    """
    data = [line.split()[1]
            for line in process_utils.CheckOutput(
                'iw dev', shell=True, log=True).splitlines()
            if ' ' in line and line.split()[0] in ['Interface', 'type']]
    i = iter(data)
    return [
        Obj(devtype='wifi', path=f'/sys/class/net/{name}/device')
        for name in i
        if next(i) == iw_type
    ]

  @classmethod
  def _GetFlimflamDevices(cls, probe_cellular=False):
    """Wrapper around flimflam (shill), the ChromeOS connection manager.

    This object is a wrapper around the data from the flimflam module, providing
    dbus format post processing.

    Args:
      probe_cellular: Whether to wait for cellular initialization or not.

    Returns:
      A list of network objects in Obj, having:
        devtype: A string in flimflam Type (wifi, cellular, ethernet).
        path: A string for /sys node device path.
        attributes: A dictionary for additional attributes.
    """
    def _ProcessDevice(device):
      properties = device.GetProperties()
      get_prop = lambda p: flimflam.convert_dbus_value(properties[p])
      result = Obj(
          devtype=get_prop('Type'),
          path=f"/sys/class/net/{get_prop('Interface')}/device")
      if result.devtype == 'cellular':
        result.attributes = dict((key, get_prop(f'Cellular.{key}')) for key in [
            'Carrier', 'FirmwareRevision', 'HardwareRevision', 'ModelID',
            'Manufacturer'
        ] if f'Cellular.{key}' in properties)
      return result

    def _ParseDbusArray(dbus_array):
      if not dbus_array:
        return []
      # convert_dbus_value transform the dbus array into a string.
      # E.g. dbus.Array([dbus.String('cellular'), dbus.String('wifi')])
      # will transform into '[\n    cellular\n    wifi\n]'
      dbus_value = flimflam.convert_dbus_value(dbus_array)
      return [element.strip() for element in dbus_value.split('\n')[1:-1]]

    def _HasCellular():
      """Detect whether a DUT has cellular or not via flimflam API.

      If a DUT has cellular, then we can see `cellular` in
      `AvailableTechnologies` or `UninitializedTechnologies` from flimflam
      GetManager().GetProperties() API.
      """
      # GetProperties() returns dbus dictionary type, which looks like this:
      # dbus.Dictionary(...
      #   dbus.String('AvailableTechnologies'):
      #     dbus.Array([
      #       dbus.String('cellular'),
      #       dbus.String('ethernet'),
      #       dbus.String('wifi')],
      #     signature=dbus.Signature('s'), variant_level=1)...)
      properties = flimflam.FlimFlam().GetManager().GetProperties()
      # `AvailableTechnologies` or `UninitializedTechnologies` return dbus
      # array type.
      available_tech = properties.get('AvailableTechnologies', None)
      uninitialize_tech = properties.get('UninitializedTechnologies', None)
      if ('cellular' in _ParseDbusArray(available_tech) or
          'cellular' in _ParseDbusArray(uninitialize_tech)):
        logging.info('DUT has cellular. Might take some time to probe it...')
        return True
      logging.info('DUT does not have cellular.')
      return False

    if probe_cellular and _HasCellular():
      # Cellular related dbus takes 10~20 seconds to initialize after booting.
      # We have to wait until it is available.
      if not flimflam.FlimFlam().FindCellularDevice():
        raise RuntimeError('Call of flimflam.FlimFlam().FindCellularDevice() '
                           'timeout!')
      cls.find_cellular = True

    return [_ProcessDevice(device) for device in
            flimflam.FlimFlam().GetObjectList('Device')]

  @classmethod
  def GetDevices(cls, devtype=None):
    """Returns network device information by given type.

    Returned data is a list of Objs corresponding to detected devices.
    Each has devtype (in same way as flimflam type classification) and path
    (location of related data in sysfs) fields.  For cellular devices, there is
    also an attributes field which contains a dict of attribute:value items.
    """
    probe_cellular = (devtype == 'cellular')
    if (cls.cached_dev_list is None or
        (probe_cellular and not cls.find_cellular)):
      try:
        dev_list = cls._GetFlimflamDevices(probe_cellular)
      except Exception:
        # for Brillo devices, shill might not be running in factory
        logging.debug('Cannot get wireless devices from shill', exc_info=1)
        dev_list = []

      # On some Brillo (AP-type) devices, WiFi interfaces are blocklisted by
      # shill and needs to be discovered manually, so we have to try 'iw config'
      # or 'iw dev' to get a more correct list.
      # 'iwconfig' is easier to parse, but for some WiFi drivers, for example
      # mwifiex, do not support wireless extensions and only provide the new
      # CFG80211/NL80211. Also mwifiex will create two more virtual nodes 'uap0,
      # p2p0' so we can't rely on globbing /sys/class/net/*/wireless. The only
      # solution is to trust 'iw dev'.

      existing_nodes = [dev.path for dev in dev_list]
      dev_list += [dev for dev in cls._GetIwconfigDevices()
                   if dev.path not in existing_nodes]

      existing_nodes = [dev.path for dev in dev_list]
      dev_list += [dev for dev in cls._GetIwDevices()
                   if dev.path not in existing_nodes]

      cls.cached_dev_list = dev_list

    # pylint: disable=not-an-iterable
    # This is a false alarm, the "if" statement above would make
    # cls.cached_dev_list a list object.
    return [dev for dev in cls.cached_dev_list
            if devtype is None or dev.devtype == devtype]

  @classmethod
  def GetPCIPath(cls, devtype, path):
    """Returns the PCI path of a device.

    `realpath /sys/class/net/wwan0/device` may be
    `/sys/devices/pci0123:45/6789:ab:cd.e/wwan/wwan0`. We need to map this to
    `/sys/devices/pci0123:45/6789:ab:cd.e` before passing it into PCIFunction.

    Args:
      devtype: The type of the device.
      path: The real path of the device.
    """
    if devtype == 'cellular':
      basename = os.path.basename(path)
      match = re.search(r'^wwan\d+$', basename)
      if match:
        dirname = os.path.dirname(path)
        if os.path.basename(dirname) == 'wwan':
          return os.path.dirname(dirname)
    return path

  @classmethod
  def ReadSysfsDeviceIds(cls, devtype, ignore_others=False):
    """Return _ReadSysfsDeviceId result for each device of specified type."""
    visited_paths = set()

    def ProbeSysfsDevices(path, ignore_others):
      path = os.path.abspath(os.path.realpath(path))
      pci_path = cls.GetPCIPath(devtype, path)
      if pci_path in visited_paths:
        return []
      visited_paths.add(pci_path)
      ret = function.InterpretFunction({'pci': pci_path})()
      if ret:
        return ret
      if not ignore_others:
        ret = function.InterpretFunction({'usb': os.path.join(path, '..')})()
        if ret:
          return ret
        ret = function.InterpretFunction({'sdio': path})()
      return ret

    ret = []
    for dev in cls.GetDevices(devtype):
      ret += ProbeSysfsDevices(dev.path, ignore_others)
    # Filter out 'None' results
    return sorted([device for device in ret if device is not None],
                  key=lambda d: sorted(d.items()))


class GenericNetworkDeviceFunction(
    cached_probe_function.LazyCachedProbeFunction):
  """Probes the information of network devices.

  This function gets information of all network devices,
  and then filters the results by the given arguments.
  """

  ARGS = [
      Arg('device_type', str, 'The type of network device. '
          'One of "wireless", "ethernet", "cellular".'),
  ]

  def GetCategoryFromArgs(self):
    if self.args.device_type not in KnownDeviceTypes.__members__:
      raise cached_probe_function.InvalidIdentityError(
          f'device_type should be one of {list(KnownDeviceTypes.__members__)}.')

    return self.args.device_type

  @classmethod
  def ProbeDevices(cls, category):
    function_table = {
        KnownDeviceTypes.wireless: cls.ProbeWireless,
        KnownDeviceTypes.ethernet: cls.ProbeEthernet,
        KnownDeviceTypes.cellular: cls.ProbeCellular
    }
    return function_table[category]()

  @classmethod
  def ProbeWireless(cls):
    return NetworkDevices.ReadSysfsDeviceIds('wifi')

  @classmethod
  def ProbeEthernet(cls):
    # Built-in ethernet devices should be attached to either SOC, PCI, or
    # internal USB/SDIO, not other buses such as external USB/SDIO.

    def _FilterEthernetDevice(device):
      bus = device.get('bus_type', 'unknown')
      removable = device.get('removable', 'unknown')
      return bus == 'pci' or removable == 'fixed'

    devices = list(
        filter(_FilterEthernetDevice,
               NetworkDevices.ReadSysfsDeviceIds('ethernet')))

    return devices

  @classmethod
  def ProbeCellular(cls):
    # It is found that some cellular components may have their interface listed
    # in shill but not available from /sys (for example, shill
    # Interface=no_netdev_23 but no /sys/class/net/no_netdev_23. Meanwhile,
    # 'modem status' gives right Device info like
    # 'Device: /sys/devices/ff500000.usb/usb1/1-1'. Unfortunately, information
    # collected by shill, 'modem status', or the USB node under Device are not
    # always synced.
    data = (NetworkDevices.ReadSysfsDeviceIds('cellular') or
            [dev.attributes for dev in NetworkDevices.GetDevices('cellular')])
    if data:
      modem_status = process_utils.CheckOutput(
          'modem status', shell=True, log=True)
      for key in ['carrier', 'firmware_revision', 'Revision']:
        matches = re.findall(
            r'^\s*' + key + ': (.*)$', modem_status, re.M)
        if matches:
          data[0][key] = matches[0]
    return data
