#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.v3 import database as v3_database
from cros.factory.hwid.v3 import rule as v3_rule


GOLDEN_HWIDV3_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata/v3-golden.yaml')


class ComponentTest(unittest.TestCase):
  """Tests the Component class."""

  def testEquality(self):
    self.assertEqual(
        hwid_action.Component('foo', 'bar'), hwid_action.Component(
            'foo', 'bar'))
    self.assertEqual(
        hwid_action.Component(
            'foo', 'bar', fields={
                'f1': 'v1',
                'f2': 'v2',
                'f3': v3_rule.Value(r'\d+$', is_re=True)
            }),
        hwid_action.Component(
            'foo', 'bar', fields={
                'f1': 'v1',
                'f2': 'v2',
                'f3': v3_rule.Value(r'\d+$', is_re=True)
            }))


class BOMTest(unittest.TestCase):
  """Tests the BOM class."""

  def setUp(self):
    super().setUp()
    self.bom = hwid_action.BOM()

  def testComponentsAddNoneClass(self):
    self.bom.AddComponent(None, 'foo')
    self._AssertHasComponent(None, 'foo')

  def testComponentsAddNone(self):
    self.bom.AddComponent('foo', None)
    self.bom.AddComponent('foo', None)
    self.bom.AddComponent('foo', None)
    self._AssertHasComponent('foo', None)

  def testComponentsOverrideNone(self):
    self.bom.AddComponent('foo', None)
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('foo', None)

    self._AssertHasComponent('foo', 'bar')

  def testComponentsAppend(self):
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('foo', 'baz')

    self._AssertHasComponent('foo', 'bar')
    self._AssertHasComponent('foo', 'baz')

  def testMultipleComponents(self):
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('baz', 'qux')

    self._AssertHasComponent('foo', 'bar')
    self._AssertHasComponent('baz', 'qux')

  def testAddAllComponents(self):
    self.bom.AddAllComponents({
        'foo': 'bar',
        'baz': ['qux', 'rox']
    })

    self._AssertHasComponent('foo', 'bar')
    self._AssertHasComponent('baz', 'qux')
    self._AssertHasComponent('baz', 'rox')

  def testAddAllComponentsWithInfo(self):
    db = v3_database.Database.LoadFile(GOLDEN_HWIDV3_FILE,
                                       verify_checksum=False)
    self.bom.AddAllComponents({'storage': ['storage_2']}, db)
    comp = self.bom.GetComponents('storage')[0]
    self.assertEqual('storage_0', comp.information['comp_group'])

  def testAddAllComponentsWithFields(self):
    db = v3_database.Database.LoadFile(GOLDEN_HWIDV3_FILE,
                                       verify_checksum=False)
    self.bom.AddAllComponents({'storage': ['storage_1']}, db, True)
    comp, = self.bom.GetComponents('storage')
    self.assertEqual(
        {
            'model': 'model1',
            'sectors': '100',
            'vendor': 'vendor1',
            'serial': v3_rule.Value(r'^#123\d+$', is_re=True)
        }, comp.fields)

  def testGetComponents(self):
    self.bom.AddComponent('foo', 'bar')
    self.bom.AddComponent('baz', 'qux')
    self.bom.AddComponent('baz', 'rox')
    self.bom.AddComponent('zib', None)

    components = self.bom.GetComponents()

    self.assertEqual(4, len(components))
    self.assertIn(hwid_action.Component('foo', 'bar'), components)
    self.assertIn(hwid_action.Component('baz', 'qux'), components)
    self.assertIn(hwid_action.Component('baz', 'rox'), components)
    self.assertIn(hwid_action.Component('zib', None), components)

    self.assertEqual([hwid_action.Component('foo', 'bar')],
                     self.bom.GetComponents('foo'))
    self.assertEqual([], self.bom.GetComponents('empty-class'))

  def _AssertHasComponent(self, cls, name):
    # pylint: disable=protected-access
    self.assertIn(cls, self.bom._components)
    if name:
      self.assertIn(name, (comp.name for comp in self.bom._components[cls]))
    else:
      self.assertEqual([], self.bom._components[cls])
    # pylint: enable=protected-access


if __name__ == '__main__':
  unittest.main()
