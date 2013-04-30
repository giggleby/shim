# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# DESCRIPTION :
# This is a test that verifies only expected components are installed in the
# DUT.

import logging
import unittest

import factory_common # pylint: disable=W0611
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg
from cros.factory.test.factory_task import FactoryTask, FactoryTaskManager
from cros.factory.gooftool import Gooftool

_TEST_TITLE = test_ui.MakeLabel('Components Verification Test',
                                u'元件验证测试')
_MESSAGE_CHECKING_COMPONENTS = test_ui.MakeLabel(
    'Checking components...', u'元件验证中...', 'progress-message')

_MESSAGE_MATCHING_ANY_BOM = test_ui.MakeLabel(
    'Matching BOM from the list...', u'正在从列表匹配 BOM ...',
    'progress-message')

_MESSAGE_CHECKING_AUX_TABLE_COMPONENTS = test_ui.MakeLabel(
    'Checking components in auxiliary table...',
    u'辅助表元件验证中...', 'progress-message')

class CheckComponentsTask(FactoryTask):
  '''Checks the given components are in the components db.'''

  def __init__(self, test):
    super(CheckComponentsTask, self).__init__()
    self._test = test

  def Run(self):
    """Runs the test.

    The probing results will be stored in test.component_list.
    """

    self._test.template.SetState(_MESSAGE_CHECKING_COMPONENTS)
    try:
      result = self._test.gooftool.VerifyComponents(self._test.component_list)
    except ValueError, e:
      self.Fail(str(e))
      return

    logging.info("Probed components: %s", result)
    self._test.probed_results = result

    # extract all errors out
    error_msgs = []
    for class_result in result.values():
      for component_result in class_result:
        if component_result.error:
          error_msgs.append(component_result.error)
    if error_msgs:
      self.Fail("At least one component is invalid:\n%s" %
                '\n'.join(error_msgs))
    else:
      self.Pass()

class VerifyAnyBOMTask(FactoryTask):
  '''Verifies the given probed_results matches any of the given BOMs.'''

  def __init__(self, test, bom_whitelist):
    """Constructor.

    Args:
      test: The test itself which contains results from other tasks.
      bom_whitelist: The whitelist for BOMs that are allowed to match.
    """
    super(VerifyAnyBOMTask, self).__init__()
    self._test = test
    self._bom_whitelist = bom_whitelist

  def Run(self):
    """Verifies probed results against all listed BOMs.

    If a match is found for any of the BOMs, the test will pass
    """

    self._test.template.SetState(_MESSAGE_MATCHING_ANY_BOM)

    all_mismatches = {}  # tracks all mismatches for each BOM for debugging
    for bom in self._bom_whitelist:
      mismatches = self._test.gooftool.FindBOMMismatches(
          self._test.board, bom, self._test.probed_results)
      if not mismatches:
        logging.info("Components verified with BOM %r", bom)
        self.Pass()
        return
      else:
        all_mismatches[bom] = mismatches

    self.Fail("Probed components did not match any of listed BOM: %s" %
              all_mismatches)

class CheckAuxTableComponentsTask(FactoryTask):
  '''Verifies specific components based on BOMCode or MLBSerialNumber.'''

  def __init__(self, test, shopfloor_wrapper,
               aux_table_component_mapping, aux_field_component_list):
    """Constructor.

    Args:
      test: The test itself which contains results from other tasks.
      shopfloor_wrapper: A shopfloor wrapper for accessing the aux data.
      aux_table_component_mapping: The name of the aux lookup table.
        e.g.,'bom' (aux_bom.csv) for BOMCode.
             'mlb' (aux_mlb.csv) for MLBSerialNumber.
      aux_field_component_list: A list of specific components in
        aux_table to be verified.
    """
    super(CheckAuxTableComponentsTask, self).__init__()
    self._test = test
    self._shopfloor_wrapper = shopfloor_wrapper
    self._aux_table_component_mapping = aux_table_component_mapping
    self._aux_field_component_list = aux_field_component_list

  def Run(self):
    """Verifies some specific components are found in the machine.

    A list of specific components is lookup by
      shopfloor.get_selected_aux_data(aux_table_name) which returns
      a row based on previous invocation of
      shopfloor.select_aux_data(aux_table_name, id).
    For example, one might call: shopfloor.select_aux_data('bom','4619HT52L08').
    From then on, shopfloor.get_selected_aux_data('bom')
      will return the data from the 'bom' table corresponding to
      ID '4619HT52L08'.
    """

    self._test.template.SetState(_MESSAGE_CHECKING_AUX_TABLE_COMPONENTS)

    # Get the data of the row selected by previous invocation of
    #   select_aux_data(aux_table_component_mapping, id) when
    #   scan BOMCode or scan MLBSerialNumber.
    try:
      aux = self._shopfloor_wrapper.get_selected_aux_data(
                self._aux_table_component_mapping)
    except ValueError:
      self.Fail("Unable to obtain selected aux data for table %r." %
        self._aux_table_component_mapping)
      return

    for aux_field in self._aux_field_component_list:
      value = aux.get(aux_field)
      if value is None:
        self.Fail("Retrieved None value for field %r in aux table %r." %
                   (aux_field, self._aux_table_component_mapping))
        return

      if not self.VerifyComponentName(aux_field, value):
        self.Fail("Expected component %r of component_class %r not found." %
                  (value, aux_field))
        return

    logging.info("Verified AuxTable Components.")
    self.Pass()

  def VerifyComponentName(self, component_class, component_name):
    '''Verifies the component_name of component_class is in probed results.

    Args:
      component_class: str. e.g.,'storage' or 'tpm'.
      component_name: str. Expected component name for the component class.
                 e.g.,'sandisk_i100_32g' or 'infineon_9965_1.2.4.31'.
    Returns:
      Boolean, True if component_name is in probed results, False if not.

    self._test.probed_results is a dict from component class
      to a list of one or more ProbedComponentResult named tuples.
    {component class: [ProbedComponentResult(
      component_name,  # The component name if found in the db, else None.
      probed_string,   # The actual probed string. None if probing failed.
      error)]}         # The error message if there is one.
    '''

    target_component = self._test.probed_results.get(component_class)
    # TODO (bowgotsai): support multiple sub-components for a component_class.
    # For example,
    #   audio_codec:
    #       - creative_ca0132
    #       - intel_pantherpoint_hdmi
    if component_name == target_component[0].component_name:
      logging.info("Expected component %r found.", component_name)
      return True
    return False

class VerifyComponentsTest(unittest.TestCase):
  ARGS = [
    Arg('component_list', list,
        'A list of components to be verified'),
    Arg('board', str,
        'The board which includes the BOMs to whitelist.',
        optional=True),
    Arg('bom_whitelist', list,
        'A whitelist of BOMs that the component probed results must match. '
        'When specified, probed components must match at least one BOM',
        optional=True),
    Arg('aux_table_component_mapping', str,
        'The name of the aux lookup table used for verifying the mapping '
        'from BOMCode or MLBSerialNumber to some specific components.'
        'It selects one row from the aux table based on previously '
        'scanned BOMCode or MLBSerialNumber. Then check specific '
        'components specified in aux_field_component_list.',
        optional=True),
    Arg('aux_field_component_list', list,
        'A list of components in aux_table to be verified.',
        optional=True),
  ]

  def __init__(self, *args, **kwargs):
    super(VerifyComponentsTest, self).__init__(*args, **kwargs)
    self._shopfloor = shopfloor
    self._ui = test_ui.UI()
    self._ui.AppendCSS('.progress-message {font-size: 2em;}')
    self.board = None
    self.component_list = None
    self.gooftool = Gooftool()
    self.probed_results = None
    self.template = ui_templates.OneSection(self._ui)
    self.template.SetTitle(_TEST_TITLE)

  def runTest(self):
    self.component_list = self.args.component_list
    self.board = self.args.board

    task_list = [CheckComponentsTask(self)]

    # Run VerifyAnyBOMTask if the BOM whitelist is specified.
    if self.args.bom_whitelist:
      task_list.append(VerifyAnyBOMTask(self, self.args.bom_whitelist))

    # Run CheckAuxTableComponentsTask if aux_field_component_list is specified.
    if self.args.aux_field_component_list:
      task_list.append(CheckAuxTableComponentsTask(
          self,
          self._shopfloor,
          self.args.aux_table_component_mapping,
          self.args.aux_field_component_list))

    FactoryTaskManager(self._ui, task_list).Run()

