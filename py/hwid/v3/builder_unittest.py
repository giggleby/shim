#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest
from unittest import mock

from cros.factory.hwid.v3 import builder
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import probe
from cros.factory.test.l10n import regions
from cros.factory.unittest_utils import label_utils
from cros.factory.utils import file_utils


_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')
_TEST_DATABASE_PATH = os.path.join(_TEST_DATA_PATH, 'test_builder_db.yaml')
_TEST_INITIAL_DATABASE_PATH = os.path.join(_TEST_DATA_PATH,
                                           'test_database_initial.yaml')


class DetermineComponentNameTest(unittest.TestCase):

  def testMainboard(self):
    comp_cls = 'mainboard'
    value = {
        'version': 'rev2'}
    expected = 'rev2'
    self.assertEqual(expected, builder.DetermineComponentName(comp_cls, value))

  def testFirmwareKeys(self):
    comp_cls = 'firmware_keys'
    value = {
        'key_recovery':
            'c14bd720b70d97394257e3e826bd8f43de48d4ed#devkeys/recovery',
        'key_root': 'b11d74edd286c144e1135b49e7f0bc20cf041f10#devkeys/rootkey'}
    expected = 'firmware_keys_dev'
    self.assertEqual(expected, builder.DetermineComponentName(comp_cls, value))

  def testDRAM(self):
    comp_cls = 'dram'
    value = {
        'part': 'ABCD',
        'size': '2048',
        'slot': '0',
        'timing': 'DDR3-800,DDR3-1066,DDR3-1333,DDR3-1600'}
    expected = 'ABCD_2048mb_0'
    self.assertEqual(expected, builder.DetermineComponentName(comp_cls, value))

  def testHashSuffix(self):
    comp_cls = 'usb_hosts'
    value = {
        'device': '0x4567',
        'revision_id': '0x00',
        'vendor': '0x0123',
        'NaN': float('NaN'),
        'bignum': 12345678901234567890,
        'negativeBignum': -12345678901234567890,
        'None': None,
        'bool': [False, True],
        'recursive': {
            '1': {
                '3': '7',
                '4': '8'
            },
            '2': {
                '5': '9',
                '6': '10'
            }
        }
    }
    expected = 'usb_hosts_721f4481'
    self.assertEqual(expected, builder.DetermineComponentName(comp_cls, value))

  def testHashSuffixOrder(self):
    comp_cls = 'usb_hosts'
    value = {
        '0': '9',
        '1': '8',
        '2': '7',
        '3': '6',
        '4': '5',
    }
    base_hash = builder.DetermineComponentName(comp_cls, value)
    value = {
        '4': '5',
        '3': '6',
        '2': '7',
        '1': '8',
        '0': '9',
    }
    reversed_hash = builder.DetermineComponentName(comp_cls, value)
    self.assertEqual(base_hash, reversed_hash)


class BuilderMethodTest(unittest.TestCase):

  def testFilterSpecialCharacter(self):
    function = builder.FilterSpecialCharacter
    self.assertEqual(function(''), 'unknown')
    self.assertEqual(function('foo  bar'), 'foo_bar')
    self.assertEqual(function('aaa::bbb-ccc'), 'aaa_bbb_ccc')
    self.assertEqual(function('  aaa::bbb-ccc___'), 'aaa_bbb_ccc')

  def testPromptAndAsk(self):
    function = builder.PromptAndAsk
    with mock.patch('builtins.input', return_value='') as mock_input:
      self.assertTrue(function('This is the question.', default_answer=True))
      mock_input.assert_called_once_with('This is the question. [Y/n] ')

    with mock.patch('builtins.input', return_value='') as mock_input:
      self.assertFalse(function('This is the question.', default_answer=False))
      mock_input.assert_called_once_with('This is the question. [y/N] ')

    with mock.patch('builtins.input', return_value='y'):
      self.assertTrue(function('This is the question.', default_answer=True))
      self.assertTrue(function('This is the question.', default_answer=False))

    with mock.patch('builtins.input', return_value='n'):
      self.assertFalse(function('This is the question.', default_answer=True))
      self.assertFalse(function('This is the question.', default_answer=False))

  # TODO (b/204729913)
  @label_utils.Informational
  def testChecksumUpdater(self):
    checksum_updater = builder.ChecksumUpdater()
    self.assertIsNotNone(checksum_updater)
    checksum_test = file_utils.ReadFile(
        os.path.join(_TEST_DATA_PATH, 'CHECKSUM_TEST'))
    updated = checksum_updater.ReplaceChecksum(checksum_test)
    checksum_test_golden = file_utils.ReadFile(
        os.path.join(_TEST_DATA_PATH, 'CHECKSUM_TEST.golden'))
    self.assertEqual(updated, checksum_test_golden)


class DatabaseBuilderTest(unittest.TestCase):

  # TODO (b/212216855)
  @label_utils.Informational
  def testInit(self):

    # From file.
    db_builder = builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH)
    self.assertEqual(
        db_builder.Build(),
        database.Database.LoadFile(_TEST_DATABASE_PATH, verify_checksum=False))

    db = builder.DatabaseBuilder.FromEmpty(project='PROJ',
                                           image_name='PROTO').Build()
    self.assertEqual(db.project, 'PROJ')
    self.assertEqual(db.GetImageName(0), 'PROTO')

  # TODO (b/212216855)
  @label_utils.Informational
  def testAddDefaultComponent(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddDefaultComponent('comp_cls_1')

    db = db_builder.Build()
    # If the probed results don't contain the component value, the default
    # component should be returned.
    bom = probe.GenerateBOMFromProbedResults(db, {}, {}, {}, 'normal', False)[0]
    self.assertEqual(bom.components['comp_cls_1'], ['comp_cls_1_default'])

    # If the probed results contain a real component value, the default
    # component shouldn't be returned.
    bom = probe.GenerateBOMFromProbedResults(
        db, {'comp_cls_1': [{
            'name': 'comp1',
            'values': {
                'value': "1"
            }
        }]}, {}, {}, 'normal', False)[0]
    self.assertEqual(bom.components['comp_cls_1'], ['comp_1_1'])

    with db_builder:
      # One component class can have at most one default component.
      self.assertRaises(ValueError, db_builder.AddDefaultComponent,
                        'comp_cls_1')

  # TODO (b/212216855)
  @label_utils.Informational
  def testAddNullComponent(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddNullComponent('comp_cls_1')

    db = db_builder.Build()
    self.assertEqual(
        {
            0: {
                'comp_cls_1': ['comp_1_1']
            },
            1: {
                'comp_cls_1': ['comp_1_2']
            },
            2: {
                'comp_cls_1': []
            }
        }, db.GetEncodedField('comp_cls_1_field'))

    # The database already accepts a device without a cpu component.
    with db_builder:
      db_builder.AddNullComponent('cpu')
    db = db_builder.Build()
    self.assertEqual({0: {
        'cpu': []
    }}, db.GetEncodedField('cpu_field'))

    # The given component class was not recorded in the database.
    with db_builder:
      db_builder.AddNullComponent('new_component')
    self.assertEqual({0: {
        'new_component': []
    }}, db.GetEncodedField('new_component_field'))

    with db_builder:
      # Should fail if the encoded field of the specified component class
      # encodes more than one class of components.
      self.assertRaises(ValueError, db_builder.AddNullComponent, 'comp_cls_2')

  # TODO (b/212216855)
  @label_utils.Informational
  def testAddFeatureManagementFlagComponents(self):

    comp_cls = 'feature_management_flags'

    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddFeatureManagementFlagComponents()

    db = db_builder.Build()

    comp_items = sorted([{
        comp_name: attr.values
    } for comp_name, attr in db.GetComponents(comp_cls).items()],
                        key=lambda d: sorted(d.items()))

    self.assertEqual(
        comp_items,
        sorted([{
            'feature_management_flags_not_chassis_branded_hw_compliant': {
                'hw_compliance_version': '1',
                'is_chassis_branded': '0'
            }
        }, {
            'feature_management_flags_not_chassis_branded_hw_incompliant': {
                'hw_compliance_version': '0',
                'is_chassis_branded': '0'
            }
        }, {
            'feature_management_flags_chassis_branded_hw_compliant': {
                'hw_compliance_version': '1',
                'is_chassis_branded': '1'
            }
        }], key=lambda d: sorted(d.items())))

    # Should add 3 components to encoded field.
    self.assertEqual(len(db.GetEncodedField(f'{comp_cls}_field').values()), 3)

    # This function should only be called once.
    with self.assertRaises(builder.BuilderException):
      db_builder.AddFeatureManagementFlagComponents()


  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=True)
  def testExtendEncodedFieldToFullCombination(self, unused_patch):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.ExtendEncodedFieldToFullCombination('comp_cls_1_field', 2)

    db = db_builder.Build()
    self.assertCountEqual([
        {
            'comp_cls_1': ['comp_1_1']
        },
        {
            'comp_cls_1': ['comp_1_2']
        },
        {
            'comp_cls_1': ['comp_1_1', 'comp_1_1']
        },
        {
            'comp_cls_1': ['comp_1_1', 'comp_1_2']
        },
        {
            'comp_cls_1': ['comp_1_2', 'comp_1_2']
        },
    ], list(db.GetEncodedField('comp_cls_1_field').values()))

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=False)
  def testExtendEncodedFieldToFullCombination_UserRegret(self, unused_patch):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.ExtendEncodedFieldToFullCombination('comp_cls_1_field', 2)

    db = db_builder.Build()
    self.assertCountEqual([
        {
            'comp_cls_1': ['comp_1_1']
        },
        {
            'comp_cls_1': ['comp_1_2']
        },
    ], list(db.GetEncodedField('comp_cls_1_field').values()))

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk',
              return_value=False)
  def testUpdateByProbedResultsAddFirmware(self, unused_prompt_and_ask_mock):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.UpdateByProbedResults(
          {
              'ro_main_firmware': [{
                  'name': 'generic',
                  'values': {
                      'hash': '1',
                      'version': 'Google_Proj.2222.2.2'
                  }
              }]
          }, {}, {}, [])

    db = db_builder.Build()
    # Should deprecated the legacy firmwares.
    self.assertEqual(
        db.GetComponents('ro_main_firmware')['firmware0'].status,
        common.ComponentStatus.deprecated)

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=False)
  def testUpdateByProbedResultsAddFirmware_SkipFirmwareComponents(
      self, unused_prompt_and_ask_mock):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.UpdateByProbedResults(
          {
              'ro_main_firmware': [{
                  'name': 'generic',
                  'values': {
                      'hash': '1',
                      'version': 'Google_Proj.2222.2.2'
                  }
              }]
          }, {}, {}, [], skip_firmware_components=True)

    db = db_builder.Build()

    self.assertNotIn('Google_Proj_2222_2_2',
                     db.GetComponents('ro_main_firmware'))

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk')
  def testUpdateByProbedResultsWithExtraComponentClasses(self,
                                                         prompt_and_ask_mock):
    for add_null_comp in [False, True]:
      prompt_and_ask_mock.return_value = add_null_comp

      with builder.DatabaseBuilder.FromFilePath(
          db_path=_TEST_DATABASE_PATH) as db_builder:
        db_builder.UpdateByProbedResults(
            {
                'comp_cls_100': [{
                    'name': 'generic',
                    'values': {
                        'key1': 'value1'
                    }
                }, {
                    'name': 'generic',
                    'values': {
                        'key1': 'value1',
                        'key2': 'value2'
                    }
                }, {
                    'name': 'generic',
                    'values': {
                        'key1': 'value1',
                        'key3': 'value3'
                    }
                }, {
                    'name': 'special',
                    'values': {
                        'key4': 'value4'
                    }
                }, {
                    'name': 'special',
                    'values': {
                        'key4': 'value5'
                    }
                }]
            }, {}, {}, [], image_name='NEW_IMAGE')
      db = db_builder.Build()
      self.assertEqual(
          sorted([
              attr.values for attr in db.GetComponents('comp_cls_100').values()
          ], key=lambda d: sorted(d.items())),
          sorted([{
              'key1': 'value1'
          }, {
              'key4': 'value4'
          }, {
              'key4': 'value5'
          }], key=lambda d: sorted(d.items())))

      self.assertEqual(add_null_comp, {'comp_cls_100': []}
                       in db.GetEncodedField('comp_cls_100_field').values())

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=False)
  def testUpdateByProbedResultsWithExtraComponents(self,
                                                   unused_prompt_and_ask_mock):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:

      # {'value': '3'} is the extra component.
      db_builder.UpdateByProbedResults(
          {
              'comp_cls_1': [{
                  'name': 'generic',
                  'values': {
                      'value': '1'
                  }
              }, {
                  'name': 'generic',
                  'values': {
                      'value': '3'
                  }
              }]
          }, {}, {}, [], image_name='NEW_IMAGE')
    db = db_builder.Build()
    self.assertEqual(
        sorted(
            [attr.values for attr in db.GetComponents('comp_cls_1').values()],
            key=lambda d: sorted(d.items())),
        sorted([{
            'value': '1'
        }, {
            'value': '2'
        }, {
            'value': '3'
        }], key=lambda d: sorted(d.items())))

    self.assertIn({'comp_cls_1': sorted(['comp_1_1', '3'])},
                  list(db.GetEncodedField('comp_cls_1_field').values()))

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk')
  def testUpdateByProbedResultsMissingEssentialComponentsAddNull(
      self, prompt_and_ask_mock):
    # If the user answer "N", the null component will be added.
    prompt_and_ask_mock.return_value = False
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.UpdateByProbedResults({}, {}, {}, [], image_name='NEW_IMAGE',
                                       form_factor='CONVERTIBLE')
    db = db_builder.Build()
    for comp_cls in common.FORM_FACTOR_COMPS['CONVERTIBLE']:
      self.assertIn({comp_cls: []},
                    list(db.GetEncodedField(comp_cls + '_field').values()))

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk')
  def testUpdateByProbedResultsMissingEssentialComponentsAddDefault(
      self, prompt_and_ask_mock):
    # If the user answer "Y", the default component will be added if no null
    # component is recorded.
    prompt_and_ask_mock.return_value = True
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.UpdateByProbedResults({}, {}, {}, [], image_name='NEW_IMAGE',
                                       form_factor='CONVERTIBLE')

    db = db_builder.Build()
    for comp_cls in common.FORM_FACTOR_COMPS['CONVERTIBLE']:
      if {
          comp_cls: []
      } in db.GetEncodedField(comp_cls + '_field').values():
        continue
      self.assertIn(comp_cls + '_default', db.GetComponents(comp_cls))
      self.assertIn({comp_cls: [comp_cls + '_default']},
                    list(db.GetEncodedField(comp_cls + '_field').values()))

  # TODO (b/212216855)
  @label_utils.Informational
  def testUpdateByProbedResultsNoEssentialComponentsWithAutoDecline(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH,
        auto_decline_essential_prompt=common.ESSENTIAL_COMPS) as db_builder:
      db_builder.UpdateByProbedResults({}, {}, {}, [], image_name='NEW_IMAGE')
      # The test will fail due to timeout without adding unittest assertion.

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk')
  def testUpdateByProbedResultsNoEssentialComponentsWithoutAutoDecline(
      self, prompt_and_ask_mock):
    prompt_and_ask_mock.return_value = True
    no_auto_decline_components = set(('mainboard', 'dram'))
    auto_decline_components = set(
        common.ESSENTIAL_COMPS) - no_auto_decline_components
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH, auto_decline_essential_prompt=list(
            auto_decline_components)) as db_builder:
      db_builder.UpdateByProbedResults({}, {}, {}, [], image_name='NEW_IMAGE')
    self.assertEqual(
        len(no_auto_decline_components), prompt_and_ask_mock.call_count)

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=False)
  def testUpdateByProbedResultsUpdateEncodedFieldsAndPatternCorrectly(
      self, unused_prompt_and_ask_mock):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:

      # Add a lot of mainboard so that the field need more bits.
      for i in range(10):
        db_builder.UpdateByProbedResults(
            {'mainboard': [{
                'name': 'generic',
                'values': {
                    'rev': str(i)
                }
            }]}, {}, {}, [])

      # Add a lot of cpu so that the field need more bits.
      for i in range(50):
        db_builder.UpdateByProbedResults(
            {'cpu': [{
                'name': 'generic',
                'values': {
                    'vendor': str(i)
                }
            }]}, {}, {}, [])

      # Add more component combination of comp_cls_1, comp_cls_2 and comp_cls_3.
      # Also add an extran component class to trigger adding a new pattern.
      db_builder.UpdateByProbedResults(
          {
              'comp_cls_1': [{
                  'name': 'generic',
                  'values': {
                      'value': '1'
                  }
              }, {
                  'name': 'generic',
                  'values': {
                      'value': '3'
                  }
              }],
              'comp_cls_2': [{
                  'name': 'generic',
                  'values': {
                      'value': '2'
                  }
              }],
              'comp_cls_3': [{
                  'name': 'generic',
                  'values': {
                      'value': '1'
                  }
              }],
              'comp_cls_100': [{
                  'name': 'generic',
                  'values': {
                      'value': '100'
                  }
              }]
          }, {}, {}, [], image_name='NEW_IMAGE')

    db = db_builder.Build()
    self.assertEqual(
        db.GetEncodedField('comp_cls_23_field'), {
            0: {
                'comp_cls_2': ['comp_2_1'],
                'comp_cls_3': ['comp_3_1']
            },
            1: {
                'comp_cls_2': ['comp_2_2'],
                'comp_cls_3': ['comp_3_2']
            },
            2: {
                'comp_cls_2': [],
                'comp_cls_3': []
            },
            3: {
                'comp_cls_2': ['comp_2_2'],
                'comp_cls_3': ['comp_3_1']
            }
        })

    # Check the pattern by checking if the fields bit length are all correct.
    self.assertEqual(
        db.GetEncodedFieldsBitLength(), {
            'mainboard_field': 8,
            'region_field': 5,
            'dram_field': 3,
            'cpu_field': 10,
            'storage_field': 3,
            'chassis_field': 0,
            'firmware_keys_field': 3,
            'ro_main_firmware_field': 5,
            'ro_fp_firmware_field': 1,
            'comp_cls_1_field': 2,
            'comp_cls_23_field': 2,
            'comp_cls_100_field': 0
        })

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=False)
  def testUpdateByProbedResultsNoNeedNewPattern(
      self, unused_prompt_and_ask_mock):
    # No matter if new image name is specified, the pattern will always use
    # the same one if no new encoded fields are added.
    for image_name in [None, 'EVT', 'NEW_IMAGE_NAME']:
      with builder.DatabaseBuilder.FromFilePath(
          db_path=_TEST_DATABASE_PATH) as db_builder:
        db_builder.UpdateByProbedResults(
            {
                'comp_cls_2': [{
                    'name': 'generic',
                    'values': {
                        str(x): str(x)
                    }
                } for x in range(10)]
            }, {}, {}, [], image_name=image_name)

      db = db_builder.Build()
      self.assertEqual(
          db.GetBitMapping(image_id=0),
          db.GetBitMapping(image_id=db.max_image_id))

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.hwid.v3.builder.PromptAndAsk', return_value=False)
  def testUpdateByProbedResultsNeedNewPattern(self, unused_prompt_and_ask_mock):
    # New pattern is required if new encoded fields are added.
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.UpdateByProbedResults(
          {
              'comp_cls_200': [{
                  'name': 'generic',
                  'values': {
                      str(x): str(x)
                  }
              } for x in range(10)]
          }, {}, {}, [], image_name='NEW_IMAGE_NAME')

    db = db_builder.Build()
    self.assertNotIn('comp_cls_200_field', db.GetEncodedFieldsBitLength(0))
    self.assertIn('comp_cls_200_field', db.GetEncodedFieldsBitLength())
    self.assertIn('NEW_IMAGE_NAME', db.GetImageName(db.max_image_id))

    # Should raise error if new image is needed but no image name.
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      self.assertRaises(ValueError, db_builder.UpdateByProbedResults,
                        {'comp_cls_200': [{
                            'name': 'x',
                            'values': {
                                'a': 'b'
                            }
                        }]}, {}, {}, [])

  # TODO (b/212216855)
  @label_utils.Informational
  def testAddRegions(self):
    db_builder = builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH)
    db = db_builder.Build()
    self.assertEqual(db.GetEncodedFieldsBitLength()['region_field'], 5)

    with db_builder:
      self.assertRaises(ValueError, db_builder.AddRegions, [], 'cpu_field')
      self.assertRaises(common.HWIDException, db_builder.AddRegions,
                        ['invalid_region'])

    db = db_builder.Build()
    # Add same region twice, make sure it is not appended again.
    original_region_field = db.GetEncodedField('region_field')
    with db_builder:
      db_builder.AddRegions(['us'])
      db_builder.AddRegions(['us'])
    db = db_builder.Build()
    self.assertDictEqual(original_region_field,
                         db.GetEncodedField('region_field'))

    with db_builder:
      # Add 40 regions, check if the bit of region_field extends or not.
      db_builder.AddRegions(regions.LEGACY_REGIONS_LIST[:40])
    db = db_builder.Build()
    self.assertEqual(db.GetEncodedFieldsBitLength()['region_field'], 6)

  # TODO (b/212216855)
  @label_utils.Informational
  def testAddSkuIds(self):
    db_builder = builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH)

    def _GetSkuIds():
      return [
          e['sku_id'][0]
          for e in db_builder.Build().GetEncodedField('sku_id_field').values()
          if len(e['sku_id'])
      ]

    db = db_builder.Build()
    self.assertEqual(db.GetComponents('sku_id'), {})

    with db_builder:
      # New values will be sorted.
      db_builder._AddSkuIds([0, 1, 50, 2])  # pylint: disable=protected-access
    self.assertEqual(_GetSkuIds(), ['sku_0', 'sku_1', 'sku_2', 'sku_50'])

    with db_builder:
      # Adding the same value again should have no effect.
      db_builder._AddSkuIds([1, 2])  # pylint: disable=protected-access
    self.assertEqual(_GetSkuIds(), ['sku_0', 'sku_1', 'sku_2', 'sku_50'])

    with db_builder:
      # New values should be added after the old values, even if the number is
      # greater.
      db_builder._AddSkuIds([30, 40, 10])  # pylint: disable=protected-access
    self.assertEqual(
        _GetSkuIds(),
        ['sku_0', 'sku_1', 'sku_2', 'sku_50', 'sku_10', 'sku_30', 'sku_40'])

  # TODO (b/212216855)
  @label_utils.Informational
  def testBuilderContext_Fail(self):
    db_builder = builder.DatabaseBuilder.FromEmpty(project='FOO',
                                                   image_name='BAR')
    self.assertRaisesRegex(
        builder.BuilderException,
        'Modification of DB should be called within builder context',
        db_builder.AddDefaultComponent, 'comp_cls_1')

    with builder.DatabaseBuilder.FromEmpty(project='FOO',
                                           image_name='BAR') as db_builder:
      self.assertRaisesRegex(
          builder.BuilderException,
          'Build should be called outside the builder context',
          db_builder.Build)

  # TODO (b/212216855)
  @label_utils.Informational
  def testSanityCheckWhileExitingContext(self):
    db_builder = builder.DatabaseBuilder.FromEmpty(project='FOO',
                                                   image_name='BAR')
    with mock.patch.object(
        db_builder._database,  # pylint: disable=protected-access
        'SanityChecks') as mock_sanity_check:
      with db_builder:
        pass
      mock_sanity_check.assert_called_once_with()

  # TODO (b/204729913)
  @label_utils.Informational
  def testRender(self):
    db_builder = builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH)
    path = file_utils.CreateTemporaryFile()
    db_builder.Render(path)

    # Should be able to load successfully and pass the checksum check.
    database.Database.LoadFile(path)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddComponent(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddComponent('comp_cls_3', 'comp_3_3', {'value': '3'},
                              'unqualified', {'extra_info_1': 'extra_val_1'})
    db = db_builder.Build()

    components = db.GetComponents('comp_cls_3')
    self.assertEqual(
        database.ComponentInfo({'value': '3'}, 'unqualified',
                               {'extra_info_1': 'extra_val_1'}),
        components.get('comp_3_3'))

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddFirmwareComponent(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddFirmwareComponent(
          'ro_main_firmware', {'version': 'Google_Proj.2222.2.2'}, 'firmware1')

    db = db_builder.Build()

    components = db.GetComponents('ro_main_firmware')
    self.assertDictEqual({'ro_main_firmware': ['firmware1']},
                         db.GetEncodedField('ro_main_firmware_field')[1])
    self.assertIn('firmware1', components)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddFirmwareComponent_NewCompClass_AppendNullAtZero(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddFirmwareComponent(
          'ro_ec_firmware', {'version': 'version_string'}, 'firmware1')

    db = db_builder.Build()

    self.assertDictEqual(
        {
            0: {
                'ro_ec_firmware': []
            },
            1: {
                'ro_ec_firmware': ['firmware1']
            },
        }, db.GetEncodedField('ro_ec_firmware_field'))
    self.assertIn(
        database.PatternField('ro_ec_firmware_field', 1),
        db.GetPattern().fields)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddFirmwareComponent_InitialDB_DontUpdatePattern(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_INITIAL_DATABASE_PATH) as db_builder:
      db_builder.AddFirmwareComponent('ro_main_firmware',
                                      {'version': 'Google_Proj.2222.2.2'},
                                      'firmware1', True)

    db = db_builder.Build()

    self.assertFalse(db.GetEncodedFieldsBitLength())
    self.assertDictEqual({'ro_main_firmware': ['firmware1']},
                         db.GetEncodedField('ro_main_firmware_field')[0])

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddFirmwareComponent_RenameSameComponent(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddFirmwareComponent('firmware_keys',
                                      {'key_recovery': 'some_hash'}, 'key1')
      db_builder.AddFirmwareComponent('firmware_keys',
                                      {'key_recovery': 'some_hash'}, 'key2')

    db = db_builder.Build()

    components = db.GetComponents('firmware_keys')
    self.assertNotIn('key1', components)
    self.assertDictEqual({'key_recovery': 'some_hash'},
                         components['key2'].values)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddFirmwareComponent_NameCollision(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddFirmwareComponent('ro_ec_firmware', {
          'version': 'version_string',
          'hash': '0'
      }, 'firmware1')
      db_builder.AddFirmwareComponent('ro_ec_firmware', {
          'version': 'version_string',
          'hash': '1'
      }, 'firmware1')

    db = db_builder.Build()

    self.assertDictEqual(
        {
            0: {
                'ro_ec_firmware': []
            },
            1: {
                'ro_ec_firmware': ['firmware1']
            },
            2: {
                'ro_ec_firmware': ['firmware1_1']
            },
        }, db.GetEncodedField('ro_ec_firmware_field'))
    self.assertIn(
        database.PatternField('ro_ec_firmware_field', 1),
        db.GetPattern().fields)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddComponentCheck_AutoDeprecate(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddComponentCheck('ro_main_firmware',
                                   {'version': 'Google_Proj.2222.2.2'},
                                   'firmware1', True)
      db_builder.AddComponentCheck('ro_fp_firmware',
                                   {'version': 'fpboard_v2.0.22222'},
                                   'firmware1', True)

    db = db_builder.Build()

    components = db.GetComponents('ro_main_firmware')
    self.assertEqual('deprecated', components['firmware0'].status)
    self.assertEqual('supported', components['firmware1'].status)

    components = db.GetComponents('ro_fp_firmware')
    self.assertEqual('deprecated', components['firmware0'].status)
    self.assertEqual('supported', components['firmware1'].status)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddComponentCheck_OnlyDeprecatePrePVTKeys(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddComponentCheck('firmware_keys', {'key_recovery': 'hash1'},
                                   'firmware_keys_dev', True)
      db_builder.AddComponentCheck('firmware_keys', {'key_recovery': 'hash1'},
                                   'firmware_keys_mp_default', True)
      db_builder.AddComponentCheck('firmware_keys', {'key_recovery': 'hash1'},
                                   'firmware_keys_mp_keyid1', True)
      db_builder.AddComponentCheck('firmware_keys', {'key_recovery': 'hash1'},
                                   'firmware_keys_mp_keyid2', True)

    db = db_builder.Build()

    components = db.GetComponents('firmware_keys')
    self.assertEqual('deprecated', components['firmware_keys_dev'].status)
    self.assertEqual('deprecated',
                     components['firmware_keys_mp_default'].status)
    self.assertEqual('supported', components['firmware_keys_mp_keyid1'].status)

  @label_utils.Informational
  def testAddComponentCheck_OnlyDeprecateSameIdentity(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddComponentCheck('ro_main_firmware',
                                   {'version': 'Google_NotProj.2222.2.2'},
                                   'firmware1', True)
      db_builder.AddComponentCheck('ro_fp_firmware',
                                   {'version': 'notfpboard_v2.0.22222'},
                                   'firmware1', True)

    db = db_builder.Build()

    components = db.GetComponents('ro_main_firmware')
    self.assertEqual('supported', components['firmware0'].status)

    components = db.GetComponents('ro_fp_firmware')
    self.assertEqual('supported', components['firmware0'].status)

  @label_utils.Informational
  def testAddComponentCheck_HandleCollisionName(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddComponentCheck('ro_main_firmware', {
          'version': 'Google_Proj.1111.1.1',
          'hash': '1'
      }, 'firmware0', True)

    db = db_builder.Build()

    components = db.GetComponents('ro_main_firmware')
    self.assertDictEqual({
        'version': 'Google_Proj.1111.1.1',
        'hash': '0'
    }, components['firmware0'].values)
    self.assertDictEqual({
        'version': 'Google_Proj.1111.1.1',
        'hash': '1'
    }, components['firmware0_1'].values)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddEncodedFieldComponents(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddEncodedFieldComponents('comp_cls_1_field', 'comp_cls_1',
                                           ['comp_1_1', 'comp_1_2'])
    db = db_builder.Build()

    self.assertDictEqual(
        {
            0: {
                'comp_cls_1': ['comp_1_1']
            },
            1: {
                'comp_cls_1': ['comp_1_2']
            },
            2: {
                'comp_cls_1': ['comp_1_1', 'comp_1_2']
            }
        }, db.GetEncodedField('comp_cls_1_field'))

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddImage_NewPattern(self):
    image_id = 2
    image_name = 'DVT'

    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddImage(image_id=image_id, image_name=image_name,
                          new_pattern=True)
      db_builder.AppendEncodedFieldBit('comp_cls_1_field', 10,
                                       image_id=image_id)
      db_builder.AppendEncodedFieldBit('comp_cls_23_field', 20,
                                       image_id=image_id)
    db = db_builder.Build()

    self.assertEqual(image_name, db.GetImageName(image_id))
    self.assertEqual(image_id, db.GetImageIdByName(image_name))
    self.assertEqual(
        database.PatternDatum(1, 'base8192', [
            database.PatternField('comp_cls_1_field', 10),
            database.PatternField('comp_cls_23_field', 20)
        ]), db.GetPattern(image_id=image_id))

  # TODO (b/204729913)
  @label_utils.Informational
  def testAddImage_ExistingPattern(self):
    image_id = 2
    reference_image_id = 1
    image_name = 'DVT'

    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AddImage(image_id=image_id, image_name=image_name,
                          new_pattern=False,
                          reference_image_id=reference_image_id)
    db = db_builder.Build()

    self.assertEqual(image_name, db.GetImageName(image_id))
    self.assertEqual(image_id, db.GetImageIdByName(image_name))
    self.assertEqual(
        db.GetPattern(image_id=reference_image_id).idx,
        db.GetPattern(image_id=image_id).idx)

  # TODO (b/204729913)
  @label_utils.Informational
  def testAppendEncodedFieldBit(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      db_builder.AppendEncodedFieldBit('comp_cls_1_field', 5, image_id=1)
    db = db_builder.Build()

    self.assertEqual(
        7,
        db.GetEncodedFieldsBitLength(image_id=1)['comp_cls_1_field'])

  # TODO (b/204729913)
  @label_utils.Informational
  def testFillEncodedFieldBit(self):
    with builder.DatabaseBuilder.FromFilePath(
        db_path=_TEST_DATABASE_PATH) as db_builder:
      # Add one more pattern without comp_cls_1.
      db_builder.AddImage(image_id=2, image_name='DVT', new_pattern=True)
      db_builder.AppendEncodedFieldBit('comp_cls_23_field', 0, image_id=2)
      for i in range(3, 18):
        db_builder.AddComponent('comp_cls_1', f'comp_1_{i}', {'value': str(i)},
                                'unqualified', {'extra_info': f'extra_val_{i}'})
        db_builder.AddEncodedFieldComponents('comp_cls_1_field', 'comp_cls_1',
                                             [f'comp_1_{i}'])
      db_builder.FillEncodedFieldBit('comp_cls_1_field')
      db_builder.FillEncodedFieldBit('comp_cls_23_field')
    db = db_builder.Build()

    # Total bits for comp_cls_1_field for image 1 is 5 (17 items).
    self.assertEqual(
        5,
        db.GetEncodedFieldsBitLength(image_id=1)['comp_cls_1_field'])
    # Total bits for comp_cls_23_field for image 2 is 1 (2 items).
    self.assertEqual(
        1,
        db.GetEncodedFieldsBitLength(image_id=2)['comp_cls_23_field'])
    # comp_cls_1_field does not exist in image 2, so no bits are allocated.
    self.assertNotIn('comp_cls_1_field',
                     db.GetEncodedFieldsBitLength(image_id=2))


if __name__ == '__main__':
  unittest.main()
