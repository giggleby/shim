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
from cros.factory.utils.process_utils import Spawn, SpawnOutput

_INPUT_EVENT = 'input_event'
_JS_INPUT_FOCUS = '''
    var element = document.getElementById("input_value");
    element.focus();
    element.select();
'''

class InputAlsCalDataTest(unittest.TestCase):
  """Update Ambient Light Sensor (ALS) calibration data in the firmware RO_VPD.

  Manual entry if there is no shopfloor server.
  Uses AUX tables to find data if there is a shopfloor server.

  If the display was replaced the operator is prompted to enter the display
  subassembly serial number. The aux_als_fixture.csv file maps the display
  serial numbers to the original fixture ALS calibration values.

  Example aux_als_fixture.csv:

  id,als_cal_data
  1011276300001,14
  3060956300013,4

  If the MLB was replaced and the ALS calibration value could not be retrieved
  from the original board, the aux_als_fatp.csv file is used to lookup the
  original fatp ALS calibration value for the device's serial number.

  Example aux_als_fatp.csv:

  id,als_cal_data
  2C143027093000014,6
  2C153027931500035,8

  """

  ARGS = [
    Arg('min_value', int, 'Min value for ALS calibration value.', default=0),
    Arg('max_value', int, 'Max value for ALS calibration value.', default=25),
    Arg('default_value', int, 'Default ALS calibration value.', default=6),
  ]

  def _ShowError(self, label_en, label_zh):
    """Utility function for displaying an error message.

    Args:
      label_en: English message to display.
      label_zh: Chinese message to display.
    """
    logging.info('Input error: %r', label_en)
    self.ui.SetHTML(test_ui.MakeLabel(label_en, label_zh), id='input_error')

  def _WriteALSCalData(self, als_cal_data, message=None):
    """Write the ALS calibration value to the VPD (firmware).

    If the write succeeds, the test will be marked as passed.
    Displays an error message to the user if the als_cal_data value
    is invalid or there is an error while writing to the VPD.

    Args:
      als_cal_data: Int or string with the value to write.
      message: (optional) Tuple with an extra English then Chinese message
               to display to the user while writing to the VPD.
    """
    WRITING_ALS_LABEL = (lambda als:
        test_ui.MakeLabel('Writing ALS calibration value: %d' % als,
                          '写ALS值: %d' % als, 'als-font-size'))
    WRITING_ALS_CSS = '.als-font-size {font-size: 2em;}'

    if message is not None:
      message_label = test_ui.MakeLabel(*message)
    else:
      message_label = None

    try:
      als_cal_data = int(als_cal_data)
      assert als_cal_data >= self.args.min_value
      assert als_cal_data <= self.args.max_value
      if als_cal_data != self.als_cal_data:
        factory.console.info('Writing als_cal_data = %d', als_cal_data)
        self.template.SetState(WRITING_ALS_LABEL(als_cal_data) +
                               '<br><p id="message" style="color: #D00;">')
        self.ui.AppendCSS(WRITING_ALS_CSS)
        if message_label:
          self.ui.SetHTML(message_label, id='message')

        Spawn(['vpd', '-i', 'RO_VPD', '-s', 'als_cal_data=%d' % als_cal_data],
              check_call=True, log=True)

    except ValueError:
      return self._ShowError('Invalid data format', u'资料格式错误')
    except AssertionError:
      return self._ShowError('Invalid number', u'无效的数字')
    except:  # pylint: disable=W0702
      logging.exception('Writing als_cal_data failed.')
      return self._ShowError(utils.FormatExceptionOnly(),
                             utils.FormatExceptionOnly())
    self.ui.Pass()

  def _FetchAuxDataCalibrationValue(self, table_name, serial_number):
    """Look up the ALS calibration data in a shopfloor AUX data table.

    The ALS calibration data is assumed to be labeled as 'als_cal_data'
    in the AUX table. Displays an error messge to the user if the
    shopfloor server returns an error.

    Args:
      table_name: String. Name of the shopfloor aux table to use.
      serial_number: String. Id of the value to retrieve.

    Returns:
      The string value from the shopfloor server or None if the value is
      not found or there is an error.
    """
    try:
      aux_data = shopfloor.get_aux_data(table_name, serial_number)
    except shopfloor.ServerFault as e:
      self._ShowError(
          'Shopfloor server error: %s' % test_ui.Escape(e.__str__()),
          u'服务器错误: %s' % test_ui.Escape(e.__str__()))
      return None
    return aux_data['als_cal_data']

  def _FetchROVpdValue(self, name):
    vpd_value = SpawnOutput(['vpd', '-i', 'RO_VPD', '-g', name],
                   check_output=True)
    if len(vpd_value) == 0:
      logging.info('RO_VPD does not contain a value for %s.', name)
      return None
    return vpd_value

  def _Fail(self, message_en, message_zh):

    JS_PRESS_SPACE_TO_FAIL = '''
        function pressSpaceToFail() {
          window.addEventListener(
            "keypress",
            function(event) {
              if (event.keyCode == " ".charCodeAt(0)) {
                window.test.fail();
              }
            });
          window.focus();
        }'''
    FAIL_LABEL = test_ui.MakeLabel(message_en, message_zh, 'fail-font')
    FAIL_CSS = '.fail-font {font-size: 1.5em; color: #D00}'
    SPACE_TO_CONTINUE_LABEL = test_ui.MakeLabel('Press SPACE to continue.',
                                                u'按空白键继续', 'prompt-font')
    SPACE_TO_CONTINUE_CSS = '.prompt-font {font-size: 1.5em}'
    self.ui.AppendCSS(FAIL_CSS)
    self.ui.AppendCSS(SPACE_TO_CONTINUE_CSS)
    self.template.SetState(FAIL_LABEL + '<br><br>' + SPACE_TO_CONTINUE_LABEL)
    self.ui.RunJS(JS_PRESS_SPACE_TO_FAIL)
    self.ui.CallJSFunction('pressSpaceToFail')

  def _WriteFATPCalibrationValue(self):
    """Fetch ALS value from the FATP shopfloor table and write it to the VPD.

    Triggers a test failure if there is no device serial number in the
    VPD to use to lookup the calibration value.
    """
    serial_number = self._FetchROVpdValue('serial_number')
    if serial_number is None:
      self._Fail('No serial number is in the VPD to lookup'
                 ' ALS calibration value.<br>Run the VPD test first.',
                 u'VPD 中找不到编号，无法查询 ALS 校准值<br>先进行 VPD 测试')
      return None

    als_cal_data = self._FetchAuxDataCalibrationValue('als_fatp', serial_number)
    if als_cal_data is None:
      MESSAGE_EN = ('No ALS calibration value available for %s.'
                    ' Using default value.' % serial_number)
      MESSAGE_ZH =  u'無法查詢到編號 %s 的 ALS 校準值<br>使用默认值。' % serial_number
      factory.console.info(MESSAGE_EN)
      self._WriteALSCalData(self.args.default_value,
                            message=(MESSAGE_EN, MESSAGE_ZH))
    else:
      self._WriteALSCalData(als_cal_data)

  def _HandleSerialNumberInput(self, event):
    """Write display subassembly calibration data to the VPD.

    If input is invalid an error is displayed back to the user.

    Args:
      event: factory.test.event.Event returned by UI framework.
             data property contains value entered by user.
    """
    self.ui.RunJS(_JS_INPUT_FOCUS)
    display_serial = event.data.strip()
    logging.debug('Display subassembly serial number: %s', display_serial)
    if not display_serial:
      return self._ShowError('No input', u'未输入')

    als_cal_data = self._FetchAuxDataCalibrationValue('als_fixture',
                                                      display_serial)
    if als_cal_data is None:
      factory.console.info('No ALS calibration value found for %s.',
                           display_serial)
    else:
      self._WriteALSCalData(als_cal_data)

  def _ShowDisplaySerialNumberPrompt(self):
    """Prompt the user to enter the serial number of the display."""

    self.template.SetState(
        test_ui.MakeLabel(
            'Enter display subassembly barcode and press ENTER.',
            u'输入显示组件的条码，然后按ENTER键') +
            '<br><input id="input_value" type="input">'
            '<br><p id="input_error" class="test-error">')
    self.ui.BindKeyJS(
        '\r',
        'window.test.sendTestEvent('
        '  "%s", document.getElementById("input_value").value)' %
        _INPUT_EVENT)
    self.ui.AddEventHandler(_INPUT_EVENT, self._HandleSerialNumberInput)
    self.ui.RunJS(_JS_INPUT_FOCUS)

  def _HandleManualInput(self, event):
    """Write manually entered ALS value to the VPD.

    If input is invalid an error is displayed back to the user.

    Args:
      event: factory.test.Event returned by UI framework.
             data property contains value entered by user.
    """
    self.ui.RunJS(_JS_INPUT_FOCUS)
    als_cal_data = event.data.strip()
    logging.debug('Input value: %s', als_cal_data)
    if not als_cal_data:
      return self._ShowError('No input', u'未输入')

    self._WriteALSCalData(als_cal_data)

  def _ShowManualInputPrompt(self):
    """Prompt the user to enter the ALS value manualy."""

    initial_value = self.als_cal_data or ''
    self.template.SetState(
        test_ui.MakeLabel(
            'Please input ALS calibration value and press ENTER.',
            u'请输入 ALS 校正资料後按下 ENTER') + '<br>' +
        '<input id="input_value" type="input" value="%s">' %
        initial_value + '<br><p id="input_error" class="test-error">')
    self.ui.AddEventHandler(_INPUT_EVENT, self._HandleManualInput)
    self.ui.BindKeyJS(
        '\r',
        'window.test.sendTestEvent('
        '  "%s", document.getElementById("input_value").value)' %
        _INPUT_EVENT)
    self.ui.AddEventHandler('input_value', self._HandleManualInput)
    self.ui.RunJS(_JS_INPUT_FOCUS)

  def _HandleDisplayReplacedInput(self, event):
    """Decides how to update the VPD based on whether the display was replaced.

    Args:
      event: factory.test.Event returned by UI framework.
             data property contains either 'Yes' or 'No' reponse.
    """
    #TODO(dparker): Find a cleaner way of removing key bindings.
    self.ui.BindKeyJS('Y', '')
    self.ui.BindKeyJS('N', '')
    reply = event.data.strip()
    if reply == "No" and self.als_cal_data is not None:
      self.ui.Pass()
      return None

    if reply == "No" and self.als_cal_data is None:
      if shopfloor.is_enabled():
        self._WriteFATPCalibrationValue()
      else:
        MESSAGE_EN = 'No ALS calibration value available. Using default value.'
        MESSAGE_ZH = u'ALS校准值丢失。使用默认值。'
        logging.info(MESSAGE_EN)
        self._WriteALSCalData(self.args.default_value,
                              message=(MESSAGE_EN, MESSAGE_ZH))

    if reply == "Yes":
      if shopfloor.is_enabled():
        self._ShowDisplaySerialNumberPrompt()
      else:
        self._ShowManualInputPrompt()

  def _ShowYesNoPrompt(self, question_en, question_zh, input_handler):
    """Display a question to the user and wait for a yes/no response.

    Args:
      question_en: Question to ask in English.
      question_zh: Question to ask in Chinese.
      input_handler: Callback to send reponse event to.
    """
    PRESS_KEY_EN = "Push a button or type 'y' or 'n'."
    PRESS_KEY_ZH = u"按下一个按钮或输入'Y'或'N'。"
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
    EVENT_PROMPT_INPUT = 'event_prompt_input'

    self.ui.AppendCSS(YES_NO_PROMPT_CSS)
    self.template.SetState(
        test_ui.MakeLabel(question_en, question_zh, YES_NO_PROMPT_CLASS) +
        '<br><br>' + YES_NO_PROMPT_HTML +
        test_ui.MakeLabel(PRESS_KEY_EN, PRESS_KEY_ZH))
    self.ui.BindKeyJS('Y', 'window.test.sendTestEvent("%s", "Yes")' %
                      EVENT_PROMPT_INPUT)
    self.ui.BindKeyJS('N', 'window.test.sendTestEvent("%s", "No")' %
                      EVENT_PROMPT_INPUT)
    self.ui.AddEventHandler(EVENT_PROMPT_INPUT, input_handler)

  def __init__(self, *args, **kwargs):
    super(InputAlsCalDataTest, self).__init__(*args, **kwargs)
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.als_cal_data = self._FetchROVpdValue('als_cal_data')
    if self.als_cal_data is not None and self.als_cal_data.isdigit():
      self.als_cal_data = int(self.als_cal_data)

    self.template.SetTitle(
        test_ui.MakeLabel('ALS Calibration Value',
                          u'ALS校準值'))

  def runTest(self):
    """Entry point for starting test execution."""
    self._ShowYesNoPrompt('Was the display replaced?',
                          u'屏幕有无更换？',
                          self._HandleDisplayReplacedInput)
    self.ui.Run()
