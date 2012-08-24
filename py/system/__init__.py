#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import netifaces
import os
import re
import subprocess
import threading

import factory_common  # pylint: disable=W0611
from cros.factory.test import factory
from cros.factory.test import shopfloor
from cros.factory.utils.process_utils import Spawn

# pylint: disable=W0702
# Disable checking of exception types, since we catch all exceptions
# in many places.

_ec = None
_lock = threading.Lock()
def GetEC():
  '''Initializes a EC instance from environment variable CROS_FACTORY_EC_CLASS,
  or use the default EC class ChromeOSEC if the variable is empty.

  The board-specific CROS_FACTORY_EC_CLASS environment variable is set in
  board_setup_factory.sh.

  Returns:
    An instance of the specified EC class implementation.'''
  # pylint: disable=W0603
  with _lock:
    global _ec
    if _ec:
      return _ec

    ec = os.environ.get('CROS_FACTORY_EC_CLASS',
                        'cros.factory.board.chromeos_ec.ChromeOSEC')
    module, cls = ec.rsplit('.', 1)
    _ec = getattr(__import__(module, fromlist=[cls]), cls)()
    return _ec


class SystemInfo(object):
  '''Static information about the system.

  This is mostly static information that changes rarely if ever
  (e.g., version numbers, serial numbers, etc.).
  '''
  # If not None, an update that is available from the update server.
  update_md5sum = None

  def __init__(self):
    self.serial_number = None
    try:
      self.serial_number = shopfloor.get_serial_number()
    except:
      pass

    self.factory_image_version = None
    try:
      lsb_release = open('/etc/lsb-release').read()
      match = re.search('^GOOGLE_RELEASE=(.+)$', lsb_release,
                re.MULTILINE)
      if match:
        self.factory_image_version = match.group(1)
    except:
      pass

    try:
      self.wlan0_mac = open('/sys/class/net/wlan0/address').read().strip()
    except:
      self.wlan0_mac = None

    try:
      uname = subprocess.Popen(['uname', '-r'], stdout=subprocess.PIPE)
      stdout, _ = uname.communicate()
      self.kernel_version = stdout.strip()
    except:
      self.kernel_version = None

    self.ec_version = None
    try:
      self.ec_version = GetEC().GetVersion()
    except:
      pass

    self.firmware_version = None
    try:
      crossystem = subprocess.Popen(['crossystem', 'fwid'],
                      stdout=subprocess.PIPE)
      stdout, _ = crossystem.communicate()
      self.firmware_version = stdout.strip() or None
    except:
      pass

    self.root_device = None
    try:
      rootdev = Spawn(['rootdev', '-s'],
                      stdout=subprocess.PIPE)
      stdout, _ = rootdev.communicate()
      self.root_device = stdout.strip()
    except:
      pass

    self.factory_md5sum = factory.get_current_md5sum()

    # update_md5sum is currently in SystemInfo's __dict__ but not this
    # object's.  Copy it from SystemInfo into this object's __dict__.
    self.update_md5sum = SystemInfo.update_md5sum


def GetIPv4Addresses():
  '''Returns a string describing interfaces' IPv4 addresses.

  The returned string is of the format

    eth0=192.168.1.10, wlan0=192.168.16.14
  '''
  ret = []
  for i in sorted(netifaces.interfaces()):
    if i.startswith('lo'):
      # Boring
      continue

    try:
      addresses = netifaces.ifaddresses(i).get(netifaces.AF_INET, [])
    except ValueError:
      continue

    ips = [x.get('addr') for x in addresses
           if 'addr' in x] or ['none']

    ret.append('%s=%s' % (i, '+'.join(ips)))

  return ', '.join(ret)


class SystemStatus(object):
  '''Information about the current system status.

  This is information that changes frequently, e.g., load average
  or battery information.

  We log a bunch of system status here.
  '''

  GET_FAN_SPEED_RE = re.compile('Current fan RPM: ([0-9]*)')
  TEMP_SENSOR_RE = re.compile('Reading temperature...([0-9]*)')
  TEMPERATURE_RE = re.compile('^(\d+): (\d+)$', re.MULTILINE)
  TEMPERATURE_INFO_RE = re.compile('^(\d+): \d+ (.+)$', re.MULTILINE)

  def __init__(self):
    self.battery = {}
    self.battery_sysfs_path = None
    path_list = glob.glob('/sys/class/power_supply/*/type')
    for p in path_list:
      if open(p).read().strip() == 'Battery':
        self.battery_sysfs_path = os.path.dirname(p)
        break

    for k, item_type in [('charge_full', int),
                         ('charge_full_design', int),
                         ('charge_now', int),
                         ('current_now', int),
                         ('present', bool),
                         ('status', str),
                         ('voltage_min_design', int),
                         ('voltage_now', int)]:
      try:
        self.battery[k] = item_type(
          open(os.path.join(self.battery_sysfs_path, k)).read().strip())
      except:
        self.battery[k] = None

    # Get fan speed
    self.fan_rpm = GetEC().GetFanRPM()

    # Get temperatures from sensors
    try:
      self.temperatures = GetEC().GetTemperatures()
    except:
      self.temperatures = []

    try:
      self.main_temperature_index = GetEC().GetMainTemperatureIndex()
    except:
      self.main_temperature_index = None

    try:
      self.load_avg = map(
        float, open('/proc/loadavg').read().split()[0:3])
    except:
      self.load_avg = None

    try:
      self.cpu = map(int, open('/proc/stat').readline().split()[1:])
    except:
      self.cpu = None

    try:
      self.ips = GetIPv4Addresses()
    except:
      self.ips = None


if __name__ == '__main__':
  import yaml
  print yaml.dump(dict(system_info=SystemInfo(None, None).__dict__,
             system_status=SystemStatus().__dict__),
          default_flow_style=False)

