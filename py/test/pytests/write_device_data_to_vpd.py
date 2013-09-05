# -*- mode: python; coding: utf-8 -*-
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Writes a subset device data to VPD.

Arguments:
  rw_keys: Keys to write to RW VPD.
  rw_prefix: Prefix to use when writing keys to RW VPD.
  ro_keys: Keys to write to RO VPD.
  ro_prefix: Prefix to use when writing ro_keys to RO VPD.
Data is all written as strings."""


import unittest


import factory_common  # pylint: disable=W0611
from cros.factory.system import vpd
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg


class CallShopfloor(unittest.TestCase):
  ARGS = [
    Arg('rw_keys', (list, tuple), 'Keys to write to RW VPD.'),
    Arg('rw_prefix', str, 'Prefix to use when writing keys to RW VPD.',
        default='factory.device_data.'),
    Arg('ro_keys', (list, tuple), 'Keys to write to RO VPD', default=None,
        optional=True),
    Arg('ro_prefix', str, 'Prefix to use when writing keys to RO VPD.',
        default='factory.device_data.')
  ]

  def runTest(self):
    ui = test_ui.UI()
    template = ui_templates.OneSection(ui)
    device_data = shopfloor.GetDeviceData()
    for label, keys, prefix in [('rw', self.args.rw_keys, self.args.rw_prefix),
                                ('ro', self.args.ro_keys, self.args.ro_prefix)]:
      if not keys:
        continue
      template.SetState(test_ui.MakeLabel(
          'Writing device data to %s VPD...' % label.upper(),
          '机器资料正在写入到 %s VPD...' % label.upper()))

      data_to_write = dict((k, device_data.get(k))
                           for k in keys)
      missing_keys = [k for k, v in data_to_write.iteritems() if v is None]
      if missing_keys:
        self.fail('Missing device data keys for %s vpd: %r' % (
            label.upper(), sorted(missing_keys)))

      getattr(vpd, label).Update(dict((prefix + k, str(v))
                                      for k, v in data_to_write.iteritems()))
