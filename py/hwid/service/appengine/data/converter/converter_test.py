# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Mapping, Union
import unittest

from cros.factory.hwid.service.appengine.data.converter import converter
from cros.factory.hwid.service.appengine.data.converter import converter_types
from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import builder as v3_builder
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import rule as v3_rule
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


_PVAlignmentStatus = contents_analyzer.ProbeValueAlignmentStatus


class TestAVLAttrs(converter.AVLAttrs):
  AVL_ATTR1 = 'avl_attr_name1'
  AVL_ATTR2 = 'avl_attr_name2'
  AVL_ATTR3 = 'avl_attr_name3'
  AVL_ATTR4 = 'avl_attr_name4'


def _ProbeInfoFromMapping(mapping: Mapping[str, Union[str, int]]):
  return stubby_pb2.ProbeInfo(probe_parameters=[
      stubby_pb2.ProbeParameter(name=name, string_value=value) if isinstance(
          value, str) else stubby_pb2.ProbeParameter(name=name, int_value=value)
      for name, value in mapping.items()
  ])


def _HWIDDBExternalResourceFromProbeInfos(
    probe_info_mapping: Mapping[int, stubby_pb2.ProbeInfo]
) -> hwid_api_messages_pb2.HwidDbExternalResource:
  return hwid_api_messages_pb2.HwidDbExternalResource(component_probe_infos=[
      stubby_pb2.ComponentProbeInfo(
          component_identity=stubby_pb2.ComponentIdentity(
              readable_label=f'label_{cid}_{i}',
              component_id=cid,
          ), probe_info=probe_info)
      for i, (cid, probe_info) in enumerate(probe_info_mapping.items())
  ])


class ConverterTest(unittest.TestCase):

  def testFieldNameConverterConvert_Success(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name3': 'skipped_value',
        'avl_attr_name4': 100,
    })
    converted_values = test_converter.Convert(probe_info)
    self.assertDictEqual(
        {
            'converted_key1': 'value1',
            'converted_key4': converter_types.IntValueType(100),
        }, converted_values)

  def testFieldNameConverterConvert_Missing(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name2': 100,
        'avl_attr_name3': 'skipped_value',
    })
    converted_values = test_converter.Convert(probe_info)
    self.assertIsNone(converted_values)

  def testFieldNameConverterMatchAligned(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name3': 'skipped_value',
        'avl_attr_name4': 100,
    })
    match_case = test_converter.Match(
        {
            'converted_key1': 'value1',
            'converted_key3': 'unused_value3',
            'converted_key4': '0x64',
        }, probe_info)

    self.assertEqual(converter.ProbeValueMatchStatus.ALL_MATCHED, match_case)

  def testFieldNameConverterMatchNotAligned(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name3': 'skipped_value',
        'avl_attr_name4': 100,
    })
    match_case = test_converter.Match(
        {
            'converted_key1': 'value1',
            'converted_key3': 'unused_value3',
            'converted_key4': '200',
        }, probe_info)

    self.assertEqual(converter.ProbeValueMatchStatus.VALUE_UNMATCHED,
                     match_case)

  def testFieldNameConverterMatchNoProbeInfo_MissingHWIDValues(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name4': 100,
    })
    match_case = test_converter.Match(
        {
            'converted_key1': 'value1',
            'converted_key3': 'unused_value3',
        }, probe_info)

    self.assertEqual(converter.ProbeValueMatchStatus.KEY_UNMATCHED, match_case)

  def testFieldNameConverterMatchNoProbeInfo_MissingProbeInfo(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name3': 100,
    })
    match_case = test_converter.Match(
        {
            'converted_key1': 'value1',
            'converted_key3': 'unused_value3',
        }, probe_info)

    self.assertEqual(converter.ProbeValueMatchStatus.INCONVERTIBLE, match_case)

  def testFieldNameConverterMatchValueIsNone(self):
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR4:
                converter.ConvertedValueSpec('converted_key4'),
        })
    probe_info = _ProbeInfoFromMapping({
        'avl_attr_name1': 'value1',
        'avl_attr_name3': 'skipped_value',
        'avl_attr_name4': 100,
    })

    match_case = test_converter.Match(None, probe_info)

    self.assertEqual(converter.ProbeValueMatchStatus.VALUE_IS_NONE, match_case)


class ConverterCollectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.collection = converter.ConverterCollection('category')

  def testCategory(self):
    self.assertEqual('category', self.collection.category)

  def testBasicOperation(self):
    converter1 = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('converted_key2'),
        })
    converter2 = converter.FieldNameConverter.FromFieldMap(
        'converter2', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('another_converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('another_converted_key2'),
        })
    self.collection.AddConverter(converter1)
    self.collection.AddConverter(converter2)

    self.assertIs(converter1, self.collection.GetConverter('converter1'))
    self.assertIs(converter2, self.collection.GetConverter('converter2'))

  def testDuplicateIdentifier(self):
    self.collection.AddConverter(
        converter.FieldNameConverter.FromFieldMap(
            'converter1', {
                TestAVLAttrs.AVL_ATTR1:
                    converter.ConvertedValueSpec('converted_key1'),
                TestAVLAttrs.AVL_ATTR4:
                    converter.ConvertedValueSpec('converted_key4'),
            }))

    self.assertRaisesRegex(
        ValueError, "The converter 'converter1' already exists",
        self.collection.AddConverter,
        converter.FieldNameConverter.FromFieldMap(
            'converter1', {
                TestAVLAttrs.AVL_ATTR2:
                    converter.ConvertedValueSpec('converted_key2'),
                TestAVLAttrs.AVL_ATTR3:
                    converter.ConvertedValueSpec('converted_key3'),
            }))

  def testConflictAttrMapping(self):
    self.collection.AddConverter(
        converter.FieldNameConverter.FromFieldMap(
            'converter1', {
                TestAVLAttrs.AVL_ATTR1:
                    converter.ConvertedValueSpec('converted_key1'),
                TestAVLAttrs.AVL_ATTR4:
                    converter.ConvertedValueSpec('converted_key4'),
            }))

    self.assertRaisesRegex(
        converter.ConverterConflictException,
        ("Converter 'converter2' conflicts with existing converter "
         "'converter1'."), self.collection.AddConverter,
        converter.FieldNameConverter.FromFieldMap(
            'converter2', {
                TestAVLAttrs.AVL_ATTR1:
                    converter.ConvertedValueSpec('converted_key1'),
                TestAVLAttrs.AVL_ATTR3:
                    converter.ConvertedValueSpec('converted_key3'),
                TestAVLAttrs.AVL_ATTR4:
                    converter.ConvertedValueSpec('converted_key4'),
            }))

    self.assertRaises(
        converter.ConverterConflictException, self.collection.AddConverter,
        converter.FieldNameConverter.FromFieldMap(
            'converter3', {
                TestAVLAttrs.AVL_ATTR1:
                    converter.ConvertedValueSpec('converted_key1'),
            }))

  def testMatchProbeValues_Aligned(self):
    converter1 = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('converted_key2'),
        })
    converter2 = converter.FieldNameConverter.FromFieldMap(
        'converter2', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('another_converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('another_converted_key2'),
        })
    self.collection.AddConverter(converter1)
    self.collection.AddConverter(converter2)

    match_result = self.collection.Match(
        {
            'converted_key1': 'value1',
            'converted_key2': '2',
            'unused_key': 'unused_value',
        },
        _ProbeInfoFromMapping({
            'avl_attr_name1': 'value1',
            'avl_attr_name2': 2,
            'avl_attr_name3': 'unrelated',
        }))
    self.assertEqual(
        converter.CollectionMatchResult(_PVAlignmentStatus.ALIGNED,
                                        converter1.identifier), match_result)

  def testMatchProbeValues_PreferKeyUnmatched(self):
    converter1 = converter.FieldNameConverter.FromFieldMap(
        'key_unmatched_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('key_unmatched_converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('key_unmatched_converted_key2'),
        })
    converter2 = converter.FieldNameConverter.FromFieldMap(
        'inconvertible_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('inconvertible_converted_key1'),
            TestAVLAttrs.AVL_ATTR3:
                converter.ConvertedValueSpec('inconvertible_converted_key3'),
        })
    self.collection.AddConverter(converter1)
    self.collection.AddConverter(converter2)

    match_result = self.collection.Match(
        {
            'no_such_key1': 'value1',
            'no_such_key2': '3',
            'unused_key': 'unused_value',
        },
        _ProbeInfoFromMapping({
            'avl_attr_name1': 'value1',
            'avl_attr_name2': 2,
        }))
    self.assertEqual(
        converter.CollectionMatchResult(_PVAlignmentStatus.NOT_ALIGNED,
                                        converter1.identifier), match_result)

  def testMatchProbeValues_PreferValueUnmatched(self):
    converter1 = converter.FieldNameConverter.FromFieldMap(
        'key_unmatched_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('key_unmatched_converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('key_unmatched_converted_key2'),
        })
    converter2 = converter.FieldNameConverter.FromFieldMap(
        'value_unmatched_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('value_unmatched_converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('value_unmatcehd_converted_key2'),
        })
    converter3 = converter.FieldNameConverter.FromFieldMap(
        'inconvertible_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('inconvertible_converted_key1'),
            TestAVLAttrs.AVL_ATTR3:
                converter.ConvertedValueSpec('inconvertible_converted_key2'),
        })
    self.collection.AddConverter(converter1)
    self.collection.AddConverter(converter2)
    self.collection.AddConverter(converter3)

    match_result = self.collection.Match(
        {
            'value_unmatched_converted_key1': 'value1',
            'value_unmatcehd_converted_key2': '3',
            'unused_key': 'unused_value',
        },
        _ProbeInfoFromMapping({
            'avl_attr_name1': 'value1',
            'avl_attr_name2': 2,
        }))
    self.assertEqual(
        converter.CollectionMatchResult(_PVAlignmentStatus.NOT_ALIGNED,
                                        converter2.identifier), match_result)

  def testMatchProbeValues_AllConverterNotConvertible(self):
    converter1 = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('converted_key2'),
        })
    converter2 = converter.FieldNameConverter.FromFieldMap(
        'converter2', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('another_converted_key1'),
            TestAVLAttrs.AVL_ATTR3:
                converter.ConvertedValueSpec('another_converted_key3'),
        })
    self.collection.AddConverter(converter1)
    self.collection.AddConverter(converter2)

    match_result = self.collection.Match(
        {
            'converted_key1': 'value1',
            'converted_key2': '3',
            'unused_key': 'unused_value',
        },
        _ProbeInfoFromMapping({
            'avl_attr_name1': 'value1',
            'avl_attr_name4': 'not_in_converter',
        }))
    self.assertEqual(
        converter.CollectionMatchResult(_PVAlignmentStatus.NOT_ALIGNED, None),
        match_result)

  def testMatchProbeValues_ValueIsNone(self):
    converter1 = converter.FieldNameConverter.FromFieldMap(
        'inconvertible_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('inconvertible_converted_key1'),
            TestAVLAttrs.AVL_ATTR3:
                converter.ConvertedValueSpec('inconvertible_converted_key2'),
        })
    converter2 = converter.FieldNameConverter.FromFieldMap(
        'unmatched_converter', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('unmatched_converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('unmatched_converted_key2'),
        })
    self.collection.AddConverter(converter1)
    self.collection.AddConverter(converter2)

    match_result = self.collection.Match(
        None,
        _ProbeInfoFromMapping({
            'avl_attr_name1': 'value1',
            'avl_attr_name2': 2,
        }))

    self.assertEqual(
        converter.CollectionMatchResult(_PVAlignmentStatus.NOT_ALIGNED,
                                        converter2.identifier), match_result)


class FixedWidthHexValueTypeTest(unittest.TestCase):

  def testHexOutputFormattedSuccess(self):
    source = '0x123'

    # width = 5, source_has_prefix=True, target_has_prefix=True
    str_value = converter.MakeFixedWidthHexValueFactory(
        width=5, source_has_prefix=True, target_has_prefix=True)(
            source)
    self.assertEqual(str_value, '0x00123')

    # width = 5, source_has_prefix=True, target_has_prefix=False
    str_value = converter.MakeFixedWidthHexValueFactory(
        width=5, source_has_prefix=True, target_has_prefix=False)(
            source)
    self.assertEqual(str_value, '00123')

    source = '123'
    # width = 5, source_has_prefix=False, target_has_prefix=True
    str_value = converter.MakeFixedWidthHexValueFactory(
        width=5, source_has_prefix=False, target_has_prefix=True)(
            source)
    self.assertEqual(str_value, '0x00123')

    # width = 5, source_has_prefix=False, target_has_prefix=False
    str_value = converter.MakeFixedWidthHexValueFactory(
        width=5, source_has_prefix=False, target_has_prefix=False)(
            source)
    self.assertEqual(str_value, '00123')

  def testHexOutputFormattedInsufficientWidth(self):
    source = '123'

    str_value = converter.MakeFixedWidthHexValueFactory(width=2)(source)

    with self.assertLogs() as cm:
      self.assertNotEqual(str_value, '0x123')
    self.assertEqual("ERROR:root:Invalid value '123' for str formatter.",
                     cm.output[0].splitlines()[0])


class HexEncodedStrValueFormatterTest(unittest.TestCase):

  def testWithIncorrectFormat_thenRaiseError(self):
    value_formatter = converter.HexEncodedStrValueFormatter(
        source_has_prefix=False, encoding='ascii', fixed_num_bytes=None)

    self.assertRaises(converter_types.StrFormatterError, value_formatter, '673')
    self.assertRaises(converter_types.StrFormatterError, value_formatter, 'xy')

  def testWithIncorrectLength_thenRaiseError(self):
    value_formatter = converter.HexEncodedStrValueFormatter(
        source_has_prefix=False, encoding='ascii', fixed_num_bytes=3)

    self.assertRaises(converter_types.StrFormatterError, value_formatter, '67')

  def testWithPrefix(self):
    value_factory = converter.MakeHexEncodedStrValueFactory(
        source_has_prefix=True)

    self.assertEqual(value_factory('0x616263'), 'abc')
    self.assertEqual(value_factory('0x610063'), 'a\0c')

  def testWithoutPrefix(self):
    value_factory = converter.MakeHexEncodedStrValueFactory()

    self.assertEqual(value_factory('616263'), 'abc')
    self.assertEqual(value_factory('610063'), 'a\0c')

  def testWithFixedLength(self):
    value_factory = converter.MakeHexEncodedStrValueFactory(fixed_num_bytes=3)

    self.assertEqual(value_factory('616263'), 'abc')
    self.assertEqual(value_factory('610063'), 'a\0c')


class ConverterManagerTest(unittest.TestCase):

  def testLinkAVL_TryAllComponents(self):
    # Arrange.
    comp_cls = 'comp_cls1'
    cid = 123
    comp_name1 = f'comp_cls1_{cid}#1'
    comp_name2 = f'comp_cls1_{cid}#2'
    test_converter = converter.FieldNameConverter.FromFieldMap(
        'converter1', {
            TestAVLAttrs.AVL_ATTR1:
                converter.ConvertedValueSpec('converted_key1'),
            TestAVLAttrs.AVL_ATTR2:
                converter.ConvertedValueSpec('converted_key2'),
        })
    converter_collection = converter.ConverterCollection(comp_cls)
    converter_collection.AddConverter(test_converter)
    converter_manager = converter_utils.ConverterManager(
        {comp_cls: converter_collection})

    with v3_builder.DatabaseBuilder.FromEmpty('CHROMEBOOK', 'PROTO') as builder:
      builder.AddComponent(comp_cls, comp_name1, {
          'converted_key1': 'value1',
          'converted_key2': 'value2',
      }, 'supported')
      builder.AddComponent(comp_cls, comp_name2, {
          'converted_key1': 'value1',
          'converted_key2': 'value-not-2',
      }, 'unsupported')
    db_with_components_only = builder.Build().DumpDataWithoutChecksum()
    avl_resource = _HWIDDBExternalResourceFromProbeInfos({
        cid:
            _ProbeInfoFromMapping({
                'avl_attr_name1': 'value1',
                'avl_attr_name2': 'value2',
            })
    })

    # Act.
    avl_linked_db_content = converter_manager.LinkAVL(db_with_components_only,
                                                      avl_resource)

    # Assert.
    avl_linked_db = database.Database.LoadData(avl_linked_db_content)
    self.assertEqual(
        v3_rule.AVLProbeValue(
            identifier='converter1', probe_value_matched=True, values={
                'converted_key1': 'value1',
                'converted_key2': 'value2'
            }),
        avl_linked_db.GetComponents(comp_cls)[comp_name1].values)
    self.assertEqual(
        v3_rule.AVLProbeValue(
            identifier='converter1', probe_value_matched=False, values={
                'converted_key1': 'value1',
                'converted_key2': 'value-not-2'
            }),
        avl_linked_db.GetComponents(comp_cls)[comp_name2].values)


if __name__ == '__main__':
  unittest.main()
