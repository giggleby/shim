# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import json
import unittest
from unittest import mock

from cros.factory.test_list_editor.backend.models import test_list


ISO_TIME_STRING = '2023-03-22T00:11:22.345678'


class TestHelperFunc(unittest.TestCase):

  def setUp(self) -> None:
    self.mock_definitions = {
        'D': {
            'inherit': 'C',
            'test_item_id': 'D'
        },
        'C': {
            'inherit': 'B',
            'test_item_id': 'C',
            'some_field1': 1,
            'some_field2': 2
        },
        'B': {
            'inherit': 'A',
            'test_item_id': 'B',
            'some_field1': 3,
            'some_field4': 4
        },
        'A': {
            'inherit': 'A',
            'test_item_id': 'A',
            'some_field1': 5,
            'some_field6': 6
        },
        'APytest': {
            'some_fields': True,
            'test_item_id': 'APytest'
        }
    }

  def testSplitAtCapital(self):
    self.assertEqual(
        test_list._GenerateDisplayName('SomeTestString'), 'Some Test String')  # pylint: disable=protected-access
    self.assertEqual(
        test_list._GenerateDisplayName('SomeTestString123'),  # pylint: disable=protected-access
        'Some Test String123')

  def testGetDisplayName(self):
    self.assertEqual(
        test_list._GetDisplayName(  # pylint: disable=protected-access
            {'display_name': 'Other ABC'}, 'ABC'),
        'Other ABC')
    self.assertEqual(test_list._GetDisplayName({'label': 'abc'}, 'ABC'), 'abc')  # pylint: disable=protected-access
    self.assertEqual(test_list._GetDisplayName({}, 'ABC'), 'A B C')  # pylint: disable=protected-access

  @mock.patch.object(test_list, 'datetime')
  def testAssignFields(self, mock_time):
    mock_isoformat = mock.Mock()
    mock_isoformat.isoformat.return_value = ISO_TIME_STRING
    mock_time.now.return_value = mock_isoformat
    result = test_list._AddFields({'Test1': {}})  # pylint: disable=protected-access
    self.assertEqual(
        result, {
            'Test1': {
                'test_item_id': 'Test1',
                'display_name': 'Test1',
                'last_modified': ISO_TIME_STRING
            }
        })

  def testTraverseInheritanceChain(self):
    result = test_list._TraverseInheritanceChain('D', self.mock_definitions)  # pylint: disable=protected-access
    self.assertEqual(result, ['D', 'C', 'B', 'A'])

  def testTraverseInheritanceNoInherit(self):

    result = test_list._TraverseInheritanceChain(  # pylint: disable=protected-access
        'APytest', self.mock_definitions)
    self.assertEqual(result, ['APytest'])

  def testResolveOverride(self):
    mock_sequence = ['A', 'B', 'C', 'D']
    self.assertEqual(
        test_list._ResolveTestItem(mock_sequence, self.mock_definitions),  # pylint: disable=protected-access
        {
            'test_item_id': 'D',
            'inherit': 'C',
            'some_field1': 1,
            'some_field2': 2,
            'some_field4': 4,
            'some_field6': 6
        })

  def testResolveTestItemInheritance(self):
    self.assertEqual(
        test_list._ResolveTestItemInheritance('D', self.mock_definitions),  # pylint: disable=protected-access
        {
            'some_field1': 1,
            'some_field2': 2,
            'some_field4': 4,
            'some_field6': 6,
            'test_item_id': 'D',
            'inherit': 'C'
        })

  def testResolveTestItemInheritanceNoInherit(self):
    self.assertEqual(
        test_list._ResolveTestItemInheritance('APytest', self.mock_definitions),  # pylint: disable=protected-access
        {
            'some_fields': True,
            'test_item_id': 'APytest'
        })

  def testRestoreTestItemDefinitions(self) -> None:
    items = {
        'A': {
            'test_item_id': 'A',
            'display_name': 'A',
            'last_modified': ISO_TIME_STRING,
            'something_else': True
        }
    }
    self.assertEqual(
        test_list._RemoveFields(items),  # pylint: disable=protected-access
        {'A': {
            'something_else': True
        }})


class TestDiffUnit(unittest.TestCase):

  def testLoad(self) -> None:
    diff = test_list.DiffUnit()
    diff.Load({'A': True})
    self.assertEqual(diff.Export(), {'A': True})

  def testUpdate(self) -> None:
    diff = test_list.DiffUnit()
    diff.Update(['A', 'B', 'C'], 123)
    self.assertEqual(diff.Export(), {'A': {
        'B': {
            'C': 123
        }
    }})

  def testUpdateOverwrite(self) -> None:
    diff = test_list.DiffUnit()
    diff.Update(['A', 'B', 'C'], 123)
    diff.Update(['A'], 123)
    self.assertEqual(diff.Export(), {'A': 123})

  def testUpdateNested(self) -> None:
    diff = test_list.DiffUnit()
    diff.Update(['A'], {'B': {
        'C': 123
    }})
    self.assertEqual(diff.Export(), {'A': {
        'B': {
            'C': 123
        }
    }})

  def testCombineKeepBase(self) -> None:
    diff = test_list.DiffUnit()
    base = {
        'A': {
            'B': {
                'C': 123
            }
        }
    }
    expected = {
        'A': {
            'B': {
                'C': 123
            }
        },
        'D': [2, 3, 4]
    }
    diff.Update(['D'], [2, 3, 4])
    self.assertEqual(diff.Combine(base), expected)

  def testCombineEmpty(self) -> None:
    diff = test_list.DiffUnit()
    base = {
        'A': {
            'B': {
                'C': 123
            }
        }
    }
    expected = {
        'A': {
            'B': {
                'C': 123
            }
        }
    }
    self.assertEqual(diff.Combine(base), expected)

  def testCombineOverwriteBase(self) -> None:
    diff = test_list.DiffUnit()
    base = {
        'A': {
            'B': {
                'C': 123
            }
        }
    }
    expected = {
        'A': [2, 3, 4]
    }
    diff.Update(['A'], [2, 3, 4])
    self.assertEqual(diff.Combine(base), expected)


class TestEditor(unittest.TestCase):

  def setUp(self) -> None:

    mock_time = mock.patch(test_list.__name__ + '.datetime').start()
    mock_isoformat = mock.Mock()
    self.fake_time = '2023-03-22T00:11:22.345678'
    mock_isoformat.isoformat.return_value = self.fake_time
    mock_time.now.return_value = mock_isoformat

  def testLoadFromFile(self):
    # fake_load.

    # We don't test inline test items here.
    # It is covered in manager_unittest.py
    fake_data = {
        'inherit': [],
        'options': {},
        'constants': {},
        'label': {},
        'tests': [],
        'override_args': {},
        'definitions': {
            'TestItem1': {
                'subtests': []
            },
            "TestItem2": {
                "subtests": []
            }
        }
    }

    expected_test_items = {
        'TestItem1': {
            'test_item_id': 'TestItem1',
            'display_name': 'Test Item1',
            'last_modified': self.fake_time,
            'subtests': []
        },
        'TestItem2': {
            'test_item_id': 'TestItem2',
            'display_name': 'Test Item2',
            'last_modified': self.fake_time,
            'subtests': []
        }
    }

    expected_result = json.dumps(expected_test_items, sort_keys=True)

    fake_test_list = test_list.TestList()
    mock_file = mock.Mock(data=fake_data, diff_data={})
    fake_test_list.LoadFromFile(mock_file)
    test_items = fake_test_list.GetTestDefinitions()

    result = json.dumps(test_items, sort_keys=True)

    self.assertEqual(expected_result, result)

  def testGetTestItemConfig(self):
    mock_definitions = {
        'definitions': {
            'D': {
                'inherit': 'C',
                'test_item_id': 'D'
            },
            'C': {
                'inherit': 'B',
                'test_item_id': 'C',
                'some_field1': 1,
                'some_field2': 2
            },
            'B': {
                'inherit': 'A',
                'test_item_id': 'B',
                'some_field1': 3,
                'some_field4': 4
            },
            'A': {
                'inherit': 'A',
                'test_item_id': 'A',
                'some_field1': 5,
                'some_field6': 6
            },
            'APytest': {
                'some_fields': True,
                'test_item_id': 'APytest'
            }
        }
    }
    fake_test_list = test_list.TestList()
    mock_file = mock.Mock(data=mock_definitions, diff_data={})
    fake_test_list.LoadFromFile(mock_file)
    test_item = fake_test_list.GetTestItemConfig('A')

    self.assertEqual(
        test_item, {
            'display_name': 'A',
            'last_modified': self.fake_time,
            'inherit': 'A',
            'test_item_id': 'A',
            'some_field1': 5,
            'some_field6': 6
        })

  def testGetTestItemNotPresentConfig(self):
    mock_definitions = {
        'definitions': {
            'D': {
                'inherit': 'C',
                'test_item_id': 'D'
            },
            'C': {
                'inherit': 'B',
                'test_item_id': 'C',
                'some_field1': 1,
                'some_field2': 2
            },
            'B': {
                'inherit': 'A',
                'test_item_id': 'B',
                'some_field1': 3,
                'some_field4': 4
            },
            'A': {
                'inherit': 'A',
                'test_item_id': 'A',
                'some_field1': 5,
                'some_field6': 6
            },
            'APytest': {
                'some_fields': True,
                'test_item_id': 'APytest'
            }
        }
    }
    fake_test_list = test_list.TestList()
    mock_file = mock.Mock(data=mock_definitions, diff_data={})
    fake_test_list.LoadFromFile(mock_file)
    test_item = fake_test_list.GetTestItemConfig('Z')

    self.assertEqual(test_item, {})

  def testExportDiff(self):
    fake_test_list = test_list.TestList()
    mock_file = mock.Mock()
    fake_test_list.ExportDiff(mock_file)

    self.assertEqual(mock_file.diff_data, {'definitions': {}})

  def testUpdateTestItemConfig(self):
    fake_test_list = test_list.TestList()
    mock_item = mock.Mock()
    mock_item.test_item_id = 'ABC'
    mock_item.dict.return_value = {
        'test_item_id': 'ABC',
        'display_name': 'A B C',
        'last_modified': ISO_TIME_STRING
    }
    mock_file = mock.Mock()
    fake_test_list.UpdateTestItemConfig(mock_item)
    fake_test_list.ExportDiff(mock_file)

    self.assertEqual(mock_file.diff_data, {'definitions': {
        'ABC': {}
    }})


if __name__ == '__main__':
  unittest.main()
