# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Archive instalog data.

Description
-----------
This pytest will save instalog files to filesystem (internal / external
storage).  This pytest basically invokes `instalog archive`, you can check
py/instalog/cli.py for more details about the command.

Test Procedure
--------------
If the file will be saved to external storage, the test will ask operator to
insert USB disk and press SPACE.  Otherwise, this test doesn't require operator
interaction.

Dependency
----------
instalog

Examples
--------
Here is an example::

  "ArchiveInstalogData": {
    "label": "Archive Instalog Data",
    "pytest_name": "archive_instalog_data",
    "args": {
      "path": "usb://logs/{SN}.tar"
    }
  }

"""

import logging
import os
import threading
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.goofy.plugins import plugin_controller
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.tools import factory_bug
from cros.factory.utils.arg_utils import Arg


PREFIX_USB = 'usb://'
PROMPT_INSERT_USB_DISK = i18n_test_ui.MakeI18nLabel(
    'Please insert USB disk to save instalog data and then press SPACE')
PROMPT_SAVING = i18n_test_ui.MakeI18nLabel('Saving...')


class ArchiveInstalogData(unittest.TestCase):
  ARGS = [
      Arg('path', str,
          'Path to save the archived logs, it will be an tar file. {SN} in '
          'path will be replaced by device serial number. If the path starts '
          'with "usb://", the path will be point to external USB disk.',
          default='usb://{SN}.tar'),
      Arg('detail', int, 'Extra detail level you want', default=0),
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.ui = test_ui.UI()
    self.space_pressed = threading.Event()

  def runTest(self):
    self.ui.BindKey(test_ui.SPACE_KEY, lambda _: self.space_pressed.set())
    self.ui.RunInBackground(self._runTest)
    self.ui.Run()

  def _runTest(self):
    template = ui_templates.OneSection(self.ui)

    instalog = plugin_controller.GetPluginRPCProxy('instalog')
    if instalog is None:
      logging.error('Cannot get proxy for instalog plugin, abort...')
      raise Exception('No Instalog Proxy')

    path = self.args.path.format(SN=self.dut.info.GetSerialNumber())

    if path.startswith(PREFIX_USB):
      rest = path[len(PREFIX_USB):]

      while True:
        template.SetState(PROMPT_INSERT_USB_DISK)
        self.space_pressed.wait()

        try:
          with factory_bug.MountUSB() as mount:
            template.SetState(PROMPT_SAVING)
            path = os.path.join(mount.mount_point, rest)
            instalog.Archive(path, self.args.detail)
            break
        except IOError:
          # failed to mount USB, try again...
          self.space_pressed.clear()
    else:
      template.SetState(PROMPT_SAVING)
      instalog.Archive(path, self.args.detail)
