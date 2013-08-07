# -*- mode: python; coding: utf-8 -*-
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Writes a subset device data to the RW VPD.

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
    Arg('vpd_data_fields', list,
         ('Fields to write into RW_VPD from device_data.'
          'Each item is a tuple of the form (prefix, key) meaning that the '
          'pair (prefix + key, value) should be added into RW_VPD if there is '
          'a pair (key, value) in device_data.'),
        default=[], optional=True),
    Arg('keys', (list, tuple), 'Keys to write to the VPD.',
        default=[], optional=True),
    Arg('prefix', str, 'Prefix to use when writing keys to the VPD.',
        default='factory.device_data.', optional=True),

  ]

  def runTest(self):
    ui = test_ui.UI()
    template = ui_templates.OneSection(ui)
    template.SetState(test_ui.MakeLabel(
        'Writing device data to RW VPD...',
        '机器资料正在写入到 RW VPD...'))

    # This is for backward capability.
    # Previously it did not have 'vpd_data_fields' and writes all keys
    # with prefix into RW_VPD.
    if self.args.vpd_data_fields is []:
      for k in self.args.keys:
        self.args.vpd_data_fields.append((self.args.prefix, k))

    device_data = shopfloor.GetDeviceData()
    # d[0] is prefix and d[1] is key
    data_to_write = dict((d[0] + d[1], device_data.get(d[1]))
                         for d in self.args.vpd_data_fields)
    missing_keys = [k for k, v in data_to_write.iteritems() if v is None]
    if missing_keys:
      self.fail('Missing device data keys: %r' % sorted(missing_keys))

    vpd.rw.Update(dict((k, str(v))
                       for k, v in data_to_write.iteritems()))
