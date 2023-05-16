# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Selectively copies the miniOS part that has the same recovery key ver as FW.

Description
-----------
miniOS A/B are signed with different recovery key, with A signed with the old
one and B signed with the new one. This test copies the miniOS partition with
the same recovery key version as firmware and overrides the other miniOS
partition.

Test Procedure
--------------
1. Checks if DUT is using disk_layout_v3. If not, ends the test.
2. Gets the recovery key version from the firmware.
3. If the recovery key version is 1, uses miniOS A as source part.
   Else uses miniOS B.
4. Copies the source partition to the destination partition.
5. Now the miniOS A and minios B are the same.

Dependency
----------
gbb_utility, futility

Examples
--------
To run the test, do::

  {
    "pytest_name": "copy_minios"
  }

"""

import logging
import re

from cros.factory.device import device_utils
from cros.factory.test import test_case
from cros.factory.utils import file_utils
from cros.factory.utils import pygpt
from cros.factory.utils.type_utils import Error


class CopyMiniOSError(Error):
  pass


_RECOVERY_KEY_VER_REGEX = r'\s+Key Version:\s+(?P<key_ver>\w+)'


class CopyMiniOS(test_case.TestCase):

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    dev = self.dut.storage.GetMainStorageDevice()
    self.gpt = pygpt.GPT.LoadFromFile(dev)
    self.minios_a_no = self.dut.partitions.MINIOS_A.index
    self.minios_b_no = self.dut.partitions.MINIOS_B.index

  def IsDiskLayoutV3(self):
    return self.gpt.IsLastPartition(self.minios_b_no)

  def GetRecoveryKeyVer(self):
    """Gets the recovery key version from the FW installed on DUT."""
    with file_utils.UnopenedTemporaryFile(prefix='minios_') as temp_f:
      logging.info('Exporting the recovery key to %s ...', temp_f)
      self.dut.CheckCall(['gbb_utility', '-r', temp_f, '--flash'], log=True)
      logging.info('Reading the recovery key info ...')
      output = self.dut.CheckOutput(['futility', 'show', temp_f], log=True)
      logging.info('Recovery key info\n%s', output)
      match = re.search(_RECOVERY_KEY_VER_REGEX, output)
      if match:
        key_ver = match.group('key_ver')
        logging.info("Recovery key version is %s", key_ver)
        return int(key_ver)
    raise CopyMiniOSError(f'Fail to extract key version from {temp_f}')

  def GetMiniOSPartByRecoveryKeyVer(self, recovery_key_ver):
    """Gets the src and dst minios partition by the given recovery key ver."""
    if recovery_key_ver == 1:
      return self.minios_a_no, self.minios_b_no
    return self.minios_b_no, self.minios_a_no

  def runTest(self):
    if not self.IsDiskLayoutV3():
      logging.info('Disk is not using disk_layout_v3.json. '
                   'Skip copying minios.')
      return

    minios_a_part_size = self.gpt.GetPartition(self.minios_a_no).blocks
    minios_b_part_size = self.gpt.GetPartition(self.minios_b_no).blocks
    if minios_a_part_size != minios_b_part_size:
      raise CopyMiniOSError(
          f'The size of minios_a ({minios_a_part_size}) and b '
          f'({minios_b_part_size}) should be the same. Please run '
          ' partition_table.py to fix it.')

    recovery_key_ver = self.GetRecoveryKeyVer()
    src_part, dst_part = self.GetMiniOSPartByRecoveryKeyVer(recovery_key_ver)
    src = self.dut.storage.GetMainStorageDevice(src_part)
    dst = self.dut.storage.GetMainStorageDevice(dst_part)

    logging.info('Copying partition %d to %d ...', src_part, dst_part)
    self.dut.CheckCall([
        'dd', 'bs=1048576', f'if={src}', f'of={dst}', 'iflag=fullblock',
        'oflag=dsync'
    ], log=True)
