#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.l10n import regions
from cros.factory.test import device_data
from cros.factory.test.pytests import update_device_data


_KNOWN_KEY_LABELS = update_device_data._KNOWN_KEY_LABELS  # pylint: disable=protected-access
_COMMONLY_USED_REGIONS = update_device_data._COMMONLY_USED_REGIONS  # pylint: disable=protected-access


class GetDisplayNameWithKeyUnitTest(unittest.TestCase):

  def testNameGiven(self):
    name = 'super power name'
    cases = [{
        'name': 'test random input',
        'key': 'irrelevant.key',
    }, {
        'name': 'keys in the known set should still be override',
        'key': device_data.KEY_SERIAL_NUMBER,
    }]

    for c in cases:
      self.assertEqual(
          update_device_data.GetDisplayNameWithKey(c['key'], name), name,
          msg=f'test failed at {c["name"]}')

  def testKnownKey(self):
    for known_key, expected in _KNOWN_KEY_LABELS.items():
      self.assertEqual(
          update_device_data.GetDisplayNameWithKey(known_key), expected)

  def testNoNameGivenAndNotKnownKey(self):
    irrelevant_key = 'irrelevant.key'
    self.assertEqual(
        update_device_data.GetDisplayNameWithKey(irrelevant_key),
        irrelevant_key)


class CreateRegionOptionsUnitTest(unittest.TestCase):

  def _ValidateOptionMatchesDisplayText(self, options):
    for idx, option in enumerate(options):
      description = regions.REGIONS[option[0]].description
      self.assertEqual(option[1], f'{idx + 1} - {option[0]}: {description}')

  def testAllRegion(self):
    options = update_device_data.CreateRegionOptions()
    self._ValidateOptionMatchesDisplayText(options)
    # Test commonly used regions should be in first sections.
    option_regions = [option[0] for option in options]
    self.assertEqual(
        set(option_regions[:len(_COMMONLY_USED_REGIONS)]),
        set(_COMMONLY_USED_REGIONS))

  def testWithSomeAllowedRegions(self):
    available_regions = ['us', 'tw']
    options = update_device_data.CreateRegionOptions(available_regions)
    self._ValidateOptionMatchesDisplayText(options)
    self.assertEqual([option[0] for option in options], available_regions)

  def testInvalidAllowedRegions(self):
    available_regions = ['alien']
    with self.assertRaises(ValueError):
      update_device_data.CreateRegionOptions(available_regions)


class CreateSelectionOptionsUnitTest(unittest.TestCase):

  def testValidValueCheckWithNonListItem(self):
    value_check = ['str_input', 3, False]
    output = update_device_data.CreateSelectOptions(value_check)
    expected = [('str_input', '1 - str_input'), (3, '2 - 3'),
                (False, '3 - False')]
    self.assertEqual(output, expected)

  def testValidValueCheckItemWithListItem(self):
    value_check = [['option'], ['option_value', 'option_text'],
                   ['option_value', 'option_text', 'dummy']]
    output = update_device_data.CreateSelectOptions(value_check)
    expected = [
        ('option', '1 - option'),
        ('option_value', '2 - option_text'),
        ('option_value', '3 - option_text'),
    ]
    self.assertEqual(output, expected)

  def testUnsupportedValueCheckItemType(self):
    with self.assertRaises(ValueError):
      value_check = [('tuple not supported', )]
      update_device_data.CreateSelectOptions(value_check)

  def testEmptyValueCheckItem(self):
    with self.assertRaises(ValueError):
      update_device_data.CreateSelectOptions([[]])


class TextDataEntryUnitTest(unittest.TestCase):

  def testGetValueBeforeSet(self):
    default_value = 'default_value'
    entry = update_device_data.TextDataEntry('key', default_value,
                                             'random_label', None)
    self.assertEqual(entry.GetValue(), default_value)

  def testInvalidRegexPattern(self):
    with self.assertRaises(Exception):
      update_device_data.TextDataEntry('key', None, 'random_label', '[')

  def testGetValueAfterSet(self):
    expected_value = 'Hello, world'
    entry = update_device_data.TextDataEntry('key', None, 'random_label',
                                             '^Hello, .*$')
    entry.SetValueFromString(expected_value)
    self.assertEqual(entry.GetValue(), expected_value)

  def testSetValueNotMatchingPattern(self):
    expected_value = 'I do not say hello'
    entry = update_device_data.TextDataEntry('key', None, 'random_label',
                                             '^Hello, .*$')
    with self.assertRaises(ValueError):
      entry.SetValueFromString(expected_value)


class SelectionDataEntryUnitTest(unittest.TestCase):

  test_options = [(1, 'text A'), (2, 'text B')]

  def testGetValueBeforeSet(self):
    default_value = 1
    entry = update_device_data.SelectionDataEntry(
        'key', default_value, 'random_label',
        SelectionDataEntryUnitTest.test_options)
    self.assertEqual(entry.GetValue(), default_value)

  def testGetValueAfterSet(self):
    entry = update_device_data.SelectionDataEntry(
        'key', None, 'random_label', SelectionDataEntryUnitTest.test_options)
    expected_value = SelectionDataEntryUnitTest.test_options[0][0]
    entry.SetValueFromString(str(expected_value))
    self.assertEqual(entry.GetValue(), expected_value)

  def testGetIndexWithDefaultValidValue(self):
    idx = 0
    value = SelectionDataEntryUnitTest.test_options[idx][0]
    entry = update_device_data.SelectionDataEntry(
        'key', value, 'random_label', SelectionDataEntryUnitTest.test_options)
    self.assertEqual(idx, entry.GetSelectedIndex())

  def testGetIndexIfValueNotSet(self):
    entry = update_device_data.SelectionDataEntry(
        'key', None, 'random_label', SelectionDataEntryUnitTest.test_options)
    with self.assertRaises(ValueError):
      entry.GetSelectedIndex()

  def testGetIndexAfterSetValue(self):
    entry = update_device_data.SelectionDataEntry(
        'key', None, 'random_label', SelectionDataEntryUnitTest.test_options)
    idx = 1
    value = SelectionDataEntryUnitTest.test_options[idx][0]
    entry.SetValueFromString(str(value))
    self.assertEqual(idx, entry.GetSelectedIndex())

  def testSetValueNotInOption(self):
    entry = update_device_data.SelectionDataEntry(
        'key', None, 'random_label', SelectionDataEntryUnitTest.test_options)
    with self.assertRaises(ValueError):
      entry.SetValueFromString('random_value')


class CreateDataEntryUnitTest(unittest.TestCase):

  @mock.patch('cros.factory.test.device_data.CheckValidDeviceDataKey')
  def testRegionKey(self, check_mock):
    check_mock.return_value = None
    entry = update_device_data.CreateDataEntry(device_data.KEY_VPD_REGION, 'tw',
                                               None, None)
    self.assertIsInstance(entry, update_device_data.SelectionDataEntry)

  @mock.patch('cros.factory.test.device_data.CheckValidDeviceDataKey')
  def testValueCheckWithNone(self, check_mock):
    check_mock.return_value = None
    entry = update_device_data.CreateDataEntry('test.key', 'random_value', None,
                                               None)
    self.assertIsInstance(entry, update_device_data.TextDataEntry)

  @mock.patch('cros.factory.test.device_data.CheckValidDeviceDataKey')
  def testValueCheckWithRegexPattern(self, check_mock):
    check_mock.return_value = None
    entry = update_device_data.CreateDataEntry('test.key', 'random_value', None,
                                               '.*')
    self.assertIsInstance(entry, update_device_data.TextDataEntry)

  @mock.patch('cros.factory.test.device_data.CheckValidDeviceDataKey')
  def testValueCheckWithOptions(self, check_mock):
    check_mock.return_value = None
    entry = update_device_data.CreateDataEntry('test.key', 'random_value', None,
                                               ['option A', 'option B'])
    self.assertIsInstance(entry, update_device_data.SelectionDataEntry)

  def testInvalidDeviceKey(self):
    with self.assertRaises(KeyError):
      update_device_data.CreateDataEntry('impossible.key', 'random_value', None,
                                         None)

  @mock.patch('cros.factory.test.device_data.CheckValidDeviceDataKey')
  def testBoolValue(self, check_mock):
    check_mock.return_value = None
    entry = update_device_data.CreateDataEntry('test.key', True, None, None)
    self.assertIsInstance(entry, update_device_data.SelectionDataEntry)


if __name__ == '__main__':
  unittest.main()
