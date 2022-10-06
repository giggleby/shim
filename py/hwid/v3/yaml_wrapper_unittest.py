#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import textwrap
import unittest

from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import rule
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.test.l10n import regions
from cros.factory.unittest_utils import label_utils


_REGIONS_DATABASE_PATH = os.path.join(
    os.path.dirname(__file__), 'testdata', 'test_yaml_wrapper_regions.json')


class ParseRegionFieldUnittest(unittest.TestCase):
  # TODO (b/212216855)
  @label_utils.Informational
  def testDecodeYAMLTag(self):
    doc = 'foo: !region_field'
    decoded = yaml.safe_load(doc)
    self.assertEqual({'region': 'us'}, decoded['foo'][29])
    self.assertEqual({'region': 'sa'}, decoded['foo'][128])
    self.assertFalse(127 in decoded['foo'])  # region 'zw' is not confirmed yet.
    self.assertTrue(decoded['foo'].is_legacy_style)

    # "no" should not be parsed as "false" (boolean) here.
    doc = 'foo: !region_field [us, gb, no]'
    decoded = yaml.safe_load(doc)
    self.assertFalse(decoded['foo'].is_legacy_style)
    self.assertEqual(decoded['foo'], {
        0: {'region': []},
        1: {'region': 'us'},
        2: {'region': 'gb'},
        3: {'region': 'no'}})

    fields = database.EncodedFields(decoded)
    self.assertFalse(fields.region_field_legacy_info['foo'])
    self.assertEqual(fields.GetField('foo'), {
        0: {'region': []},
        1: {'region': ['us']},
        2: {'region': ['gb']},
        3: {'region': ['no']}})

  def testDumpRegionField(self):
    doc = 'foo: !region_field [us, gb]'
    decoded = yaml.safe_load(doc)
    dump_str = yaml.safe_dump(decoded).strip()
    self.assertEqual(doc, dump_str)

    doc = 'foo: !region_field'
    decoded = yaml.safe_load(doc)
    dump_str = yaml.safe_dump(decoded, default_flow_style=False).strip()
    self.assertEqual(doc, dump_str)


class ParseRegionComponentUnittest(unittest.TestCase):
  def setUp(self):
    regions.InitialSetup(
        region_database_path=_REGIONS_DATABASE_PATH, include_all=False)

  def tearDown(self):
    regions.InitialSetup()

  def testLoadRegionComponent(self):
    for s in ('region: !region_component', 'region: !region_component {}'):
      obj = yaml.safe_load(s)['region']
      self.assertEqual(dict(obj), {
          'items': {
              'aa': {'values': {'region_code': 'aa'}},
              'bb': {'values': {'region_code': 'bb'}},
              'zz': {'values': {'region_code': 'zz'},
                     'status': 'unsupported'}}})

  def testLoadRegionComponentStatusLists(self):
    obj = yaml.safe_load('region: !region_component\n'
                         '  unqualified: [aa]\n'
                         '  deprecated: [zz]\n')['region']
    self.assertEqual(dict(obj), {
        'items': {
            'aa': {'values': {'region_code': 'aa'},
                   'status': 'unqualified'},
            'bb': {'values': {'region_code': 'bb'}},
            'zz': {'values': {'region_code': 'zz'},
                   'status': 'deprecated'}}})

  def testLoadRegionComponentError(self):
    self.assertRaises(Exception, yaml.safe_load,
                      'region: !region_component 123')
    self.assertRaises(Exception, yaml.safe_load, 'region: !region_component\n'
                      '  bad_key: []\n')
    self.assertRaises(Exception, yaml.safe_load, 'region: !region_component\n'
                      '  unqualified: tw\n')
    self.assertRaises(Exception, yaml.safe_load, 'region: !region_component\n'
                      '  unqualified: []\n')
    self.assertRaises(
        Exception, yaml.safe_load, 'region: !region_component\n'
        '  unqualified: [tw, us]\n'
        '  deprecated: [us, gb]\n')

  def testDumpRegionComponent(self):
    load2 = lambda doc: yaml.safe_load(
        yaml.safe_dump(yaml.safe_load(doc), default_flow_style=False))
    doc = 'region: !region_component\n'
    self.assertEqual(yaml.safe_load(doc), load2(doc))
    doc = 'region: !region_component {}\n'
    self.assertEqual(yaml.safe_load(doc), load2(doc))

    doc = 'region: !region_component\n  unqualified: [zz]\n'
    self.assertEqual(yaml.safe_load(doc), load2(doc))
    doc = 'region: !region_component\n  unqualified: [zz]\n  unsupported: [aa]'
    self.assertEqual(yaml.safe_load(doc), load2(doc))


class StandardizeUnittest(unittest.TestCase):
  def testParseBool(self):
    self.assertEqual(yaml.safe_load('true'), True)
    self.assertEqual(yaml.safe_load('TRUE'), True)
    self.assertEqual(yaml.safe_load('false'), False)
    self.assertEqual(yaml.safe_load('FALSE'), False)

    self.assertEqual(yaml.safe_load('no'), 'no')
    self.assertEqual(yaml.safe_load('NO'), 'NO')
    self.assertEqual(yaml.safe_load('yes'), 'yes')
    self.assertEqual(yaml.safe_load('YES'), 'YES')

    self.assertEqual(yaml.safe_load('on'), 'on')
    self.assertEqual(yaml.safe_load('ON'), 'ON')
    self.assertEqual(yaml.safe_load('off'), 'off')
    self.assertEqual(yaml.safe_load('OFF'), 'OFF')


class LinkAVLTest(unittest.TestCase):

  def testAVLProbeValue_Load(self):
    obj = yaml.safe_load(
        textwrap.dedent('''\
            !link_avl
            converter: converter1
            probe_value_matched: false
            original_values: {key: value}
            '''))
    self.assertIsInstance(obj, rule.AVLProbeValue)
    self.assertDictEqual({'key': 'value'}, obj)
    self.assertEqual('converter1', obj.converter_identifier)
    self.assertFalse(obj.probe_value_matched)

  def testAVLProbeValue_Dump(self):
    obj = rule.AVLProbeValue('converter', False, {'key': 'value'})
    dump_str = yaml.safe_dump(obj)
    self.assertEqual('{key: value}\n', dump_str)

  def testAVLProbeValue_DumpInternal(self):
    obj1 = rule.AVLProbeValue('converter', True, {'key': 'value'})
    dump_str = yaml.safe_dump(obj1, internal=True)
    # Current version of PyYaml does not support sort_keys=False feature in
    # represent_mapping method, so this test only ensures that loaded obj is the
    # same as the original one.
    obj2 = yaml.safe_load(dump_str)

    self.assertIsInstance(obj2, rule.AVLProbeValue)
    self.assertDictEqual(obj2, obj1)
    self.assertEqual('converter', obj2.converter_identifier)
    self.assertTrue(obj2.probe_value_matched)


@rule.RuleFunction(['string'])
def StrLen():
  return len(rule.GetContext().string)


@rule.RuleFunction(['string'])
def AssertStrLen(length):
  logger = rule.GetLogger()
  if len(rule.GetContext().string) <= length:
    logger.Error('Assertion error')


class ValueYAMLTagTest(unittest.TestCase):
  def testYAMLParsing(self):
    self.assertEqual(yaml.safe_load('!re abc'), rule.Value('abc', is_re=True))
    self.assertEqual(
        yaml.safe_load(yaml.safe_dump(rule.Value('abc', is_re=False))), 'abc')
    self.assertIn(
        yaml.safe_dump(rule.Value('abc', is_re=True)),
        (
            "!re 'abc'\n",  # SafeDump style
            "!re abc\n...\n",  # CSafeDumper style
        ))


class FromFactoryBundleYAMLTagTest(unittest.TestCase):

  def testFromFactoryBundle_Load(self):
    obj = yaml.safe_load(
        textwrap.dedent('''\
            !from_factory_bundle
            key: value
            bundle_uuids:
            - uuid1
            '''))
    self.assertDictEqual({'key': 'value'}, obj)
    self.assertEqual(obj.bundle_uuids, ['uuid1'])

  def testFromFactoryBundle_Dump(self):
    obj = rule.FromFactoryBundle(bundle_uuids=['uuid1'], key='value')
    dump_str = yaml.safe_dump(obj)
    self.assertEqual('{key: value}\n', dump_str)

  def testFromFactoryBundle_DumpInternal(self):
    obj1 = rule.FromFactoryBundle(bundle_uuids=['uuid1'], key='value')
    dump_str = yaml.safe_dump(obj1, internal=True)
    # Current version of PyYaml does not support sort_keys=False feature in
    # represent_mapping method, so this test only ensures that loaded obj is the
    # same as the original one.
    obj2 = yaml.safe_load(dump_str)
    self.assertDictEqual({'key': 'value'}, obj2)
    self.assertEqual(obj2.bundle_uuids, ['uuid1'])


class FlowStyleForMultiLineDataTest(unittest.TestCase):

  def testFlowStyleIsLiteral(self):
    # A space followed by a newline in yaml means two spaces in folded flow
    # style ('>').  However, this does not work (especially for
    # CSafe{Dumper,Loader} if the line is already indented.  This test fails
    # when the flow style is set to '>'.

    data = {
        'key':
            textwrap.dedent(f'''\
                firstline
                 {'x' * 80}  remaining
            ''')
    }

    dumped = yaml.safe_dump(data)
    loaded = yaml.safe_load(dumped)

    # The loaded value loaded['key'] by folded flow style will be
    # f"firstline\n {'x' * 80} \nremaining\n" which is inconsistent.
    self.assertDictEqual(data, loaded)
    self.assertEqual(
        textwrap.dedent(f'''\
            key: |
              firstline
               {'x' * 80}  remaining
        '''), dumped)


if __name__ == '__main__':
  unittest.main()
