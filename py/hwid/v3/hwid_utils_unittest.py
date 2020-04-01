#!/usr/bin/env python2
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Integration tests for the HWID v3 framework."""

import os
import unittest

import mock

import factory_common  # pylint: disable=unused-import
from cros.factory.hwid.v3.bom import BOM
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3.database import Database
from cros.factory.hwid.v3 import hwid_utils


_TEST_DATABASE_PATH = os.path.join(
    os.path.dirname(__file__), 'testdata', 'TEST_PROJECT')

_TEST_PROBED_RESULTS_PATH = os.path.join(
    os.path.dirname(__file__), 'testdata', 'TEST_PROJECT_probed_results')

_TEST_ENCODED_STRING_GOOD = 'CHROMEBOOK B9M-A6P'

_TEST_ENCODED_STRING_BATTERY_UNSUPPORTED = 'CHROMEBOOK B3M-A4Z'

_TEST_ENCODED_STRING_FIRMWARE_KEYS_PREMP = 'CHROMEBOOK B8M-A7Y'


class _HWIDTestCaseBase(unittest.TestCase):
  def assertBOMEquals(self, bom1, bom2):
    self.assertEquals(bom1.encoding_pattern_index, bom2.encoding_pattern_index)
    self.assertEquals(bom1.image_id, bom2.image_id)
    self.assertEquals(set(bom1.components.keys()), set(bom2.components.keys()))
    for comp_cls, bom1_comp_names in bom1.components.iteritems():
      self.assertEquals(bom1_comp_names, bom2.components[comp_cls])

  def setUp(self):
    self.database = Database.LoadFile(_TEST_DATABASE_PATH,
                                      verify_checksum=False)
    self.probed_results = hwid_utils.GetProbedResults(
        infile=_TEST_PROBED_RESULTS_PATH)


class GenerateHWIDTest(_HWIDTestCaseBase):
  def testNormal(self):
    identity = hwid_utils.GenerateHWID(
        self.database, self.probed_results, {}, {}, False)
    self.assertEquals(identity.encoded_string, _TEST_ENCODED_STRING_GOOD)

  def testBadComponentStatus(self):
    # The function should also verify if all the component status are valid.
    self.probed_results['battery'] = [{'name': 'battery_unsupported',
                                       'values': {'size': '1'}}]
    self.assertRaises(common.HWIDException, hwid_utils.GenerateHWID,
                      self.database, self.probed_results, {}, {}, False)


class DecodeHWIDTest(_HWIDTestCaseBase):
  def testNormal(self):
    identity, bom = hwid_utils.DecodeHWID(
        self.database, _TEST_ENCODED_STRING_FIRMWARE_KEYS_PREMP)

    self.assertEquals(identity.encoded_string,
                      _TEST_ENCODED_STRING_FIRMWARE_KEYS_PREMP)
    self.assertBOMEquals(bom, BOM(0, 1, {'battery': ['battery_supported'] * 2,
                                         'firmware_keys': ['key_premp'],
                                         'region': ['tw']}))


class VerifyHWIDTest(_HWIDTestCaseBase):
  def testNormal(self):
    hwid_utils.VerifyHWID(self.database, _TEST_ENCODED_STRING_GOOD,
                          self.probed_results, {}, {},
                          False, current_phase='PVT',
                          allow_mismatched_components=False)

  def testBOMMisMatch(self):
    self.probed_results['region'] = [{'name': 'us',
                                      'values': {'region_code': 'us'}}]
    self.assertRaises(common.HWIDException, hwid_utils.VerifyHWID,
                      self.database, _TEST_ENCODED_STRING_GOOD,
                      self.probed_results, {}, {}, False,
                      current_phase='PVT', allow_mismatched_components=False)

  def testBadComponentStatus(self):
    self.probed_results['battery'] = [{'name': 'battery_unsupported',
                                       'values': {'size': '1'}}]
    self.assertRaises(common.HWIDException, hwid_utils.VerifyHWID,
                      self.database, _TEST_ENCODED_STRING_BATTERY_UNSUPPORTED,
                      self.probed_results, {}, {}, False, current_phase='PVT',
                      allow_mismatched_components=False)

  def testBadPhase(self):
    self.probed_results['firmware_keys'] = [{'name': 'premp',
                                             'values': {'rootkey': 'abcde'}}]
    self.assertRaises(common.HWIDException, hwid_utils.VerifyHWID,
                      self.database, _TEST_ENCODED_STRING_FIRMWARE_KEYS_PREMP,
                      self.probed_results, {}, {}, False, current_phase='PVT',
                      allow_mismatched_components=False)


class ListComponentsTest(_HWIDTestCaseBase):
  def _TestListComponents(self, comp_cls, expected_results):
    def _ConvertToSets(orig_dict):
      return {key: set(value) for key, value in orig_dict.iteritems()}

    results = hwid_utils.ListComponents(self.database, comp_cls)
    self.assertEquals(_ConvertToSets(results), _ConvertToSets(expected_results))

  def testSpecificComponentClass(self):
    self._TestListComponents('firmware_keys',
                             {'firmware_keys': ['key_premp', 'key_mp']})

  def testAllComponentClass(self):
    result = hwid_utils.ListComponents(self.database, None)
    self.assertIn('battery', result)
    self.assertIn('firmware_keys', result)
    self.assertIn('region', result)


class EnumerateHWIDTest(_HWIDTestCaseBase):
  def setUp(self):
    super(EnumerateHWIDTest, self).setUp()

  def testSupported(self):
    results = hwid_utils.EnumerateHWID(self.database, status='supported')
    self.assertEquals(len(results), 6)

  def testReleased(self):
    results = hwid_utils.EnumerateHWID(self.database, status='released')
    self.assertEquals(len(results), 12)

  def testAll(self):
    results = hwid_utils.EnumerateHWID(self.database, status='all')
    self.assertEquals(len(results), 24)

  def testPrevImageId(self):
    results = hwid_utils.EnumerateHWID(self.database, image_id=0, status='all')
    self.assertEquals(len(results), 12)

  def testSpecificSomeComponents(self):
    results = hwid_utils.EnumerateHWID(self.database, image_id=0, status='all',
                                       comps={'firmware_keys': ['key_premp']})
    self.assertEquals(len(results), 6)

  def testNoResult(self):
    results = hwid_utils.EnumerateHWID(self.database, image_id=0, status='all',
                                       comps={'firmware_keys': ['key_xxx']})
    self.assertEquals(len(results), 0)


class GetProbeStatementPathTest(unittest.TestCase):
  @mock.patch('os.path.exists')
  def testUseDefaultProbeStatementPath(self, os_path_exists_mock):
    project = 'PROJECT'
    os_path_exists_mock.return_value = False
    probe_statement_path = hwid_utils.GetProbeStatementPath(project)

    self.assertTrue(
        os.path.basename(probe_statement_path).startswith('default_'))

  @mock.patch('os.path.exists')
  def testUseProjectProbeStatementPath(self, os_path_exists_mock):
    project = 'PROJECT'
    os_path_exists_mock.return_value = True
    probe_statement_path = hwid_utils.GetProbeStatementPath(project)

    self.assertTrue(
        os.path.basename(probe_statement_path).startswith(
            project.lower() + '_'))


if __name__ == '__main__':
  unittest.main()
