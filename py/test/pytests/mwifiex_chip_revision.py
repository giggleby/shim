# -*- coding: utf-8 -*-
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test that checks for marvell 8997 PCIe chip revision.

See crosbug.com/p/56042 for more info.
"""

import os
import re
import unittest

import factory_common  # pylint: disable=W0611

from cros.factory.device import device_utils
from cros.factory.utils.arg_utils import Arg


MARVELL_VENDOR_ID = '1b4b'


class MwifiexChipRevision(unittest.TestCase):
  """Test marvell 8997 PCIe chip revision id."""
  ARGS = [
      Arg('expected_device_id', str, 'expected PCIe device ID',
          default='2b42'),
      Arg('expected_revision_id', int, 'expected chip revision ID')
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def runTest(self):
    lspci_stdout = self.dut.CheckOutput(['lspci', '-n'])

    m = re.search(r'%s:%s \(rev (.*?)\)' %
                  (MARVELL_VENDOR_ID, self.args.expected_device_id),
                  lspci_stdout)
    if not m:
      raise RuntimeError('Fatal: Marvell chip with device_id %s not found!' %
                         self.args.expected_device_id)

    revision_id = int(m.groups(1)[0], 16)
    if revision_id != self.args.expected_revision_id:
      raise RuntimeError('Fatal: invalid WiFi chip revision 0x%x, the board '
                         'needs to be reworked.' % revision_id)
