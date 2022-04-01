# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import logging
import os
import os.path

from cros.factory.probe.functions import sysfs
from cros.factory.probe.functions import usb
from cros.factory.probe.lib import cached_probe_function

_INTERFACE_CLASS_VALUE = 0x0b
_INTERFACE_CLASS_FIELD = 'bInterfaceClass'


class SmartCardUSBFunction(cached_probe_function.GlobPathCachedProbeFunction):
  """Probes all USB smart card reader devices.

  Description
  -----------
  This function goes through ``/sys/bus/usb/devices/`` to read attributes of
  each usb device and find out all smart card readers there.  Each result
  must contain these fields:

  - ``device_path``: Pathname of the sysfs directory.
  - ``idVendor``
  - ``idProduct``

  The result might also contain these optional fields if they are exported in
  the sysfs entry:

  - ``manufacturer``
  - ``product``
  - ``bcdDevice``
  """
  GLOB_PATH = '/sys/bus/usb/devices/*'

  @classmethod
  def ProbeDevice(cls, dir_path):
    # An USB device might have multiple interfaces, each is represented as
    # a sub-folder inside the device's sysfs node.  We treat a device a
    # smart card reader if any of its interface has the specific class code.
    for interface_path_candidate in glob.glob(
        os.path.join(dir_path, f'{os.path.basename(dir_path)}:*')):
      interface_probed_result = sysfs.ReadSysfs(interface_path_candidate,
                                                [_INTERFACE_CLASS_FIELD])
      if interface_probed_result is None:
        continue
      raw_interface_probed_result = interface_probed_result[
          _INTERFACE_CLASS_FIELD]
      try:
        actual_interface_class_value = int(raw_interface_probed_result, 16)
      except ValueError:
        logging.warning('Unexpected %s value: %s.', _INTERFACE_CLASS_FIELD,
                        raw_interface_probed_result)
        continue
      if actual_interface_class_value == _INTERFACE_CLASS_VALUE:
        break
    else:
      return None
    return usb.ReadUSBSysfs(dir_path)
