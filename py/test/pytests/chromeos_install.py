# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs chromeos-install."""

import logging
import os
import subprocess
import threading
import unittest

from cros.factory.test.args import Arg
from cros.factory.test.test_ui import Escape, MakeLabel, UI
from cros.factory.test.ui_templates import OneScrollableSection
from cros.factory.utils.process_utils import Spawn, CheckOutput

_TEST_TITLE = MakeLabel('Installing ChromeOS', u'更新ChromeOS')
_CSS = '#state {text-align:left;}'


class ChromeOSInstallTest(unittest.TestCase):
  ARGS = [
    Arg('usb_rootdev', str, 'Path to USB device.', optional=False),
  ]

  def setUp(self):
    self._ui = UI()
    self._template = OneScrollableSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    self._ui.AppendCSS(_CSS)

  def InstallChromeOS(self):
    """Runs chromeos-install.

    While installing, it shows updater activity on factory UI.
    """
    p = Spawn(['chromeos-install', '--yes', '--skip_src_removable'],
              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, log=True)
    for line in iter(p.stdout.readline, ''):
      logging.info(line.strip())
      self._template.SetState(Escape(line), append=True)

    if p.poll() != 0:
      self._ui.Fail('ChromeOS installation failed: %d.' % p.returncode)
    else:
      Spawn(['sync'])
      Spawn(['reboot'])

  def runTest(self):
    rootdev = CheckOutput(['rootdev', '-s']).strip()
    if not rootdev.startswith(self.args.usb_rootdev):
      return
    threading.Thread(target=self.InstallChromeOS).start()
    self._ui.Run()
