# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# DESCRIPTION :
# This is a test to verify HWID during factory flow. The test supports three
# ways of fetching/probing HWID:
# 1) Manually select by operator.
# 2) Fetch from shop floor server.
# 3) Auto probe for best match HWID.
#
# To use the auto-probing feature, you have to specify some arguments to the
# test. Please refer to ARGS below for detailed explanation.

import factory_common # pylint: disable=W0611
import re
import unittest

from cros.factory.hwdb.hwid_tool import HWID_RE
from cros.factory.test import factory
from cros.factory.test import gooftools
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg
from cros.factory.test.factory_task import FactoryTask, FactoryTaskManager
from cros.factory.utils.process_utils import Spawn, SpawnOutput

_MESSAGE_FETCH_FROM_SHOP_FLOOR = test_ui.MakeLabel(
    'Fetching HWID from shop floor server...',
    u'从 Shop Floor 服务器抓取 HWID 中...',
    'hwid-font-size')
_MESSAGE_AUTO_PROBE_HWID = test_ui.MakeLabel('Auto probing HWID...',
                                             u'自动侦测 HWID 中...',
                                             'hwid-font-size')
_MESSAGE_WRITING = (lambda hwid:
    test_ui.MakeLabel('Writing HWID: %s' % hwid, u'写入 HWID: %s' % hwid,
                      'hwid-font-size'))
_MESSAGE_CHOOSE_HWID = test_ui.MakeLabel('Select HWID:</br></br>',
                                         u'选择 HWID：</br></br>',
                                         'hwid-font-size')
_MESSAGE_HOW_TO_SELECT = test_ui.MakeLabel('</br></br>Select with Enter key',
                                           u'</br></br>使用 Enter 键选择',
                                           'hwid-font-size')
_MESSAGE_CURRENT_VALUE = lambda hwid: '%s (Current Value)' % hwid

_TEST_DEFAULT_CSS = '.hwid-font-size {font-size: 2em;}'
_SELECT_BOX_STYLE = 'font-size: 1.5em; background-color: white;'

_SELECT_BOX_ID = 'hwid_select'
_SELECTION_PER_PAGE = 10
_EVENT_SUBTYPE_HWID_SELECT = 'HWID-Select'
_JS_HWID_SELECT = '''
    ele = document.getElementById("%s");
    idx = ele.selectedIndex;
    window.test.sendTestEvent("%s", ele.options[idx].value)
''' % (_SELECT_BOX_ID, _EVENT_SUBTYPE_HWID_SELECT)

_VARIANT_SELECT_BOX_ID = 'variant_select'
_EVENT_SUBTYPE_VARIANT_SELECT = 'Variant-Select'
_JS_VARIANT_SELECT = '''
    ele = document.getElementById("%s");
    idx = ele.selectedIndex;
    window.test.sendTestEvent("%s", ele.options[idx].value)
''' % (_VARIANT_SELECT_BOX_ID, _EVENT_SUBTYPE_VARIANT_SELECT)

_ERR_HWID_NOT_FOUND = test_ui.MakeLabel('Cannot find matched HWID.',
                                        u'无法找到匹配的 HWID。',
                                        'hwid-font-size test-error')

_TEST_TITLE = test_ui.MakeLabel('HWID Test', u'HWID测试')


class WriteHWIDTask(FactoryTask):
  '''Writes HWID using gooftool.'''
  def __init__(self, test):
    super(WriteHWIDTask, self).__init__()
    self.test = test

  def Run(self):
    hwid = self.test.hwid
    if not hwid:
      raise ValueError("Invalid empty HWID")

    self.test.template.SetState(_MESSAGE_WRITING(hwid))
    # TODO(hungte) Support partial matching by gooftools or hwid_tool.
    # When the input is not a complete HWID (i.e., BOM-VARIANT pair), select
    # and derive the complete ID from active HWIDs in current database.
    # Ex: input="BLUE A" => matched to "MARIO BLUE A-B 6868".
    current_hwid = Spawn(['crossystem', 'hwid'],
                         check_output=True).stdout_data.strip()
    # To save time, only do HWID write if the input HWID is different from
    # the one already on the system.
    if hwid != current_hwid:
      gooftools.run("gooftool write_hwid '%s'" % hwid)
    else:
      factory.console.info("Probed HWID is the same as the one already on "
                           "the machine. Skip write.")
    self.Stop()


class ShopFloorHWIDTask(FactoryTask):
  '''Fetchs HWID from shop floor server.'''
  def __init__(self, test):
    super(ShopFloorHWIDTask, self).__init__()
    self.test = test

  def Run(self):
    shopfloor.update_local_hwid_data()
    self.test.template.SetState(_MESSAGE_FETCH_FROM_SHOP_FLOOR)
    self.test.hwid = shopfloor.get_hwid()
    self.Stop()


class AutoProbeHWIDTask(FactoryTask):
  '''Automatically probes matched HWID(s) using gooftool.'''
  def __init__(self, test):
    super(AutoProbeHWIDTask, self).__init__()
    self.test = test

  def Run(self):
    shopfloor.update_local_hwid_data()
    self.test.template.SetState(_MESSAGE_AUTO_PROBE_HWID)
    gooftool_cmd = 'gooftool best_match_hwids'
    if self.test.args.missing:
      gooftool_cmd += ' --missing ' + ' '.join(self.test.args.missing)
    if self.test.args.comps:
      gooftool_cmd += ' --comps ' + ' '.join(self.test.args.comps)
    if self.test.args.variant:
      gooftool_cmd += ' --variant %s' % self.test.args.variant
    if self.test.args.status:
      gooftool_cmd += ' --status %s' % self.test.args.status
    (stdout, _, _) = gooftools.run(gooftool_cmd)
    matched_hwids = re.findall(r"^MATCHING HWID: (.+)$", stdout,
                               re.MULTILINE)

    if matched_hwids:
      self.test.hwid_list = []
      # Use hwid_tool.HWID_RE to check the format of probed HWIDs
      for i in xrange(0, len(matched_hwids)):
        match = HWID_RE.search(matched_hwids[i]).group(0)
        if match:
          self.test.hwid_list.append(match)
      factory.console.info("Found matched HWIDs: %s" % self.test.hwid_list)
    else:
      self.test.template.SetState(_ERR_HWID_NOT_FOUND)
      factory.console.info("Cannot find matched HWID.")
    self.Stop()


class FilterVariantTask(FactoryTask):
  '''Filter HWIDs by variant by running automated and interactive tests.

  Reads a list of rules from test.variant_filter and removes entries from
  test.hwid_list that that do not match. The order of the rules must match
  the order the variants appear in the HWID.

  The format of variant_filter is a list of tuples (filter_name, filter_args).
  The filter_name specifies what type check to perform. filter_args is a dict
  that maps variant character values to properties of the device that are either
  probed or manually selected.
  '''

  def __init__(self, test):
    super(FilterVariantTask, self).__init__()
    self.FILTER_MAP = {
        'keyboard': self._IdentifyKeyboard,
        'motherboard': self._IdentifyMotherboard,
        'memory': self._IdentifyMemory
    }
    self.test = test
    self.filter_rules = test.args.variant_filter
    self.variant = ''

  def Run(self):
    self._RunNextFilter()

  def _FilterByVariant(self):
    '''Filter test.hwid_list to HWIDs matching self.variant.'''

    filtered_hwids = []
    variant_re = re.compile(r'^LINK [\w]+ (?P<variant>[\w ]+)-\w [0-9]{4}$')
    for hwid in self.test.hwid_list:
      variant_match = variant_re.match(hwid)
      if self.variant == variant_match.group('variant'):
        filtered_hwids.append(hwid)
    factory.console.info('Matching HWIDs: %s', filtered_hwids)
    self.test.hwid_list = filtered_hwids

  def _RunNextFilter(self):
    '''Run the next variant filter rule.'''

    if len(self.filter_rules) == 0:
      self._FilterByVariant()
      self.Stop()
    filter_name, filter_args = self.filter_rules.pop(0)
    self.FILTER_MAP[filter_name](filter_args)

  def _IdentifyKeyboard(self, keyboard_layout_map):
    '''Automatically probe the keyboard type.

    Uses the keyboard_layout set in the VPD.
    Args:
      keyboard_layout_map: Dict. Map of keyboard layouts to variant values.
                  Example: {'xkb:us::eng': 'A', 'xkb:gb:extd:eng': 'B'}
    Returns:
      None but adds an variant character to self.variant
    '''
    vpd_keyboard_layout = SpawnOutput(['vpd', '-g', 'keyboard_layout'])
    keyboard_variant = keyboard_layout_map[vpd_keyboard_layout]
    self.variant += keyboard_variant
    factory.console.info('Selected %s for keyboard variant.', keyboard_variant)
    self._RunNextFilter()

  def _IdentifyMemory(self, memory_map):
    '''Automatically probe the memory vendor.

    Args:
      memory_map: Dict. Map of memory vendors to variant values.
                  Example: {'Hynix': 'A'}
    Returns:
      None but adds an variant charater to self.variant
    '''
    mosys_raw_output = SpawnOutput(['mosys', 'memory', 'spd', 'print', 'id'])
    spd_vendor_re = re.compile(
        r'^\d \| \d+-\d+: (?P<vendor>[\w ]+) \| \d+ \| [\w-]+ $')
    # Only check the first bank. Assuming vendors are uniform across all banks.
    spd_vendor_match = spd_vendor_re.match(mosys_raw_output.splitlines()[0])
    spd_vendor = spd_vendor_match.group('vendor')
    memory_variant = memory_map[spd_vendor]
    self.variant += memory_variant
    factory.console.info('Selected %s for memory variant.', memory_variant)
    self._RunNextFilter()

  def _IdentifyMotherboardCallback(self, event):
    '''Callback from _IdentifyMotherboard.

    Args:
      event: factory.test.Event returned by UI framework.
             data property contains variant selected by operator.
    '''
    self.variant += event.data
    factory.console.info('Selected %s for motherboard variant.', event.data)
    self._RunNextFilter()

  def _IdentifyMotherboard(self, option_map):
    '''Prompt the operator to select the motherboard vendor.

    Args:
      option_map: Dict. Map of motherboard vendors to variant values.
                  Example: {'Chintech': 'D'}
    Returns:
      None but adds an variant character to self.variant
    '''
    PROMPT_EN = 'Select Motherboard Vendor:<br/><br/>'
    PROMPT_ZH = u'选择主板供应商:<br/><br/>'
    prompt_label = test_ui.MakeLabel(PROMPT_EN, PROMPT_ZH,
                                     'hwid-font-size')
    self.test.template.SetState(prompt_label)
    select_list = ['<select size=%d style="%s" id="%s">' %
                   (_SELECTION_PER_PAGE, _SELECT_BOX_STYLE,
                    _VARIANT_SELECT_BOX_ID)]
    for name, value in option_map.iteritems():
      select_list.append('<option value="%s">%s</option>' % (value, name))
    select_list.append('</select>')
    self.test.template.SetState(select_list, append=True)
    self.test.template.SetState(_MESSAGE_HOW_TO_SELECT, append=True)
    self.test.ui.BindKeyJS(13, _JS_VARIANT_SELECT)
    self.test.ui.AddEventHandler(_EVENT_SUBTYPE_VARIANT_SELECT,
                                 self._IdentifyMotherboardCallback)
    self.test.ui.RunJS('document.getElementById("%s").selectedIndex=0' %
                       _VARIANT_SELECT_BOX_ID)
    self.test.ui.RunJS('document.getElementById("%s").focus()' %
                       _VARIANT_SELECT_BOX_ID)


class SelectHWIDTask(FactoryTask):
  '''Shows a list of HWIDs on UI and let operator choose a HWID from the it.'''

  def __init__(self, test):
    super(SelectHWIDTask, self).__init__()
    self.test = test
    self.pages = 0
    self.page_index = 0
    self.hwid_list = None

  def BuildHWIDList(self):
    current_hwid = self.test.hwid or Spawn(['crossystem', 'hwid'],
                         check_output=True).stdout_data.strip()

    if self.test.hwid_list:
      known_list = self.test.hwid_list
    else:
      (stdout, _, result) = gooftools.run("hwid_tool hwid_list",
                                          ignore_status=True)
      known_list = stdout.splitlines()
      if (not known_list) or (result != 0):
        factory.console.info('Warning: No valid HWID database in system.')
        known_list = []

    # Build a list with elements in (hwid_value, display_text).
    # The first element is "current value".
    hwids = [(current_hwid, _MESSAGE_CURRENT_VALUE(current_hwid))]
    hwids += [(hwid, hwid) for hwid in known_list]
    return hwids

  def SetHWID(self, event):
    # TODO(tammo) Use hwid_tool or probe to quick probe if selected HWID
    # matches current system, by checking non-firmware components.
    self.test.hwid = event.data
    self.Stop()

  def RenderPage(self):
    self.test.template.SetState(_MESSAGE_CHOOSE_HWID)
    select_list = ['<select size=%d style="%s" id="%s">' %
                   (_SELECTION_PER_PAGE, _SELECT_BOX_STYLE, _SELECT_BOX_ID)]
    for data in self.hwid_list:
      select_list.append('<option value="%s">%s</option>' % (data[0], data[1]))
    select_list.append('</select>')
    self.test.template.SetState(select_list, append=True)
    self.test.template.SetState(_MESSAGE_HOW_TO_SELECT, append=True)
    self.test.ui.BindKeyJS(13, _JS_HWID_SELECT)
    self.test.ui.AddEventHandler(_EVENT_SUBTYPE_HWID_SELECT, self.SetHWID)
    self.test.ui.RunJS('document.getElementById("%s").selectedIndex=0' %
                       _SELECT_BOX_ID)
    self.test.ui.RunJS('document.getElementById("%s").focus()' % _SELECT_BOX_ID)

  def Run(self):
    self.hwid_list = self.BuildHWIDList()

    # Skip if auto_select is True and there is only one match.
    # hwid_list[0] is the current system HWID and hwid_list[1] is the
    # probed one.
    if len(self.hwid_list) == 2 and self.test.args.auto_select:
      self.test.hwid = self.hwid_list[1][1]
      self.Stop()

    self.RenderPage()


class HWIDTest(unittest.TestCase):
  ARGS = [
    Arg('override_hwid', (str, unicode),
        'An override HWID which is used during development.', default=None,
        optional=True),
    Arg('auto_probe', bool, 'Whether to enable HWID auto probe.', default=False,
        optional=True),
    Arg('auto_select', bool,
        'Whether to auto select HWID if there is only one match', default=True,
        optional=True),
    Arg('missing', list,
        'A list of missing components in the following format:'
        '["comp1", "comp2", ..]', default=None, optional=True),
    Arg('comps', list,
        'A list of known component canonicals to pass to gooftool in the'
        'following format: ["comp_canonical1", "comp_canonical2", ...]',
        default=None, optional=True),
    Arg('variant', (str, unicode),
        'A string indicating the variant code to pass to gooftool',
        default=None, optional=True),
    Arg('variant_filter', list,
        'A set of rules to filter HWIDs by variant', default=None,
        optional=True),
    Arg('status', (str, unicode),
        'A string indicating from what status of HWIDs should the program'
        'find possible match. (deprecated, eol, qualified, supported)',
        default='supported', optional=True)
  ]

  def __init__(self, *args, **kwargs):
    super(HWIDTest, self).__init__(*args, **kwargs)
    self.hwid = None
    self.hwid_list = None
    self.task_list = []
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS(_TEST_DEFAULT_CSS)
    self.template.SetTitle(_TEST_TITLE)

  def runTest(self):
    if self.args.override_hwid:
      self.hwid = self.args.override_hwid
    elif shopfloor.is_enabled() and not self.args.auto_probe:
      self.task_list.append(ShopFloorHWIDTask(self))
    else:
      if self.args.auto_probe:
        self.task_list.append(AutoProbeHWIDTask(self))

      if self.args.variant_filter:
        self.task_list.append(FilterVariantTask(self))

      self.task_list.append(SelectHWIDTask(self))

    self.task_list.append(WriteHWIDTask(self))
    FactoryTaskManager(self.ui, self.task_list).Run()
