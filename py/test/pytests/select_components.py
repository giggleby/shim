# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# DESCRIPTION :
# This is a test for selecting non-probable components and update the selected
# results in device data.

import factory_common # pylint: disable=W0611
import logging
import os
import unittest

from cros.factory.hwid import common
from cros.factory.hwid import database
from cros.factory.hwid import hwid
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import factory
from cros.factory.test.args import Arg
from cros.factory.test.ui_templates import OneSection, SelectBox, Table

_MESSAGE_SELECT = test_ui.MakeLabel('Select Components:', u'选择元件：',
                                    'msg-font-size')

_TEST_DEFAULT_CSS = '.msg-font-size {font-size: 2em;}'
_SELECT_BOX_STYLE = ('font-size: 1.5em; background-color: white; '
                     'min-width: 150px;')

_SELECT_BOX_ID = lambda x: 'Select-' + x
_SELECTION_PER_PAGE = 10
_EVENT_SUBTYPE_SELECT_COMP = 'Select-Components'

_TEST_TITLE = test_ui.MakeLabel('Select Components', u'选择元件')


class SelectComponentTest(unittest.TestCase):
  ARGS = [
    Arg('comps', dict,
        """A dict from components in hwid database to
        (device_data_field, choices). If choices is not None, user selects
        value from choices. If it is None, user selects valid component
        from hwid database. That value will be stored as device_data_field
        in device_data.
        E.g. comps={"cpu": ("component.cpu",
                            ["choice_1", "choice_2])}""",
        optional=False),
  ]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    self.ui.AppendCSS(_TEST_DEFAULT_CSS)
    self.template.SetTitle(_TEST_TITLE)
    self.device_data = shopfloor.GetDeviceData()
    # The component names.
    self.fields = self.args.comps.keys()
    self.component_device_data = dict((k, self.args.comps[k][0])
        for k in self.fields)
    self.component_choices = dict((k, self.args.comps[k][1])
        for k in self.fields)

  def SelectComponent(self, event):
    """Handle component selection RPC call from Javascript.

    The passed in 'event' is a list of tuples, containing selected component
    for each field. For example,
      [(0, 'inpaq'), (1, 'gce'), (2, 'us_darfon')]
    The first item of each tuple is the index of the field as specified in
    the test argument. The second item is the selected component.
    """
    logging.info('Component selection: %r', event.data)
    for comp in event.data:
      key_name = self.component_device_data[self.fields[comp[0]]]
      self.device_data[key_name] = comp[1]
      factory.console.info('Update device data %r: %r' % (key_name, comp[1]))
    shopfloor.UpdateDeviceData(self.device_data)

  def runTest(self):
    table = Table(element_id=None, rows=2, cols=len(self.fields))
    db = database.Database.LoadFile(os.path.join(
        common.DEFAULT_HWID_DATA_PATH, common.ProbeBoard().upper()))
    comp_values = hwid.ListComponents(db, self.fields)
    # Updates comp_values with choices from test list.
    for field in self.fields:
      if self.component_choices[field] is not None:
        comp_values[field] = self.component_choices[field]

    for field_index, field in enumerate(self.fields):
      self.ui.RunJS('addComponentField("%s");' % field)

      table.SetContent(0, field_index, field)
      select_box = SelectBox(_SELECT_BOX_ID(field), _SELECTION_PER_PAGE,
                             _SELECT_BOX_STYLE)
      selected = None
      for index, comp_value in enumerate(comp_values[field]):
        select_box.InsertOption(comp_value, comp_value)
        # Let user choose component even if device data field is not present
        # in device_data.
        if comp_value == self.device_data.get(
            self.component_device_data[field], None):
          selected = index
      if selected is not None:
        select_box.SetSelectedIndex(selected)
      table.SetContent(1, field_index, select_box.GenerateHTML())
    html = [_MESSAGE_SELECT, '<center>', table.GenerateHTML(), '</center>']

    self.ui.AddEventHandler(_EVENT_SUBTYPE_SELECT_COMP, self.SelectComponent)

    html.append('<input type="button" value="OK" '
                'onClick="SelectComponents();"/>')
    self.ui.BindKeyJS(13, "SelectComponents();")

    self.template.SetState(''.join(html))
    self.ui.Run()
    return
