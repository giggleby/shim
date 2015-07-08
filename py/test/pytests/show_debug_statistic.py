#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Displays a status of the current debug statistic in device-data."""

import datetime
import unittest
import logging
import posixpath
import xmlrpclib

import factory_common  # pylint: disable=W0611
from cros.factory.test.args import Arg
from cros.factory.test import test_ui
from cros.factory.test import shopfloor

CSS = """
table {
  margin-left: auto;
  margin-right: auto;
  padding-bottom: 1em;
}
th, td {
  padding: 0 1em;
}
"""

class ShowDebugStat(unittest.TestCase):
  """A factory test to report test status."""
  ARGS = [
      Arg('prefix_of_debug_keys', list,
          ('A list of the prefix of the debug information. <prefix>_total '
           'and <prefix>_success will be extracted to compute.'),
          optional=False, default=[]),
      Arg('save_to_shopfloor', bool,
          'True to save the data to the shopfloor in a CSV form.',
          default=False, optional=True),
  ]

  def runTest(self):
    ui = test_ui.UI(css=CSS)
    device_data = shopfloor.GetDeviceData()
    serial_number = device_data.get('mlb_serial_number', 'unknown')

    csv_header = ['serial_number']
    csv_row = [serial_number]
    table = []
    for prefix in self.args.prefix_of_debug_keys:
      total = device_data.get('%s_total' % prefix, 0)
      success = device_data.get('%s_success' % prefix, 0)
      csv_header.append('%s_total' % prefix)
      csv_header.append('%s_success' % prefix)
      csv_row.append(str(total))
      csv_row.append(str(success))

      status = 'passed' if success == total else 'failed-and-waived'
      table.append(('<tr class="test-status-%s" style="font-size: 300%%">'
                    '<th>%s</th><td>%s</td></tr>') %
                   (status, prefix, '%s / %s' % (success, total)))

    # Save to the shopfloor if save_to_shopfloor
    logging.info('Uploading debug statistic as CSV to shopfloor.')
    csv_filename = 'debug_stat_%s_%s.csv' % (
        datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3],  # time
        serial_number)
    csv_content = '%s\n%s' % (','.join(csv_header), ','.join(csv_row))
    shopfloor_server = shopfloor.GetShopfloorConnection()
    shopfloor_server.SaveAuxLog(
        posixpath.join('debug_stat', csv_filename),
        xmlrpclib.Binary(csv_content))

    html = [
        '<div class="test-vcenter-outer"><div class="test-vcenter-inner">',
        test_ui.MakeLabel('Debug statistic:', u'测试統計列表：'),
        '<table>'] + table + ['</table>']

    html = html + ['<a onclick="onclick:window.test.pass()" href="#">',
                   test_ui.MakeLabel('Click or press SPACE to continue',
                                     u'点击或按空白键继续'),
                   '</a>']
    html = html + ['</div></div>']

    ui.EnablePassFailKeys()
    ui.BindStandardKeys(bind_fail_keys=False)

    ui.SetHTML(''.join(html))
    ui.Run()
