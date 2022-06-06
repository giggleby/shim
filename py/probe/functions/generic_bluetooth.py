# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from cros.factory.probe import function
from cros.factory.probe.lib import cached_probe_function


def _ProbePCIOrUSB(path):
  path = os.path.abspath(os.path.realpath(path))
  return (function.InterpretFunction({'pci': path})() or
          function.InterpretFunction({'usb': os.path.join(path, '..')})())


def _RecursiveProbe(path, read_method):
  """Recursively probes in path and all the subdirectory using read_method.

  Args:
    path: Root path of the recursive probing.
    read_method: The method used to probe device information.
      This method accepts an input path and returns a list of dictionaries.
      e.g. _ReadSysfsUsbFields, _ReadSysfsPciFields, or _ReadSysfsDeviceId.

  Returns:
    A list of dictionaries, each contain the probe result from a subdirectory
    of the given path.
  """
  visited_path = set()
  results = []

  def _InternalRecursiveProbe(path):
    """Recursively probes in path and all the subdirectory using read_method.

    Args:
      path: Root path of the recursive probing.
    """
    path = os.path.realpath(path)
    if path in visited_path or not os.path.isdir(path):
      return

    data = read_method(path)
    # Only append new data
    for result in data:
      if result not in results:
        results.append(result)
    entries_list = os.listdir(path)
    visited_path.add(path)

    for filename in entries_list:
      # Do not search directory upward
      if filename == 'subsystem':
        continue
      sub_path = os.path.join(path, filename)
      _InternalRecursiveProbe(sub_path)

  _InternalRecursiveProbe(path)
  return results


class GenericBluetoothFunction(cached_probe_function.CachedProbeFunction):
  """Probe the generic Bluetooth information."""

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    # Probe in primary path
    probe_results = _ProbePCIOrUSB('/sys/class/bluetooth/hci0/device')
    if not probe_results:
      # TODO(akahuang): Confirm if we only probe the primary path or not.
      # Use information in driver if probe failed in primary path
      probe_results = _RecursiveProbe('/sys/module/bluetooth/holders',
                                      _ProbePCIOrUSB)
    return probe_results
