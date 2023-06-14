#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from google.protobuf import text_format

from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine.probe_tools import probe_statement_converters as ps_converters


def _CreateStrProbeParam(name: str,
                         value: str) -> probe_info_analytics.ProbeParameter:
  return probe_info_analytics.ProbeParameter(name=name, string_value=value)


class TouchscreenModuleConverterTest(unittest.TestCase):

  def setUp(self):
    self._converter = ps_converters.BuildTouchscreenModuleConverter()

  def testGenerateDefinition(self):
    actual = self._converter.GenerateDefinition()

    expect = text_format.Parse(
        '''
        name: "touchscreen_module.generic_input_device_and_edid"
        description:
          "Probe statement converter for touchscreen modules with eDP displays."
        parameter_definitions {
          name: "module_vendor_id"
          description: "Vendor ID."
          value_type: STRING
        }
        parameter_definitions {
          name: "module_product_id"
          description: "Product ID."
          value_type: STRING
        }
        parameter_definitions {
          name: "panel_edid_vendor_code"
          description: "The vendor code, 3 letters"
          value_type: STRING
        }
        parameter_definitions {
          name: "panel_edid_product_id"
          description: "The product ID, 16 bits"
          value_type: STRING
        }''', probe_info_analytics.ProbeFunctionDefinition())
    self.assertEqual(actual, expect)

  def testParseProbeParam_WithMissingParamAllowed_ThenValidationPassed(self):
    probe_params = [
        _CreateStrProbeParam('module_vendor_id', 'AB12'),
        _CreateStrProbeParam('module_product_id', 'CD34'),
        _CreateStrProbeParam('panel_edid_vendor_code', 'ABC'),
        # `panel_edid_product_id` is missing.
    ]

    actual = self._converter.ParseProbeParams(probe_params,
                                              allow_missing_params=True)

    self.assertEqual(actual.probe_info_parsed_result.result_type,
                     probe_info_analytics.ProbeInfoParsedResult.PASSED)

  def testParseProbeParam_WithMissingParamNotAllowed_ThenValidationFailed(self):
    probe_params = [
        _CreateStrProbeParam('module_vendor_id', 'AB12'),
        _CreateStrProbeParam('module_product_id', 'CD34'),
        _CreateStrProbeParam('panel_edid_vendor_code', 'ABC'),
        # `panel_edid_product_id` is missing.
    ]

    actual = self._converter.ParseProbeParams(probe_params,
                                              allow_missing_params=False)

    expected_parsed_result = probe_info_analytics.ProbeInfoParsedResult(
        result_type=(
            probe_info_analytics.ProbeInfoParsedResult.INCOMPATIBLE_ERROR),
        general_error_msg='Missing probe parameters: panel_edid_product_id.')
    self.assertEqual(actual.probe_info_parsed_result, expected_parsed_result)

  def testParseProbeParam_WithSomeParamValueInvalid_ThenValidationFailed(self):
    probe_params = [
        _CreateStrProbeParam('module_vendor_id', 'not a hex string'),
        _CreateStrProbeParam('module_product_id', 'CD34'),
        _CreateStrProbeParam('panel_edid_vendor_code', 'value is too long'),
        _CreateStrProbeParam('panel_edid_product_id', '1234'),
    ]

    actual = self._converter.ParseProbeParams(probe_params,
                                              allow_missing_params=True)

    expected_parsed_result = probe_info_analytics.ProbeInfoParsedResult(
        result_type=(
            probe_info_analytics.ProbeInfoParsedResult.PROBE_PARAMETER_ERROR))
    expected_parsed_result.probe_parameter_errors.add(
        index=0, hint=('format error, should be hex number between 0000 and '
                       'FFFF with leading zero perserved.'))
    expected_parsed_result.probe_parameter_errors.add(
        index=2, hint='Must be a 3-letter all caps string.')
    self.assertEqual(actual.probe_info_parsed_result, expected_parsed_result)

  def testParseProbeParam_WithExtraParam_ThenValidationFailed(self):
    probe_params = [
        _CreateStrProbeParam('module_vendor_id', 'AB12'),
        _CreateStrProbeParam('module_product_id', 'CD34'),
        _CreateStrProbeParam('panel_edid_vendor_code', 'ABC'),
        _CreateStrProbeParam('panel_edid_product_id', '1234'),
        _CreateStrProbeParam('the_unknown_param', 'the_unknown_value'),
    ]

    actual = self._converter.ParseProbeParams(probe_params,
                                              allow_missing_params=True)

    expected_parsed_result = probe_info_analytics.ProbeInfoParsedResult(
        result_type=(
            probe_info_analytics.ProbeInfoParsedResult.INCOMPATIBLE_ERROR),
        general_error_msg='Unknown probe parameters: the_unknown_param.')
    self.assertEqual(actual.probe_info_parsed_result, expected_parsed_result)

  def testParseProbeParam_CanGenerateProbeStatement(self):
    probe_params = [
        _CreateStrProbeParam('module_vendor_id', 'AB12'),
        _CreateStrProbeParam('module_product_id', 'CD34'),
        _CreateStrProbeParam('panel_edid_vendor_code', 'ABC'),
        _CreateStrProbeParam('panel_edid_product_id', '1234'),
    ]

    actual = self._converter.ParseProbeParams(
        probe_params, allow_missing_params=False,
        comp_name_for_probe_statement='comp_name')

    expected_probe_statements = [
        probe_config_types.ComponentProbeStatement(
            'touchscreen', 'comp_name-touchscreen_controller', {
                'eval': {
                    'input_device': {}
                },
                'expect': {
                    'vendor': [True, 'hex', '!eq 0xAB12'],
                    'product': [True, 'hex', '!eq 0xCD34']
                }
            }),
        probe_config_types.ComponentProbeStatement(
            'display_panel', 'comp_name-edid_panel', {
                'eval': {
                    'edid': {}
                },
                'expect': {
                    'vendor': [True, 'str', '!eq ABC'],
                    'product_id': [True, 'hex', '!eq 0x1234']
                }
            })
    ]
    self.assertCountEqual(actual.output, expected_probe_statements)


if __name__ == '__main__':
  unittest.main()
