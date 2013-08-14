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
from cros.factory.system.disk_space import GetMaxStatefulPartitionUsage

class CheckDiskSpaceTest(unittest.TestCase):
  ARGS = [
    Arg('stateful_partition_threshold_pct', (int, float),
        'Threshold of disk usage.', default=95)]

  def runTest(self):
    max_partition, max_usage_type, max_usage = GetMaxStatefulPartitionUsage()
    logging.info('%s partition %s usage %d%%',
                 max_partition, max_usage_type, max_usage)
    self.assertLessEqual(max_usage, self.args.stateful_partition_threshold_pct,
        ('%s partition %s usage %d%% is above threshold %d%%' %
         (max_partition, max_usage_type, max_usage,
          self.args.stateful_partition_threshold_pct)))
