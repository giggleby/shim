#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

import jsonschema

from cros.factory.test.test_lists import test_list_common


class TestTestListCommon(unittest.TestCase):

  def testValidateSchema(self):
    mock_test_list = {
        'inherit': [],
        'label': 'Empty Test List',
        'constants': {},
        'options': {},
        'definitions': {},
        'tests': []
    }
    test_list_common.ValidateTestListFileSchema(mock_test_list)

  def testValidateErrorTestList(self):
    mock_test_list = {
        'inherit': [],
        'label': 'Empty Test List',
        'something_wrong': True,
        'constants': {},
        'options': {},
        'definitions': {},
        'tests': []
    }
    with self.assertRaises(jsonschema.ValidationError):
      test_list_common.ValidateTestListFileSchema(mock_test_list)


if __name__ == '__main__':
  unittest.main()
