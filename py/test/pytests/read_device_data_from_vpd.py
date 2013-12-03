# -*- mode: python; coding: utf-8 -*-
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Reads device data from the RW VPD, if present.

Data is all read as strings."""


import unittest


import factory_common  # pylint: disable=W0611
from cros.factory.system import vpd
from cros.factory.test import factory
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg


class CallShopfloor(unittest.TestCase):
  ARGS = [
    Arg('vpd_data_fields', list,
         ('Fields to write into shopfloor device_data from RW_VPD.'
          'Each item is a tuple of the form (prefix, key) meaning that the '
          'pair (key, value) should be added into device_data if there is '
          'a pair (prefix + key, value) in RW_VPD . If key is *, it means '
          'all keys with the prefix should be added.'),
        default=[], optional=True),
    Arg('prefix', str,
        ('Prefix to use when reading keys from the RW_VPD. The prefix is '
         'stripped; e.g., if there is a VPD entry for '
         'factory.device_data.foo=bar, then foo=bar is added to device_data.'
         'This option only applies if vpd_data_fields is [].'),
        default='factory.device_data.', optional=True),
  ]

  def _ShouldIncludeKey(self, vpd_key, vpd_data_fields):
    # vpd_data_fields[0] is prefix
    # vpd_data_fields[1] is key
    if vpd_data_fields[1] == '*':
      return vpd_key.startswith(vpd_data_fields[0])
    else:
      return vpd_key == vpd_data_fields[0] + vpd_data_fields[1]

  def runTest(self):
    ui = test_ui.UI()
    template = ui_templates.OneSection(ui)
    template.SetState(test_ui.MakeLabel(
        'Reading device data from RW VPD...',
        '正在从 RW VPD 读机器资料...'))

    # This is for backward capability.
    # Previously it did not have 'vpd_data_fields' and reads all keys
    # with prefix in RW_VPD.
    if self.args.vpd_data_fields == []:
      self.args.vpd_data_fields = [(self.args.prefix, '*')]

    vpd_data = vpd.rw.GetAll()
    for d in self.args.vpd_data_fields:
      shopfloor.UpdateDeviceData(
          dict((k[len(d[0]):],
                (v.upper() == 'TRUE') if v.upper() in ['TRUE', 'FALSE'] else v)
               for k, v in vpd_data.iteritems() if self._ShouldIncludeKey(
                   k, d)))

    factory.get_state_instance().UpdateSkippedTests()
