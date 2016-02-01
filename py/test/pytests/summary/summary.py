#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Displays a status summary for all tests in the current section.

The summary includes tests up to, but not including, this test).

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
"""

import logging
import threading
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory import system
from cros.factory.test.args import Arg
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test.fixture import bft_fixture

CSS = """
table {
  margin-left: auto;
  margin-right: auto;
  padding-bottom: 1em;
}
th, td {
  padding: 0 1em;
}
.screensaver-font-size {
  font-size: 8em;
  color: white;
}
"""

_CSS_SCREENSAVER = """
.display-full-screen-hide {
  background-color: white;
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  top: 0;
  visibility: hidden;}
.display-full-screen-show {
  background-color: white;
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  top: 0;
  visibility: visible;}
"""

_JS_SCREENSAVER = """
DisplayTest = function() {
  this.display = false;
  this.focusItem = 0;
  this.styleDiv = null;
  this.fullScreenElement = null;
  this.text_zh = null;
  this.text_en = null;
};

/**
 * Creates a display test and runs it.
 */
function setupDisplayTest() {
  window.displayTest = new DisplayTest();
  window.displayTest.setupFullScreenElement();
  window.onkeydown = function(event) {
    test.sendTestEvent("onScreensaverOff", {});
  }
}

function changeBackgroundColor(color, text_color) {
  window.displayTest.fullScreenElement.style.backgroundColor=color;
  window.displayTest.text_zh.style.color=text_color;
  window.displayTest.text_en.style.color=text_color;
}

/**
 * Switches the display.
 */
function switchDisplayOnOff() {
  window.displayTest.switchDisplayOnOff();
}

/**
 * Initializes fullscreen elements.
 */
DisplayTest.prototype.setupFullScreenElement = function() {
  this.fullScreenElement = document.getElementById("display-test-container");
  this.text_en= document.getElementById("text-screensaver-en");
  this.text_zh= document.getElementById("text-screensaver-zh");
  this.fullScreenElement.className = "display-full-screen-hide";
};

/**
 * Toggles the fullscreen display visibility.
 */
DisplayTest.prototype.switchDisplayOnOff = function() {
  //If current display is on, turns it off
  if (this.display) {
    this.switchDisplayOff();
  } else {
    this.switchDisplayOn();
  }

};

/**
 * Switches the fullscreen display on. Sets fullScreenElement
 * visibility to visible and enlarges the test iframe to fullscreen.
 */
DisplayTest.prototype.switchDisplayOn = function() {
  this.display = true;
  this.fullScreenElement.className = "display-full-screen-show";
  window.test.setFullScreen(true);
};

/**
 * Switches the fullscreen display off. Sets fullScreenElement
 * visibility to hidden and restores the test iframe to normal.
 */
DisplayTest.prototype.switchDisplayOff = function() {
  this.display = false;
  this.fullScreenElement.className = "display-full-screen-hide";
  window.test.setFullScreen(false);
};
"""

_HTML_SCREENSAVER = """
    <div id="display-test-container">
      <center>
        <span id="text-screensaver-en" class="screensaver-font-size">
           FAILED<br \>Press anykey to exit
        </span>
        <br \>
        <span id="text-screensaver-zh" class="screensaver-font-size">
           FAILED<br \>按任意键退出
        </span>
      </center>
     </div>
"""

class Report(unittest.TestCase):
  """A factory test to report test status."""
  ARGS = [
      Arg('disable_input_on_fail', bool,
          ('Disable user input to pass/fail when the overall status is not '
           'PASSED'),
          default=False),
      Arg('pass_without_prompt', bool,
          'If all tests passed, pass this test without prompting',
          default=False, optional=True),
      Arg('bft_fixture', dict,
          ('BFT fixture arguments (see bft_fixture test).  If provided, then a '
           'red/green light is lit to indicate failure/success rather than '
           'showing the summary on-screen.  The test does not fail if unable '
           'to connect to the BFT fixture.'),
          optional=True),
      Arg('accessibility', bool,
          'Display bright red background when the overall status is not PASSED',
          default=False, optional=True),
      Arg('screensaver_wait_secs', int, 'Waiting time in seconds to turn on screensaver.',
          default=None, optional=True),
  ]

  def _SetFixtureStatusLight(self, all_pass):
    try:
      fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)
      fixture.SetStatusColor(
          fixture.StatusColor.GREEN
          if all_pass
          else fixture.StatusColor.RED)
      fixture.Disconnect()
    except bft_fixture.BFTFixtureException:
      logging.exception('Unable to set status color on BFT fixture')

  def setUp(self):
    self.ui = test_ui.UI(css=CSS)
    self.ui.AddEventHandler('onScreensaverOff', self.onScreensaverOff)
    self._task_finished = threading.Event()
    self._force_stop = threading.Event()
    self._screensaver_thread = threading.Thread(target=self.screensaveObserver,
      args=(self._task_finished, self._force_stop))

  def onScreensaverOff(self, event):
    self._force_stop.set()

  def screensaveObserver(self, task_finished, force_stop):
    self.ui.AppendCSS(_CSS_SCREENSAVER)
    self.ui.AppendHTML(_HTML_SCREENSAVER)
    self.ui.RunJS(_JS_SCREENSAVER)

    self.ui.CallJSFunction('setupDisplayTest')

    while True:
      # Now the screensaver is off, wait for 10 sec and then show screensaver
      end_time = time.time() + self.args.screensaver_wait_secs
      while end_time - time.time() >= 0:
        if task_finished.is_set():
          return
        time.sleep(1)

      self.ui.CallJSFunction('switchDisplayOnOff') # Turn on
      force_stop.clear()

      count = 0
      colors = ['red', 'green', 'blue', 'white']
      text_colors = ['green', 'blue', 'white', 'red']
      while not task_finished.is_set() and not force_stop.is_set():
        # Wait for the screensaverOff flag turn to be True,
        time.sleep(1)
        count = (count + 1) % len(colors)
        self.ui.CallJSFunction('changeBackgroundColor', colors[count],
          text_colors[count])

      # Now the screensaver is off again
      self.ui.CallJSFunction('switchDisplayOnOff') # Turn off

  def runTest(self):
    test_list = self.test_info.ReadTestList()
    test = test_list.lookup_path(self.test_info.path)
    states = factory.get_state_instance().get_test_states()

    ui = self.ui

    statuses = []

    table = []
    for t in test.parent.subtests:
      if t == test:
        break

      state = states.get(t.path)

      table.append('<tr class="test-status-%s"><th>%s</th><td>%s</td></tr>'
                   % (state.status.replace('_', '-'),
                      test_ui.MakeTestLabel(t),
                      test_ui.MakeStatusLabel(state.status)))
      statuses.append(state.status)

    overall_status = factory.overall_status(statuses)
    all_pass = overall_status in (factory.TestState.PASSED,
                                  factory.TestState.FAILED_AND_WAIVED)

    board = system.GetBoard()
    if all_pass:
      board.OnSummaryGood()
    else:
      board.OnSummaryBad()
    """factory.get_state_instance().UpdateStatus(all_pass) will call
    UpdateStatus in goofy_rpc.py, and notify ui to update the color of
    dut's tab.
    """
    factory.get_state_instance().UpdateStatus(all_pass)

    if self.args.bft_fixture:
      self._SetFixtureStatusLight(all_pass)

    if all_pass and self.args.pass_without_prompt:
      return

    html = [
        '<div class="test-vcenter-outer"><div class="test-vcenter-inner">',
        test_ui.MakeLabel('Test Status for %s:' % test.parent.path,
                          u'%s 测试结果列表：' % test.parent.path),
        '<div class="test-status-%s" style="font-size: 300%%">%s</div>' % (
            overall_status, test_ui.MakeStatusLabel(overall_status)),
        '<table>'] + table + ['</table>']
    if not self.args.disable_input_on_fail or all_pass:
      html = html + ['<a onclick="onclick:window.test.pass()" href="#">',
                     test_ui.MakeLabel('Click or press SPACE to continue',
                                       u'点击或按空白键继续'),
                     '</a>']
    else:
      html = html + [test_ui.MakeLabel(
          'Unable to proceed, since some previous tests have not passed.',
          u'之前所有的测试必须通过才能通过此项目')]
    html = html + ['</div></div>']

    if self.args.accessibility and not all_pass:
      html = ['<div class="test-vcenter-accessibility">'] + html + ['</div>']

    if not self.args.disable_input_on_fail:
      ui.EnablePassFailKeys()
    # If disable_input_on_fail is True, and overall status is PASSED, user
    # can only pass the test.
    elif all_pass:
      ui.BindStandardKeys(bind_fail_keys=False)

    ui.SetHTML(''.join(html))
    logging.info('starting ui.Run with overall_status %r', overall_status)

    self._task_finished.clear()
    if self.args.screensaver_wait_secs is not None:
      self._screensaver_thread.start()

    ui.Run()
    self._task_finished.set()
    if self.args.screensaver_wait_secs is not None:
      self._screensaver_thread.join()
