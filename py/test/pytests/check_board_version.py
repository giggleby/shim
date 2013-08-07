# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
# This factory test checks board version by mosys. The path to mosys binary
# can be specified in test args since we might need to hack mosys sometimes.

import unittest

from cros.factory.test import factory
from cros.factory.test.args import Arg
from cros.factory.utils.process_utils import CheckOutput

class CheckBoardVersionTest(unittest.TestCase):
  ARGS = [
    Arg('mosys_path', str, 'path to mosys binary',
        default='/usr/sbin/mosys'),
    Arg('board_version', str, 'board version like "PVT".')]

  def runTest(self):
    board_version = CheckOutput([self.args.mosys_path, 'platform', 'version'],
                                log=True).strip()
    factory.console.info('board version: %s', board_version)
    self.assertEquals(self.args.board_version, board_version)
