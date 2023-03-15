# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time
from typing import List

from cros.factory.goofy.plugins import periodic_plugin
from cros.factory.goofy.plugins import plugin
from cros.factory.utils import process_utils
from cros.factory.utils import schema
from cros.factory.utils import type_utils


_ASIX_DONGLE_VENDOR = 'ASIX Electronics Corp.'

_IP_CIDR_SCHEMA = schema.JSONSchemaDict(
    'ip_cidr_list schema',
    {
        'type': 'array',
        'items': {
            'type': 'string',
            'minItems': 1
        }
    },
)

_MODULE_RELOAD_SECS = 2


class AsixNetworkMonitor(periodic_plugin.PeriodicPlugin):

  def __init__(self, goofy, ip_cidr_list: List, scan_periods_secs: int = 30):
    """Constructor

    Args:
      ip_cidr_list: A list containing the network IP/CIDR.
      scan_periods_secs: Scan Ethernet connection at the given interval.
    """
    if scan_periods_secs <= _MODULE_RELOAD_SECS:
      raise RuntimeError(
          'scan_periods_secs should be greater than the time we wait for the '
          f'kernel module to reload. scan_periods_secs: {scan_periods_secs}s. '
          f'Time wait for kernel module to reload: {_MODULE_RELOAD_SECS}s.')
    super().__init__(goofy, scan_periods_secs, [plugin.RESOURCE.NETWORK])
    _IP_CIDR_SCHEMA.Validate(ip_cidr_list)
    self._ip_cidr_list = ip_cidr_list

  @type_utils.Overrides
  def RunTask(self):
    if self._IsAsixDonglePlugined():
      if self._HasNetworkConnection():
        return
      logging.info('Dongle is inserted but there\'s no IP. '
                   'Try to rmmod and modprobe the kernel module ...')
      self._ForceReloadAsixModule()
    else:
      logging.info('Did not detect Asix dongle. Do nothing.')

  def _IsAsixDonglePlugined(self):
    lsusb_rows = process_utils.CheckOutput(['lsusb']).splitlines()
    for row in lsusb_rows:
      if _ASIX_DONGLE_VENDOR in row:
        return True
    return False

  def _ForceReloadAsixModule(self):
    logging.info("Force reloading Asix module ...")
    process_utils.LogAndCheckOutput(['rmmod', 'asix'])
    time.sleep(_MODULE_RELOAD_SECS)
    process_utils.LogAndCheckOutput(['modprobe', 'asix'])

  def _HasNetworkConnection(self):
    for ip_cidr in self._ip_cidr_list:
      stdout = process_utils.LogAndCheckOutput(
          ['ip', 'addr', 'show', 'to', ip_cidr]).strip()
      if stdout:
        logging.info(stdout)
        logging.info('Device has Internet connection!')
        return True
    return False
