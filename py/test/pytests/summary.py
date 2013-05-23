#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''
Displays a status summary for all tests in the current section
(up to, but not including, this test).

For example, if the test tree is

SMT
  ...
Runin
  A
  B
  C
  report (this test)
  shutdown

...then this test will show the status summary for A, B, and C.

dargs:
  disable_input_on_fail: Disable user input to pass/fail when
    the overall status is not PASSED. If this argument is True and overall
    status is PASSED, user can pass the test by clicking the item or hitting
    space. If this argument is True and overall status is not PASSED,
    the test will hang there while the control menu can still work to
    stop/abort the test.
'''

import logging
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test.args import Arg
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test.fixture import bft_fixture

CSS = '''
table {
  margin-left: auto;
  margin-right: auto;
  padding-bottom: 1em;
}
th, td {
  padding: 0 1em;
}
'''

class Report(unittest.TestCase):
  ARGS = [
    Arg('disable_input_on_fail', bool,
        'Disable user input to pass/fail when the overall status is not PASSED',
        default=False),
    Arg('bft_fixture', dict,
        ('BFT fixture arguments (see bft_fixture test).  If provided, then a '
         'red/green light is lit to indicate failure/success rather than '
         'showing the summary on-screen.  The test does not fail if unable '
         'to connect to the BFT fixture.'),
        optional=True),
    ]

  def runTest(self):
    test_list = self.test_info.ReadTestList()
    test = test_list.lookup_path(self.test_info.path)
    states = factory.get_state_instance().get_test_states()

    ui = test_ui.UI(css=CSS)

    statuses = []

    table = []
    for t in test.parent.subtests:
      if t == test:
        break

      state = states.get(t.path)

      table.append('<tr class="test-status-%s"><th>%s</th><td>%s</td></tr>'
                   % (state.status,
                      test_ui.MakeTestLabel(t),
                      test_ui.MakeStatusLabel(state.status)))
      statuses.append(state.status)

    overall_status = factory.overall_status(statuses)

    html = [
        '<div class="test-vcenter-outer"><div class="test-vcenter-inner">',
        test_ui.MakeLabel('Test Status for %s:' % test.parent.path,
                          u'%s 测试结果列表：' % test.parent.path),
        '<div class="test-status-%s" style="font-size: 300%%">%s</div>' % (
            overall_status, test_ui.MakeStatusLabel(overall_status)),
        '<table>'] + table + ['</table>']
    if (not self.args.disable_input_on_fail or
        overall_status == factory.TestState.PASSED):
      html = html + ['<a onclick="onclick:window.test.pass()" href="#">',
                     test_ui.MakeLabel('Click or press SPACE to continue',
                                       u'点击或按空白键继续'),
                     '</a>']
    else:
      html = html + [test_ui.MakeLabel(
          'Unable to proceed, since some previous tests have not passed.',
          u'之前所有的测试必须通过才能通过此项目')]
    html = html + ['</div></div>']
    if not self.args.disable_input_on_fail:
      ui.EnablePassFailKeys()
    # If disable_input_on_fail is True, and overall status is PASSED, user
    # can only pass the test.
    elif overall_status == factory.TestState.PASSED:
      ui.BindStandardKeys(bind_fail_keys=False)

    if self.args.bft_fixture:
      try:
        fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)
        fixture.SetStatusColor(
            fixture.StatusColor.GREEN
            if overall_status == factory.TestState.PASSED
            else fixture.StatusColor.RED)
        fixture.Disconnect()
      except bft_fixture.BFTFixtureException:
        logging.exception('Unable to set status color on BFT fixture')

    ui.SetHTML(''.join(html))
    ui.Run()
