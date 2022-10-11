# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from cros.factory.probe.functions import sysfs
from cros.factory.probe.functions import usb
from cros.factory.probe.lib import cached_probe_function
from cros.factory.utils import type_utils


RemovableResult = type_utils.Enum(('fixed', 'removable', 'unknown'))

_REMOVABLE_FIELD = 'removable'
_ALLOWED_VID_PID_LIST = frozenset([
    ('0c27', '3bfa'),
])


class NFCUSBFunction(cached_probe_function.GlobPathCachedProbeFunction):
  """Probes internal USB NFC reader devices.

  Description
  -----------
  This function goes through ``/sys/bus/usb/devices/`` to read attributes of
  each usb device and find out all NFC readers there.  Each result must contain
  these fields:

  - ``device_path``: Pathname of the sysfs directory.
  - ``idVendor``
  - ``idProduct``

  The result might also contain these optional fields if they are exported in
  the sysfs entry:

  - ``manufacturer``
  - ``product``
  - ``bcdDevice``

  Because we cannot differentiate between keyboards and nfc readers, we
  make an explicit list of allowed (vid, pid).
  """
  GLOB_PATH = '/sys/bus/usb/devices/*'

  @classmethod
  def ProbeDevice(cls, dir_path):
    removable_probed_result = sysfs.ReadSysfs(dir_path, [_REMOVABLE_FIELD])
    logging.debug('%r for %r is %r', _REMOVABLE_FIELD, dir_path,
                  removable_probed_result)
    if removable_probed_result is None:
      return None
    if removable_probed_result[_REMOVABLE_FIELD] != RemovableResult.fixed:
      return None

    result = usb.ReadUSBSysfs(dir_path)
    if (result['idVendor'], result['idProduct']) in _ALLOWED_VID_PID_LIST:
      return result
    return None
