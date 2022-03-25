#!/usr/bin/env python3
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unittest for json_utils.py."""

import enum
import os
from typing import Dict, List, NamedTuple, Optional
import unittest

from cros.factory.utils import file_utils
from cros.factory.utils import json_utils

_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__),
                               'testdata', 'json_utils_unittest.json')


class _TestCaseBase(unittest.TestCase):

  def assertJSONObjEqual(self, a, b):
    if isinstance(a, list):
      self.assertIsInstance(b, list)
      self.assertEqual(len(a), len(b))
      for element_a, element_b in zip(a, b):
        self.assertJSONObjEqual(element_a, element_b)
    elif isinstance(a, dict):
      self.assertIsInstance(b, dict)
      self.assertEqual(len(a), len(b))
      for key, value in a.items():
        self.assertJSONObjEqual(value, b[key])
    else:
      self.assertIs(type(a), type(b))
      self.assertEqual(a, b)


class LoadStrTest(_TestCaseBase):
  _TEST_DATA = '{"aaa": [3, false, null, "bbb"]}'

  def testLoadStr(self):
    self.assertJSONObjEqual(
        json_utils.LoadStr(self._TEST_DATA), {'aaa': [3, False, None, "bbb"]})


class LoadFileTest(_TestCaseBase):

  def testLoadFile(self):
    self.assertJSONObjEqual(
        json_utils.LoadFile(_TEST_DATA_PATH), {
            'aaa': 'bbb',
            'ccc': ['ddd', {}, 'fff']
        })


# For dumping related tests, just check whether the dumped output can be loaded
# back or not.


class DumpStrTest(_TestCaseBase):
  _TEST_DATA = {
      'aaa': [3, False, None, 'bbb']
  }

  def testNormal(self):
    for kwargs in [{}, {
        'pretty': False
    }, {
        'pretty': True
    }]:
      json_str = json_utils.DumpStr(self._TEST_DATA, **kwargs)
      self.assertJSONObjEqual(json_utils.LoadStr(json_str), self._TEST_DATA)


class DumpFileTest(_TestCaseBase):
  _TEST_DATA = {
      'aaa': [3, False, None, 'bbb']
  }

  def testNormal(self):
    for kwargs in [{}, {
        'pretty': False
    }, {
        'pretty': True
    }]:
      with file_utils.UnopenedTemporaryFile() as path:
        json_utils.DumpFile(path, self._TEST_DATA, **kwargs)
        self.assertJSONObjEqual(json_utils.LoadFile(path), self._TEST_DATA)


class JSONDatabaseTest(_TestCaseBase):

  def testNormal(self):
    with file_utils.TempDirectory() as dir_path:
      db_path = os.path.join(dir_path, 'db')

      db = json_utils.JSONDatabase(db_path, allow_create=True)
      self.assertJSONObjEqual(db, {})

      db['aaa'] = 'bbb'
      db['ccc'] = [1, None, {
          'ddd': 'eee'
      }]
      self.assertJSONObjEqual(db, {
          'aaa': 'bbb',
          'ccc': [1, None, {
              'ddd': 'eee'
          }]
      })

      db.Save()
      db2 = json_utils.JSONDatabase(db_path)
      self.assertJSONObjEqual(db2, {
          'aaa': 'bbb',
          'ccc': [1, None, {
              'ddd': 'eee'
          }]
      })


class _EnumForSerializerTest(enum.Enum):
  E1 = enum.auto()
  E2 = enum.auto()


class _NameTupleForSerializerTest(NamedTuple):
  field1: int
  field2: List[Optional['_NameTupleForSerializerTest']]
  field3: Dict[str, _EnumForSerializerTest]


class SerializerTest(_TestCaseBase):

  def testAll(self):
    test_data = {
        'aaa':
            _NameTupleForSerializerTest(3, [
                None,
                _NameTupleForSerializerTest(5, [],
                                            {'a': _EnumForSerializerTest.E1}),
            ], {'b': _EnumForSerializerTest.E2}),
        'bbb':
            123
    }

    serializer = json_utils.Serializer(
        [json_utils.ConvertEnumToStr, json_utils.ConvertNamedTupleToDict])
    actual_serialized_result = serializer.Serialize(test_data)

    expected_serialized_result = {
        'aaa': {
            'field1': 3,
            'field2': [
                None,
                {
                    'field1': 5,
                    'field2': [],
                    'field3': {
                        'a': 'E1',
                    },
                },
            ],
            'field3': {
                'b': 'E2',
            },
        },
        'bbb': 123,
    }
    self.assertJSONObjEqual(actual_serialized_result,
                            expected_serialized_result)


if __name__ == '__main__':
  unittest.main()
