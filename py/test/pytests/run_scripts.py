# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs arbitary script and shows the stderr/stdout on the UI."""

import logging
import os
import re
import time
import subprocess
import threading
import unittest

from cros.factory.event_log import Log
from cros.factory.test import factory
from cros.factory.test.args import Arg
from cros.factory.test.event import Event
from cros.factory.test.test_ui import Escape, MakeLabel, UI
from cros.factory.test.ui_templates import OneScrollableSection
from cros.factory.utils.process_utils import Spawn

#TODO(itspeter): Fill the Chinese String in the MakeLabel
_TEST_TITLE = MakeLabel('Running Scrips', u'Running Scrips')
_CSS = '#state {text-align:left;}'


class UpdateFirmwareTest(unittest.TestCase):
  ARGS = [
    Arg('script_path', str, 'Full path of the script.'),
    Arg('arguments', list,
        'A list of additional arguments that will be pass to the script.',
        default=list(), optional=True),
    Arg('display', str,
        'Display the content from other files instead of stdout/stderr.',
        default=None, optional=True)
  ]

  def setUp(self):
    self.assertTrue(os.path.isfile(self.args.script_path),
                    msg='%s is missing.' % self.args.script_path)
    self._ui = UI()
    self._template = OneScrollableSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    self._ui.AppendCSS(_CSS)

  def RunSscript(self):
    """Runs script.

    While running, it shows updater activity on factory UI.
    """
    p = Spawn(
      [self.args.script_path] + self.args.arguments,
      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, log=True)

    full_output = ""
    if self.args.display:
      time.sleep(0.5) # Give time if the script need to clean up the log
      while p.poll() is None:
        if os.path.exists(self.args.display):
          with open(self.args.display) as f:
            to_display = f.read()
            self._template.SetState(Escape(to_display), append=False)
            full_output = Escape(to_display)
            time.sleep(0.1)
      # Final result.
      if os.path.exists(self.args.display):
        with open(self.args.display) as f:
          to_display = f.read()
          full_output = Escape(to_display)
          logging.info(full_output)

    else:
      for line in iter(p.stdout.readline, ''):
        logging.info(line.strip())
        self._template.SetState(Escape(line), append=True)
        full_output += Escape(line)

    Log('console_output', stdout=full_output)
    if p.poll() != 0:
      # Try to grep the failed reason from the script
      REG_EXP = r'\[goofy_error_msg\](.*)\[goofy_error_msg\]'
      match = re.search(REG_EXP, full_output, re.MULTILINE)
      fail_reason = (
          'Script reutnrs: %d.\n\nFull output=%r' %
          (p.returncode, full_output))
      if match:
        fail_reason = match.group(1)
        factory.logging.info("Get error reasons from script: %r", fail_reason)

      self._ui.Fail(fail_reason)
    else:
      self._ui.Pass()

  def runTest(self):
    threading.Thread(target=self.RunSscript).start()
    self._ui.Run()
