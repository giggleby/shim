# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test if the memory size is correctly written in the firmware.

Description
-----------
Linux kernel trusts the available memory region specified from firmware, via
ACPI or Device Tree. However, it is possible for the firmware to send wrong
values, for example always only assigning 8GB for kernel while the system
has 16GB memory installed.

On traditional PC, the memory information is stored on SPD chipset on memory
module so firmware should read and claim free space for kernel according to SPD.
On modern Chromebooks, the SPD is replaced by a pre-defined mapping table and
decided by straps. When the mapping table is out-dated, for example if an old
firmware is installed, then the allocated memory for kernel would be wrong.

The Chrome OS command, ``mosys``, can read from physical or virtual SPD and
report expected memory size. So this test tries to compare the value from
``mosys`` and kernel ``meminfo`` to figure out if firmware has reported wrong
memory size for kernel.

Usually firmware has to reserve some memory, for example ACPI tables, DMA,
I/O port mappings, so the kernel is expected to get less memory. This is
specified by argument ``max_diff_ratio``.

Meanwhile, for virtual SPD, it is possible that both firmware and ``mosys`` have
out-dated information of memory straps, so optionally we support a third source,
the shopfloor backend, to provide memory size.

If argument ``device_data_key`` is set, we will also check memory size by the
information from device data (usually retrieved from shopfloor backend if
factory supports it).

Test Procedure
--------------
This is an automated test without user interaction.

When started, the test collects memory size information from different source
and fail if the difference is too large.

Dependency
----------
- Command ``mosys``: ``mosys -k memory spd print geometry``.
- Kernel to support ``/proc/meminfo``, search for string ``MemTotal``.
- Optionally, shopfloor integration to save memory in device data.

Examples
--------
To compare and check only the memory size from ``mosys`` and kernel, add this
in test list::

  {
    "pytest_name": "memory_size"
  }

To read device data from Shopfloor Service then compare and check the memory
size from ``mosys``, kernel, and device data ``component.memory_size``, with
difference up to 20 percent::

  {
    "pytest_name": "shopfloor_service",
    "args": {
      "method": "GetDeviceInfo"
    }
  }

  {
    "pytest_name": "memory_size",
    "args": {
      "device_data_key": "component.memory_size",
      "max_diff_ratio": 0.2
    }
  }
"""

import re

from cros.factory.test import device_data
from cros.factory.test.i18n import _
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


class MemorySize(test_case.TestCase):
  related_components = (test_case.TestCategory.DRAM, )
  ARGS = [
      Arg('device_data_key', str,
          'Device data key for getting memory size in GB.', default=None),
      Arg('max_diff_ratio', float,
          ('Maximum tolerance difference between memory size detected by '
           'kernel and mosys within a ratio.'), default=0.2),
  ]

  def runTest(self):
    self.ui.SetState(_('Checking memory info...'))

    # Get memory info using mosys.
    ret = process_utils.CheckOutput(
        ['mosys', '-k', 'memory', 'spd', 'print', 'geometry'])
    mosys_mem_mb = sum([int(x) for x in re.findall('size_mb="([^"]*)"', ret)])

    # Get kernel meminfo.
    kernel_mem_mb = int(
        re.search(r'^MemTotal:\s*([0-9]+)\s*kB',
                  file_utils.ReadFile('/proc/meminfo')).group(1)) // 1024

    if abs(1.0 - kernel_mem_mb / mosys_mem_mb) > self.args.max_diff_ratio:
      self.fail(f'Kernel and mosys report different memory sizes: '
                f'mosys={int(mosys_mem_mb)}mb, kernel={int(kernel_mem_mb)}mb.')
      return

    if not self.args.device_data_key:
      return

    mosys_mem_gb = round(mosys_mem_mb / 1024.0, 1)
    sf_mem_gb = round(float(device_data.GetDeviceData(
        self.args.device_data_key)), 1)

    # The memory size info in mosys should be the same as that in device data.
    if abs(mosys_mem_gb - sf_mem_gb) > 10e-6:
      msg = (
          f'Memory size detected in mosys ({mosys_mem_gb:.1f} GB) is different '
          f'from the record in device data ({sf_mem_gb:.1f} GB)')
      self.fail(msg)
