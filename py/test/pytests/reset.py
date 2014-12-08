#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Resets the test list by invoking factory_restart -a
'''

import logging
import os
import time
import unittest

import factory_common  # pylint: disable=W0611

from cros.factory.test import factory
from cros.factory.test.args import Arg
from cros.factory.utils.process_utils import Spawn

class ResetTest(unittest.TestCase):

  ARGS = [
      Arg('command', list, 'The command to run.',
          default=['factory_restart', '-a'])
      ]

  def setUp(self):
    self._command = self.args.command

  def runTest(self):
    Spawn(self._command, call=True, log_stderr_on_error=True)
    # This is expected to kill us. Give it a chance to, and then
    # fail if we're still alive.
    time.sleep(10)
    self.Fail('Test was expected to reset')

  def tearDown(self):
    pass
