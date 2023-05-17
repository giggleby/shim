# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Checks that the partition table extends nearly to the end of the storage
device.

Description
-----------
This test checks if the partition table allocates at least ``min_usage_pct``
percent of the storage. If not, this test expands stateful partition to the end
of the storage device by default. However, on disk_layout_v3, MINIOS-B locates
at the end of the partition table. This test will cache and remove MINIOS-B,
expand stateful partition and copy MINIOS-B back. This test will also resize
MINIOS-B so that its size is the same as MINIOS-A.

This test doesn't check the actual size of the stateful partition, rather the
sector at which it ends.

This test doesn't support remote device.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.

Dependency
----------
- `pygpt` utility.

Examples
--------
To run this pytest with default arguments, add this in test list::

  {
    "pytest_name": "partition_table"
  }

This is also predefined in ``generic_common.test_list.json`` as
``PartitionTable``.

If you can't expand stateful partition for some reason, override the argument
by::

  {
    "inherit": "PartitionTable",
    "args": {
      "expand_stateful": false
    }
  }
"""

import logging
import os

from cros.factory.device import device_utils
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import pygpt


class PartitionTableTest(test_case.TestCase):
  ARGS = [
      Arg('min_usage_pct', (int, float),
          'Percentage of the storage device that must be before the end of the '
          'stateful partition.  For example, if this is 95%, then the stateful '
          'partition must end at a sector that is >=95% of the total number of '
          'sectors on the device.',
          default=95),
      Arg('expand_stateful', bool,
          'Repair partition headers and tables and expand stateful partition '
          'to all available free space',
          default=True)
  ]

  def _ShowGPTTable(self, path):
    show_cmd = pygpt.GPTCommands.Show()
    show_cmd.ExecuteCommandLine(path)

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.gpt = None
    self.minios_b_cache = None

  def tearDown(self):
    if self.minios_b_cache:
      file_utils.TryUnlink(self.minios_b_cache)

  def runTest(self):
    self.assertTrue(self.dut.link.IsLocal(),
                    'This test only support local device')
    dev = self.dut.storage.GetMainStorageDevice()
    self.gpt = pygpt.GPT.LoadFromFile(dev)
    stateful_no = self.dut.partitions.STATEFUL.index
    stateful_part = self.gpt.GetPartition(stateful_no)
    minios_a_no = self.dut.partitions.MINIOS_A.index
    minios_a_part = self.gpt.GetPartition(minios_a_no)
    minios_b_no = self.dut.partitions.MINIOS_B.index
    minios_b_dev = self.dut.storage.GetMainStorageDevice(minios_b_no)
    minios_b_is_removed = False
    start_sector = stateful_part.FirstLBA
    sector_count = stateful_part.blocks
    end_sector = start_sector + sector_count
    sector_size = self.gpt.block_size

    # Linux always considers sectors to be 512 bytes long independently of the
    # devices real block size.
    device_size = 512 * int(
        self.dut.ReadFile('/sys/class/block/%s/size' % os.path.basename(dev)))

    pct_used = end_sector * sector_size * 100 / device_size

    logging.info(
        'start_sector=%d, sector_count=%d, end_sector=%d, device_size=%d',
        start_sector, sector_count, end_sector, device_size)
    logging.info('Stateful partition extends to %.3f%% of storage',
                 pct_used)

    # In disk_layout_v3, minios_b is the last partition.
    # We have to remove it temporary if we would like to expand the stateful
    # partition.
    has_minios_b = self.gpt.IsLastPartition(minios_b_no)
    if has_minios_b:
      logging.info('DUT is using disk_layout_v3.json.')

    if pct_used < self.args.min_usage_pct:
      if not self.args.expand_stateful:
        self.FailTask('Stateful partition does not cover enough of storage '
                      'device')

      # Repair partition headers and tables
      self.gpt.Resize(pygpt.GPT.GetImageSize(dev))

      # Calculate the size of minios_a and reserve space when expanding
      # stateful partition.
      reserved_blocks = minios_a_part.blocks if has_minios_b else 0

      if has_minios_b:
        self.gpt.WriteToFile(dev)
        # Copy the content of minios_a to minios_b partition.
        self.minios_b_cache = file_utils.CreateTemporaryFile(
            prefix='minios_b_cache')
        logging.info('Caching the content of MINIOS-B to %s',
                     self.minios_b_cache)
        self.dut.CheckCall([
            'dd', 'bs=1048576', f'if={minios_b_dev}',
            f'of={self.minios_b_cache}', 'iflag=fullblock', 'oflag=dsync'
        ], log=True)

        minios_b_is_removed = True
        pygpt.RemovePartition(dev, minios_b_no)
        # Reload gpt table since we removed partition minios_b.
        self.gpt = pygpt.GPT.LoadFromFile(dev)

      _, new_blocks = self.gpt.ExpandPartition(stateful_no, reserved_blocks)
      # Write back GPT table.
      self.gpt.WriteToFile(dev)

      if not has_minios_b:
        self._ShowGPTTable(dev)
        return

      # Add back partition minios_b.
      logging.info('Add back partition MINIOS-B.')
      add_cmd = pygpt.GPTCommands.Add()
      add_cmd.ExecuteCommandLine('-i', str(minios_b_no), '-t', 'minios', '-b',
                                 str(start_sector + new_blocks), '-s',
                                 str(reserved_blocks), '-l', 'MINIOS-B', dev)
      # Reload partition minios_b since it has changed.
      self.gpt = pygpt.GPT.LoadFromFile(dev)

    if has_minios_b:
      # Make sure that the partition size of minios_a/b are the same.
      minios_b_part = self.gpt.GetPartition(minios_b_no)
      if minios_a_part.blocks != minios_b_part.blocks:
        logging.info(
            'The partition size of MINIOS-A is %d, and MINIOS-B is '
            '%d. Resizing MINIOS-B so that their sizes are the same.',
            minios_a_part.blocks, minios_b_part.blocks)
        add_cmd = pygpt.GPTCommands.Add()
        add_cmd.ExecuteCommandLine('-i', str(minios_b_no), '-s',
                                   str(minios_a_part.blocks), dev)

      if minios_b_is_removed:
        logging.info('Copying back MINIOS-B.')
        self.dut.CheckCall([
            'dd', 'bs=1048576', f'if={self.minios_b_cache}',
            f'of={minios_b_dev}', 'iflag=fullblock', 'oflag=dsync'
        ], log=True)

        self._ShowGPTTable(dev)
