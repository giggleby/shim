# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
# This factory test checks disk space usage is not above certain threshold.

import logging
import unittest

from cros.factory.test.args import Arg
from cros.factory.system.disk_space import (GetMaxStatefulPartitionUsage,
        GetEncyptedStatefulPartitionUsage)

class CheckDiskSpaceTest(unittest.TestCase):
  ARGS = [
    Arg('stateful_partition_threshold_pct', (int, float),
        'Threshold of stateful partition usage.', default=95),
    Arg('encrypted_stateful_partition_threshold_pct', (int, float),
        'Threshold of encrypted stateful partition usage.', default=95)]

  def runTest(self):
    if self.args.stateful_partition_threshold_pct:
      max_partition, max_usage_type, max_usage = GetMaxStatefulPartitionUsage()
      logging.info('%s partition %s usage %d%%',
                   max_partition, max_usage_type, max_usage)
      self.assertLessEqual(max_usage,
          self.args.stateful_partition_threshold_pct,
          ('%s partition %s usage %d%% is above threshold %d%%' %
           (max_partition, max_usage_type, max_usage,
            self.args.stateful_partition_threshold_pct)))
    if self.args.encrypted_stateful_partition_threshold_pct:
      usage = GetEncyptedStatefulPartitionUsage()
      logging.info('encrypted stateful partition usage: bytes: %d%%,'
                   ' inodes: %d%%',
                   usage.bytes_used_pct, usage.inodes_used_pct)
      self.assertLessEqual(usage.bytes_used_pct,
          self.args.encrypted_stateful_partition_threshold_pct,
          ('encrypted stateful partition bytes usage %d%% is '
           'above threshold %d%%' % (usage.bytes_used_pct,
               self.args.encrypted_stateful_partition_threshold_pct)))
      self.assertLessEqual(usage.inodes_used_pct,
          self.args.encrypted_stateful_partition_threshold_pct,
          ('encrypted stateful partition inodes usage %d%% is '
           'above threshold %d%%' % (usage.inodes_used_pct,
               self.args.encrypted_stateful_partition_threshold_pct)))
