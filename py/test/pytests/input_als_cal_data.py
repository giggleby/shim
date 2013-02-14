# -*- mode: python; coding: utf-8 -*-
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import unittest

from cros.factory.test import factory
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test import utils
from cros.factory.test.args import Arg
from cros.factory.utils.process_utils import Spawn

_EVENT_PROMPT_INPUT = 'event_prompt_input'
_INPUT_EVENT = 'input_event'
_JS_INPUT_FOCUS = '''
    var element = document.getElementById("input_value");
    element.focus();
    element.select();
'''

class InputAlsCalData(unittest.TestCase):
  """Update ALS calibration data 'als_cal_data' in the RO_VPD

  Manual entry if there is no shopfloor server.
  Uses an 'als' AUX table to find data if there is a shopfloor server.

  Example aux_als.csv:

  id,als_cal_data
  1011276300001,14
  3060956300013,4

  """

  ARGS = [
    Arg('min_value', int, 'Min value for ALS calibration value.', default=0),
    Arg('max_value', int, 'Max value for ALS calibration value.', default=25),
  ]

  def SetError(self, label_en, label_zh=None):
    logging.info('Input error: %r', label_en)
    self.ui.SetHTML(test_ui.MakeLabel(label_en, label_zh), id='input_error')

  def WriteALSCalData(self, als_cal_data):
    WRITING_ALS_LABEL = (lambda als:
        test_ui.MakeLabel('Writing ALS calibration value: %d' % als,
                          '写ALS值: %d' % als, 'als-font-size'))
    WRITING_ALS_CSS = '.als-font-size {font-size: 2em;}'

    try:
      als_cal_data = int(als_cal_data)
      assert als_cal_data >= self.args.min_value
      assert als_cal_data <= self.args.max_value
      if als_cal_data != self._als_cal_data:
        factory.console.info('Writing als_cal_data = %d', als_cal_data)
        self.template.SetState(WRITING_ALS_LABEL(als_cal_data))
        self.ui.AppendCSS(WRITING_ALS_CSS)
        Spawn(['vpd', '-i', 'RO_VPD', '-s', 'als_cal_data=%d' % als_cal_data],
              check_call=True, log=True)
    except ValueError:
      return self.SetError('Invalid data format', u'资料格式错误')
    except AssertionError:
      return self.SetError('Invalid number', u'无效的数字')
    except:  # pylint: disable=W0702
      logging.exception('Writing als_cal_data failed.')
      return self.SetError(utils.FormatExceptionOnly())
    self.ui.Pass()

  def ShowSerialNumberPrompt(self):
    self.template.SetState(
        test_ui.MakeLabel(
            'Enter display subassembly barcode and press ENTER.',
            u'TRANSLATE: Enter display subassembly bardcode and press Enter.') +
            '<br><input id="input_value" type="input">'
            '<br><p id="input_error" class="test-error">')
    self.ui.BindKeyJS(
        '\r',
        'window.test.sendTestEvent('
        '  "%s", document.getElementById("input_value").value)' %
        _INPUT_EVENT)
    self.ui.AddEventHandler(_INPUT_EVENT, self.HandleSerialNumberInput)
    self.ui.RunJS(_JS_INPUT_FOCUS)

  def HandleSerialNumberInput(self, event):
    self.ui.RunJS(_JS_INPUT_FOCUS)
    display_serial = event.data.strip()
    logging.debug('Display subassembly serial number: %s', display_serial)
    if not display_serial:
      return self.SetError('No input', u'未输入')
    try:
      aux_data = shopfloor.get_aux_data('als', display_serial)
    except shopfloor.ServerFault as e:
      return self.SetError('Shopfloor server error: %s' %
                           test_ui.Escape(e.__str__()))
    als_cal_data = aux_data['als_cal_data']
    self.WriteALSCalData(als_cal_data)

  def ShowManualInputPrompt(self):
    self.template.SetState(
        test_ui.MakeLabel(
            'Please input ALS calibration value and press ENTER.',
            u'请输入 ALS 校正资料後按下 ENTER') + '<br>' +
        '<input id="input_value" type="input" value="%d">' %
        self._als_cal_data + '<br><p id="input_error" class="test-error">')
    self.ui.AddEventHandler(_INPUT_EVENT, self.HandleManualInput)
    self.ui.BindKeyJS(
        '\r',
        'window.test.sendTestEvent('
        '  "%s", document.getElementById("input_value").value)' %
        _INPUT_EVENT)
    self.ui.AddEventHandler('input_value', self.HandleManualInput)
    self.ui.RunJS(_JS_INPUT_FOCUS)

  def HandleManualInput(self, event):
    self.ui.RunJS(_JS_INPUT_FOCUS)
    als_cal_data = event.data.strip()
    logging.debug('Input value: %s', als_cal_data)
    if not als_cal_data:
      return self.SetError('No input', u'未输入')
    self.WriteALSCalData(als_cal_data)

  def ShowYesNoPrompt(self, prompt, input_handler):
    KEY_PROMPT = "Push a button or type 'y' or 'n'."
    YES_NO_PROMPT_HTML = '''
      <input type="button" value="Yes"
          onclick="window.test.sendTestEvent('event_prompt_input', this.value)"
          style="font-size:2em; width:100px; height:50px">
      <input type="button" value="No"
          onclick="window.test.sendTestEvent('event_prompt_input', this.value)"
          style="font-size:2em; width:100px; height:50px">
      <br><br>
    '''
    YES_NO_PROMPT_CLASS = 'prompt-font-size'
    YES_NO_PROMPT_CSS = '.%s {font-size: 2em;}' % YES_NO_PROMPT_CLASS

    self.ui.AppendCSS(YES_NO_PROMPT_CSS)
    self.template.SetState(
        test_ui.MakeLabel(prompt, prompt, YES_NO_PROMPT_CLASS) + '<BR><BR>' +
        YES_NO_PROMPT_HTML + test_ui.MakeLabel(KEY_PROMPT, KEY_PROMPT))
    self.ui.BindKeyJS('Y', 'window.test.sendTestEvent("%s", "Yes")' %
                      _EVENT_PROMPT_INPUT)
    self.ui.BindKeyJS('N', 'window.test.sendTestEvent("%s", "No")' %
                      _EVENT_PROMPT_INPUT)
    self.ui.AddEventHandler(_EVENT_PROMPT_INPUT, input_handler)

  def HandleYesNoInput(self, event):
    #TODO(dparker): Find a cleaner way of removing key bindings.
    self.ui.BindKeyJS('Y', '')
    self.ui.BindKeyJS('N', '')
    reply = event.data.strip()
    if reply == "No":
      self.ui.Pass()
      return
    if shopfloor.is_enabled():
      self.ShowSerialNumberPrompt()
    else:
      self.ShowManualInputPrompt()

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self._als_cal_data = int(Spawn(
        ['vpd', '-i', 'RO_VPD', '-g', 'als_cal_data'],
        check_output=True).stdout_data)
    self.template.SetTitle(test_ui.MakeLabel('ALS Calibration Value',
                                             u'ALS Calibration Value'))

  def runTest(self):
    self.ShowYesNoPrompt('Was the display replaced?', self.HandleYesNoInput)
    self.ui.Run()
