# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
# This factory test checks board version and rev id by mosys.
# The path to mosys binary can be specified in test args since we might need
# to hack mosys sometimes.

import re
import unittest

from cros.factory.test import factory
from cros.factory.test.args import Arg
from cros.factory.utils.process_utils import Spawn

_RE_REV = re.compile(
    r'^\w+: v0: (\w), v1: (\w), v2: (\w) => rev (\w)$', flags=re.MULTILINE)

class CheckBoardVersionTest(unittest.TestCase):
  ARGS = [
    Arg('mosys_path', str, 'path to mosys binary',
        default='/usr/sbin/mosys'),
    Arg('board_version', str, 'board version like "PVT".'),
    Arg('board_rev_ids', list, 'a list of valid rev ids read from resistors')]

  def runTest(self):
    process = Spawn([self.args.mosys_path, '-vvv', 'platform', 'version'],
                    check_output=True, read_stderr=True, log=True)
    board_version = process.stdout_data.strip()
    factory.console.info('board version: %s', board_version)
    rev_search = _RE_REV.search(process.stderr_data)
    v0, v1, v2, rev = (rev_search.groups() if rev_search
        else (None, None, None, None))
    factory.console.info('resistors: v0: %s, v1: %s, v2: %s', v0, v1, v2)
    factory.console.info('rev id: %s', rev)
    self.assertEquals(self.args.board_version, board_version)
    self.assertTrue(rev in self.args.board_rev_ids,
        'rev id %s is not in valid id list %s' % (rev, self.args.board_rev_ids))
